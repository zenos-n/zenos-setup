"""Non-destructive compiler integration; run only in the designated ZenOS VM."""

import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from src import runner
from src.builder import build_config_documents
from src.runner import build_disko_zcfg, build_graphics_config
from test_builder import FULL_PAYLOAD, default_payload


@unittest.skipUnless(
    os.environ.get("ZENOS_SETUP_COMPILER_SOURCE"), "requires VM compiler snapshot"
)
class RenderTests(unittest.TestCase):
    def test_privileged_canonical_handoff_is_confined_to_private_target(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            machine = root / "target"
            (machine / "Users").mkdir(parents=True)
            config = runner._initialize_target_config(directory)
            runner._write_host_documents(
                runner._host_dir(config, "zen-box"),
                build_config_documents(default_payload(), password_hash="$6$test$hash"),
            )
            canonical = machine / "Users/zen/.private/Config/main.zcfg"
            with mock.patch.object(runner, "DRY_RUN", False):
                created = runner._publish_user_sources(config, "zen-box", str(machine))
                try:
                    self.assertEqual(canonical.stat().st_uid, 1000)
                    self.assertEqual(canonical.stat().st_mode & 0o777, 0o600)
                    snapshot = runner._config_snapshot(config, directory, str(machine))
                    copied = Path(snapshot) / "hosts/zen-box/users/zen/main.zcfg"
                    self.assertFalse(copied.is_symlink())
                    self.assertEqual(copied.read_bytes(), canonical.read_bytes())
                    original = canonical.read_bytes()
                    source = Path(config) / "hosts/zen-box/users/zen/main.zcfg"
                    source.unlink()
                    source.write_bytes(original)
                    with self.assertRaises(subprocess.CalledProcessError):
                        runner._publish_user_sources(config, "zen-box", str(machine))
                    self.assertEqual(canonical.read_bytes(), original)
                    source.unlink()
                    source.symlink_to("/Users/zen/.private/Config/main.zcfg")
                    canonical.unlink()
                    canonical.symlink_to(Path(config) / "flake.nix")
                    with self.assertRaises(subprocess.CalledProcessError):
                        runner._config_snapshot(config, directory, str(machine))
                finally:
                    runner._remove_user_sources(created)

    @unittest.skipUnless(
        os.environ.get("ZENOS_SETUP_RUNTIME_SOURCE"), "requires VM runtime snapshot"
    )
    def test_default_flow_evaluates_with_current_runtime(self):
        self._evaluate_default_flow(automatic=False)

    @unittest.skipUnless(
        os.environ.get("ZENOS_SETUP_RUNTIME_SOURCE"), "requires VM runtime snapshot"
    )
    def test_default_automatic_flow_evaluates_with_current_runtime(self):
        self._evaluate_default_flow(automatic=True)

    def _evaluate_default_flow(self, *, automatic):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            documents = build_config_documents(
                default_payload(), password_hash="$6$test$hash"
            )
            documents["drives.zcfg"] = (
                build_disko_zcfg("/dev/vda")
                if automatic
                else """
legacy.fileSystems = {
  "/" = { device = "/dev/vda2"; fsType = "ext4"; };
  "/boot" = { device = "/dev/vda1"; fsType = "vfat"; };
};
"""
            )
            documents["host.zcfg"] += "import ./drives.zcfg;\n"
            for name, text in documents.items():
                (root / name).parent.mkdir(parents=True, exist_ok=True)
                (root / name).write_text(text)
            env = {
                **os.environ,
                "PYTHONPATH": os.environ["ZENOS_SETUP_COMPILER_SOURCE"],
            }
            compiled = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "zenlang",
                    "compile",
                    str(root / "host.zcfg"),
                    "-o",
                    str(root / "host.nix"),
                ],
                env=env,
                capture_output=True,
                text=True,
            )
            self.assertEqual(compiled.returncode, 0, compiled.stderr)
            expression = (
                "import "
                + str(Path(__file__).with_name("evaluate-host.nix"))
                + " { "
                + " ".join(
                    key + " = " + json.dumps(value) + ";"
                    for key, value in {
                        "nixpkgsSource": os.environ["ZENOS_SETUP_NIXPKGS_SOURCE"],
                        "zenpkgsSource": os.environ["ZENOS_SETUP_RUNTIME_SOURCE"],
                        "hostModule": str(root / "host.nix"),
                    }.items()
                )
                + " }"
            )
            result = subprocess.run(
                ["nix", "eval", "--impure", "--json", "--expr", expression],
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            actual = json.loads(result.stdout)
            self.assertEqual(actual["hostname"], "zen-box")
            self.assertEqual(actual["home"], "/Users/zen")
            self.assertEqual(actual["disk"], "/dev/vda" if automatic else None)
            if not automatic:
                self.assertEqual(actual["root"], "/dev/vda2")
                self.assertEqual(actual["esp"], "/dev/vda1")
            self.assertTrue(actual["gnome"])
            self.assertIn("dash-stacks@neg-zero.com", actual["extensions"])
            self.assertIn("forge@jmmaranan.com", actual["extensions"])
            settings = "\n".join(actual["dconf"])
            self.assertIn("window-gap-size=@u 4", settings)
            self.assertIn("toggle-tiled-left=@as []", settings)
            self.assertIn("close=['<Super>q']", settings.replace("@as ", ""))

    def test_hardware_input_lock_and_pending_host_contract(self):
        # This small flake tests handoff mechanics, not the image-owned NixOS runtime.
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "private-hardware"
            source.mkdir()
            (source / "hardware-configuration.nix").write_text("{ ... }: { }\n")
            (source / "detection.json").write_text('{"version": 1}\n')
            added = subprocess.run(
                [
                    "nix",
                    "store",
                    "add-path",
                    "--name",
                    "zenos-setup-hardware",
                    str(source),
                ],
                text=True,
                capture_output=True,
                check=True,
            )
            store_path = added.stdout.strip()
            config = root / "config"
            host = config / "hosts" / "oobe-test"
            host.mkdir(parents=True)
            runner._write_json(
                str(host / "hardware.json"),
                {
                    "version": 1,
                    "storePath": store_path,
                    "sha256": runner._sha256(
                        str(source / "hardware-configuration.nix")
                    ),
                },
            )
            runner._write_json(str(host / "oobe.json"), {"status": "pending"})
            template = """{
  inputs.setup-hardware = { url = "path:@ZENOS_SETUP_HARDWARE@"; flake = false; };
  outputs = { self, setup-hardware }: {
    nixosConfigurations.oobe-test.config.system.build.toplevel.drvPath =
      assert builtins.pathExists (setup-hardware + "/hardware-configuration.nix");
      assert (builtins.fromJSON (builtins.readFile ./hosts/oobe-test/oobe.json)).status == "pending";
      "/nix/store/test-only-handoff.drv";
  };
}
"""
            with mock.patch.object(runner, "DRY_RUN", False):
                runner._bind_hardware(
                    str(config), template, str(host / "hardware.json")
                )
                runner._lock_and_evaluate(str(config), "oobe-test")
            self.assertNotIn(
                runner.HARDWARE_PLACEHOLDER, (config / "flake.nix").read_text()
            )
            self.assertTrue((config / "flake.lock").is_file())
            self.assertEqual(
                sorted(path.name for path in config.rglob("*.nix")), ["flake.nix"]
            )

    def test_current_compiler_accepts_split_hosts_and_nix_parser_accepts_output(self):
        payloads = [FULL_PAYLOAD, default_payload()]
        for desktop in ("gnome", "kde", "xfce", "cinnamon", "budgie", "mate", "none"):
            payloads.append(
                {
                    "pages": [
                        {
                            "id": "desktop",
                            "install_de": desktop != "none",
                            "desktop_environment": desktop,
                        }
                    ]
                }
            )
        oobe = copy.deepcopy(FULL_PAYLOAD)
        oobe["oobe"] = True
        payloads.append(oobe)
        for index, payload in enumerate(payloads):
            with self.subTest(index=index), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                documents = build_config_documents(
                    payload, password_hash="$6$test$hash"
                )
                documents["drives.zcfg"] = build_disko_zcfg("/dev/vda")
                documents["graphics.zcfg"] = build_graphics_config([])
                documents["host.zcfg"] += (
                    "import ./drives.zcfg;\nimport ./graphics.zcfg;\n"
                )
                for name, text in documents.items():
                    (root / name).parent.mkdir(parents=True, exist_ok=True)
                    (root / name).write_text(text, encoding="utf-8")
                env = {
                    **os.environ,
                    "PYTHONPATH": os.environ["ZENOS_SETUP_COMPILER_SOURCE"],
                }
                for command in ("check", "compile"):
                    args = [
                        sys.executable,
                        "-m",
                        "zenlang",
                        command,
                        str(root / "host.zcfg"),
                    ]
                    if command == "compile":
                        args += ["-o", str(root / "host.nix")]
                    result = subprocess.run(
                        args, env=env, text=True, capture_output=True
                    )
                    self.assertEqual(result.returncode, 0, result.stderr)
                result = subprocess.run(
                    ["nix-instantiate", "--parse", str(root / "host.nix")],
                    text=True,
                    capture_output=True,
                )
                self.assertEqual(result.returncode, 0, result.stderr)
