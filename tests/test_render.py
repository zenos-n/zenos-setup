"""Non-destructive compiler integration; run only in the designated ZenOS VM."""

import copy
import configparser
from itertools import product
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from src import runner
from src.builder import GNOME_EXTENSION_IDS, build_config_documents
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
        payload = default_payload()
        selected = next(page for page in payload["pages"] if page["id"] == "desktop")[
            "gnome_options"
        ]["extension_ids"]
        actual = self._evaluate_flow(
            payload,
            automatic=automatic,
            extension_ids=selected + ["customize-clock-on-lockscreen"],
        )
        self.assertTrue(set(actual["extensions"]) <= set(actual["installedExtensions"]))
        self.assertIn("dash-stacks@neg-zero.com", actual["extensions"])
        self.assertIn("forge@jmmaranan.com", actual["extensions"])
        self.assertIn("window-gap-size=@u 4", actual["userDconf"])
        self.assertIn(
            "window-focus-left=['<Super>h']", actual["userDconf"].replace("@as ", "")
        )
        self.assertIn("pattern='dd.MM  HH:mm'", actual["userDconf"])
        self.assertIn("timeout=2000", actual["userDconf"])
        for section, keys in {
            "org/gnome/shell": {"enabled-extensions": "as"},
            "org/gnome/shell/extensions/forge": {
                "window-gap-size": "u",
                "tiling-mode-enabled": "b",
            },
            "org/gnome/shell/extensions/forge/keybindings": {"window-focus-left": "as"},
            "org/gnome/shell/extensions/date-menu-formatter": {
                "font-size": "i",
                "update-level": "i",
            },
            "org/gnome/shell/extensions/coverflowalttab": {"desaturate-factor": "d"},
            "org/gnome/shell/extensions/notification-timeout": {"timeout": "i"},
            "org/gnome/shell/extensions/rounded-window-corners-reborn": {
                "border-width": "i",
                "global-rounded-corner-settings": "a{sv}",
            },
            "org/gnome/shell/extensions/dash-stacks": {
                "popup-height": "i",
                "popup-width": "i",
                "stacks": "s",
            },
        }.items():
            for key, expected_type in keys.items():
                self.assertEqual(
                    actual["userDconfTypes"][section][key],
                    expected_type,
                    (section, key),
                )
        settings = "\n".join(actual["dconf"])
        self.assertIn("toggle-tiled-left=@as []", settings)
        self.assertIn("close=['<Super>q']", settings.replace("@as ", ""))

    @unittest.skipUnless(
        os.environ.get("ZENOS_SETUP_RUNTIME_SOURCE"), "requires VM runtime snapshot"
    )
    def test_extension_modules_honor_selection_and_tiling_without_branding(self):
        for enabled, tiling, forge_selected in product((False, True), repeat=3):
            with self.subTest(
                enabled=enabled, tiling=tiling, forge_selected=forge_selected
            ):
                payload = copy.deepcopy(FULL_PAYLOAD)
                pages = {page["id"]: page for page in payload["pages"]}
                pages["desktop"]["gnome_options"].update(
                    theme=False,
                    extensions=enabled,
                    tiling=tiling,
                    extension_ids=["dash-stacks"]
                    + (["forge"] if forge_selected else []),
                )
                expected = {"dash-stacks@neg-zero.com"} if enabled else set()
                extension_ids = ["dash-stacks"] if enabled else []
                forge = tiling or (enabled and forge_selected)
                if forge:
                    expected.add("forge@jmmaranan.com")
                    extension_ids.append("forge")
                actual = self._evaluate_flow(payload, extension_ids=extension_ids)
                self.assertEqual(set(actual["extensions"]), expected)
                self.assertEqual(set(actual["installedExtensions"]), expected)
                settings = configparser.ConfigParser(interpolation=None)
                settings.read_string(actual["userDconf"])
                self.assertEqual(
                    "org/gnome/shell/extensions/dash-stacks" in settings, enabled
                )
                self.assertEqual("org/gnome/shell/extensions/forge" in settings, forge)
                self.assertNotIn("org/gnome/shell/extensions/user-theme", settings)
                if forge:
                    self.assertEqual(
                        settings["org/gnome/shell/extensions/forge"][
                            "tiling-mode-enabled"
                        ],
                        str(tiling).lower(),
                    )
                    bindings = settings["org/gnome/shell/extensions/forge/keybindings"]
                    self.assertEqual(
                        bindings["window-focus-left"].removeprefix("@as "),
                        "['<Super>Left']",
                    )
                    self.assertEqual(
                        bindings["prefs-tiling-toggle"].removeprefix("@as "),
                        "['<Super>w']",
                    )
                    self.assertIn(
                        bindings["window-swap-left"].removeprefix("@as "),
                        ("[]", "['']"),
                    )

    @unittest.skipUnless(
        os.environ.get("ZENOS_SETUP_RUNTIME_SOURCE"), "requires VM runtime snapshot"
    )
    def test_each_selected_extension_evaluates_with_current_runtime(self):
        for extension_id in sorted(GNOME_EXTENSION_IDS):
            with self.subTest(extension=extension_id):
                payload = copy.deepcopy(FULL_PAYLOAD)
                next(page for page in payload["pages"] if page["id"] == "desktop")[
                    "gnome_options"
                ].update(
                    theme=False,
                    extensions=True,
                    tiling=False,
                    extension_ids=[extension_id],
                )
                self._evaluate_flow(payload, extension_ids=[extension_id])

    def _evaluate_flow(self, payload, *, automatic=False, extension_ids=()):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            documents = build_config_documents(payload, password_hash="$6$test$hash")
            generated = "\n".join(documents.values())
            for forbidden in (
                "extensionPackages",
                "extensionUuids",
                "extensionUuid",
                "enabled-extensions",
                "org/gnome/shell/extensions/",
            ):
                self.assertNotIn(forbidden, generated)
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
                + " extensionIds = [ "
                + " ".join(json.dumps(name) for name in extension_ids)
                + " ]; }"
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
            self.assertEqual(actual["shell"], "zsh")
            self.assertTrue(actual["zsh"])
            self.assertTrue(actual["zoxide"])
            self.assertTrue(actual["direnv"])
            self.assertTrue(actual["p10k"].endswith("/share/zenos-shell/p10k.zsh"))
            self.assertTrue(actual["homeManagerService"])
            self.assertEqual(actual["disk"], "/dev/vda" if automatic else None)
            if not automatic:
                self.assertEqual(actual["root"], "/dev/vda2")
                self.assertEqual(actual["esp"], "/dev/vda1")
            self.assertTrue(actual["gnome"])
            self.assertCountEqual(actual["extensions"], actual["expectedExtensions"])
            self.assertFalse(actual["globalUuidDefinition"])
            self.assertTrue(actual["coreExtensionPackagesEmpty"])
            self.assertTrue(actual["coreExtensionUuidsEmpty"])
            self.assertFalse(actual["zenfs"])
            return actual

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
                runner._lock_config(str(config))
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
        for enabled in (False, True):
            payload = copy.deepcopy(FULL_PAYLOAD)
            next(page for page in payload["pages"] if page["id"] == "desktop")[
                "gnome_options"
            ].update(
                extensions=enabled,
                extension_ids=sorted(GNOME_EXTENSION_IDS),
                tiling=False,
            )
            payloads.append(payload)
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
