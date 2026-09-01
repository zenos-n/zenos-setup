import hashlib
import json
import os
import stat
import tempfile
import unittest
from unittest import mock

from src import runner


def _progress(_value):
    pass


class RunnerSafetyTests(unittest.TestCase):
    def test_dry_run_is_default_and_never_starts_subprocess(self):
        self.assertTrue(runner.DRY_RUN)
        with mock.patch("src.runner.subprocess.Popen") as popen:
            runner._run(["false"])
        popen.assert_not_called()

    def test_auto_disk_accepts_exactly_one_supported_whole_disk(self):
        self.assertEqual(runner._selected_auto_disk({"disks": ["vda"]}), "/dev/vda")
        self.assertEqual(
            runner._selected_auto_disk({"disks": ["/dev/nvme0n1"]}),
            "/dev/nvme0n1",
        )
        for disks in ([], ["vda", "vdb"]):
            with self.subTest(disks=disks):
                with self.assertRaisesRegex(RuntimeError, "exactly one"):
                    runner._selected_auto_disk({"disks": disks})

    def test_auto_disk_rejects_partitions_and_unsafe_paths(self):
        unsafe = (
            "/dev/vda1",
            "/dev/nvme0n1p1",
            "/dev/mmcblk0p2",
            "/dev/disk/by-id/example",
            "/tmp/vda",
            "../vda",
            "loop0",
        )
        for device in unsafe:
            with self.subTest(device=device):
                with self.assertRaises(RuntimeError):
                    runner._selected_auto_disk({"disks": [device]})

    def test_real_mode_requires_a_whole_block_device(self):
        fake_stat = mock.Mock(st_mode=stat.S_IFREG)
        with mock.patch.object(runner, "DRY_RUN", False):
            with mock.patch("src.runner.os.stat", return_value=fake_stat):
                with self.assertRaisesRegex(RuntimeError, "whole block device"):
                    runner._selected_auto_disk({"disks": ["vda"]})

    def test_disko_output_is_fixed_declarative_layout(self):
        config = runner.build_disko_config("/dev/nvme0n1")

        self.assertIn('device = "/dev/nvme0n1";', config)
        self.assertIn('type = "gpt";', config)
        self.assertIn('size = "1G";', config)
        self.assertIn('type = "EF00";', config)
        self.assertIn('format = "vfat";', config)
        self.assertIn('mountpoint = "/boot";', config)
        self.assertIn('size = "100%";', config)
        self.assertIn('format = "ext4";', config)
        self.assertIn('mountpoint = "/";', config)
        self.assertNotIn("wipefs", config)
        self.assertNotIn("sgdisk", config)

        zcfg = runner.build_disko_zcfg("/dev/nvme0n1")
        self.assertIn('legacy.disko.devices.disk.main = {', zcfg)
        self.assertIn('device = "/dev/nvme0n1";', zcfg)

    def test_config_layout_allows_only_flake_lock_and_host_files(self):
        with tempfile.TemporaryDirectory() as work_dir:
            root = runner._dry_config_root(work_dir)
            os.makedirs(os.path.join(root, "hosts", "zen-test"))
            runner._write_text(os.path.join(root, "flake.nix"), "{ }")
            for name in ("host.zcfg", "host.nix", "hardware-configuration.nix"):
                runner._write_text(os.path.join(root, "hosts", "zen-test", name), "")
            runner._validate_config_layout(root)

            runner._write_text(os.path.join(root, "README"), "not allowed")
            with self.assertRaisesRegex(RuntimeError, "unexpected config root"):
                runner._validate_config_layout(root)

    def test_initial_config_copies_only_the_iso_flake_template(self):
        with tempfile.TemporaryDirectory() as source_dir:
            with tempfile.TemporaryDirectory() as work_dir:
                template = os.path.join(source_dir, "flake.nix")
                runner._write_text(template, "{ description = \"ISO template\"; }\n")
                runner._write_text(os.path.join(source_dir, "README"), "must not copy\n")
                with mock.patch.object(runner, "ISO_CONFIG_TEMPLATE", template):
                    config_dir = runner._initialize_target_config(work_dir)

                self.assertEqual(set(os.listdir(config_dir)), {"flake.nix", "hosts"})
                with open(os.path.join(config_dir, "flake.nix"), encoding="utf-8") as file:
                    self.assertEqual(file.read(), "{ description = \"ISO template\"; }\n")
                self.assertEqual(config_dir, runner._dry_config_root(work_dir))

    def test_oobe_config_layout_requires_an_existing_flake(self):
        with tempfile.TemporaryDirectory() as work_dir:
            root = runner._dry_config_root(work_dir)
            os.makedirs(os.path.join(root, "hosts"))

            with self.assertRaisesRegex(RuntimeError, "must contain flake.nix"):
                runner._validate_config_layout(root)


class InitialInstallTests(unittest.TestCase):
    def _run_short(self, work_dir, logs):
        disk = {"id": "disks", "mode": "auto", "disks": ["vda"]}
        pages = {"disks": disk}
        with mock.patch("src.runner._rand_suffix", return_value="abc123"):
            with mock.patch("src.runner.subprocess.Popen") as popen:
                runner._run_short(pages, work_dir, _progress, logs.append)
        popen.assert_not_called()
        return runner._dry_config_root(work_dir), "oobe-abc123"

    def test_short_install_persists_marker_and_uses_only_disko(self):
        logs = []
        with tempfile.TemporaryDirectory() as work_dir:
            config_dir, host = self._run_short(work_dir, logs)
            host_dir = os.path.join(config_dir, "hosts", host)

            self.assertTrue(os.path.isfile(os.path.join(config_dir, "flake.nix")))
            self.assertEqual(set(os.listdir(config_dir)), {"flake.nix", "hosts"})
            self.assertEqual(
                set(os.listdir(host_dir)),
                {
                    ".hidden",
                    "desktop.zcfg",
                    "drives.zcfg",
                    "graphics.zcfg",
                    "hardware-configuration.nix",
                    "host.nix",
                    "host.zcfg",
                    "install-plan.json",
                    "oobe.json",
                    "system.zcfg",
                },
            )
            with open(os.path.join(host_dir, "oobe.json"), encoding="utf-8") as file:
                marker = json.load(file)
            self.assertEqual(marker["temporaryHost"], host)
            self.assertEqual(marker["status"], "pending")
            self.assertEqual(marker["version"], 2)
            self.assertEqual(
                set(marker["artifacts"]),
                {"disko", "graphics", "hardware"},
            )
            for metadata in marker["artifacts"].values():
                self.assertEqual(
                    metadata["sha256"], runner._sha256(os.path.join(host_dir, metadata["file"]))
                )
            runner._validate_config_layout(config_dir)

        command_logs = [line for line in logs if "would run:" in line]
        disko = [line for line in command_logs if " disko --mode disko " in line]
        self.assertEqual(len(disko), 1)
        hardware = [line for line in command_logs if "nixos-generate-config" in line]
        self.assertEqual(len(hardware), 1)
        self.assertIn("--no-filesystems", hardware[0])
        self.assertFalse(any("wipefs" in line or "sgdisk" in line for line in logs))
        self.assertEqual(sum("umount --recursive /mnt" in line for line in logs), 2)

    def test_short_command_order_is_disko_hardware_lock_eval_install(self):
        logs = []
        with tempfile.TemporaryDirectory() as work_dir:
            self._run_short(work_dir, logs)

        joined = "\n".join(logs)
        positions = [
            joined.index("disko --mode disko"),
            joined.index("nixos-generate-config"),
            joined.index("nix flake lock --offline"),
            joined.index("nix eval --offline"),
            joined.index("nixos-install --flake"),
        ]
        self.assertEqual(positions, sorted(positions))
        self.assertIn("/Config/ZenOS#nixosConfigurations.oobe-abc123", joined)

    def test_long_install_has_no_oobe_marker_or_plaintext_password(self):
        password = "very-secret-password"
        disk = {"id": "disks", "mode": "auto", "disks": ["vda"]}
        data = {
            "oobe": False,
            "pages": [
                {"id": "computer_name", "hostname": "zen-final"},
                {
                    "id": "user",
                    "username": "zen",
                    "fullname": "Zen User",
                    "password": password,
                },
                disk,
            ],
        }
        pages = {page["id"]: page for page in data["pages"]}

        with tempfile.TemporaryDirectory() as work_dir:
            with mock.patch("src.builder.hash_password", return_value="$6$test$hash"):
                runner._run_long(data, pages, work_dir, _progress, None)
            config_dir = runner._dry_config_root(work_dir)
            host_dir = os.path.join(config_dir, "hosts", "zen-final")
            self.assertNotIn("oobe.json", os.listdir(host_dir))
            self.assertNotIn("install-plan.json", os.listdir(host_dir))
            for directory, _subdirs, files in os.walk(config_dir):
                for filename in files:
                    with open(os.path.join(directory, filename), "rb") as file:
                        self.assertNotIn(password.encode(), file.read())

    def test_disko_failure_still_runs_final_cleanup(self):
        disk = {"id": "disks", "mode": "auto", "disks": ["vda"]}
        commands = []

        def fail_disko(command, _log_fn=None, **_kwargs):
            commands.append(command)
            if "disko" in command:
                raise RuntimeError("Disko failed")

        with tempfile.TemporaryDirectory() as work_dir:
            with mock.patch("src.runner._run", side_effect=fail_disko):
                with mock.patch("src.runner._rand_suffix", return_value="abc123"):
                    with self.assertRaisesRegex(RuntimeError, "Disko failed"):
                        runner._run_short({"disks": disk}, work_dir, _progress, None)

        unmounts = [command for command in commands if "umount" in command]
        self.assertEqual(len(unmounts), 2)


class OobeTests(unittest.TestCase):
    def _seed_pending(self, work_dir, temporary_host="oobe-abc123"):
        config_dir = runner._dry_config_root(work_dir)
        host_dir = os.path.join(config_dir, "hosts", temporary_host)
        os.makedirs(host_dir)
        runner._write_text(os.path.join(config_dir, "flake.nix"), "{ }")
        hardware = b"hardware-config-from-install\n"
        graphics = b"graphics-config-from-install\n"
        disko = b"disko-config-from-install\n"
        with open(os.path.join(host_dir, "hardware-configuration.nix"), "wb") as file:
            file.write(hardware)
        with open(os.path.join(host_dir, "graphics.zcfg"), "wb") as file:
            file.write(graphics)
        with open(os.path.join(host_dir, "drives.zcfg"), "wb") as file:
            file.write(disko)
        runner._write_text(os.path.join(host_dir, "host.zcfg"), "temporary\n")
        runner._write_text(os.path.join(host_dir, "host.nix"), "temporary\n")
        runner._write_json(
            os.path.join(host_dir, "install-plan.json"),
            {"disk": {"mode": "auto", "devices": ["vda"], "partitions": []}},
        )
        runner._write_json(
            os.path.join(host_dir, "oobe.json"),
            {
                "artifacts": {
                    "disko": {"file": "drives.zcfg", "sha256": hashlib.sha256(disko).hexdigest()},
                    "graphics": {"file": "graphics.zcfg", "sha256": hashlib.sha256(graphics).hexdigest()},
                    "hardware": {
                        "file": "hardware-configuration.nix",
                        "sha256": hashlib.sha256(hardware).hexdigest(),
                    },
                },
                "status": "pending",
                "temporaryHost": temporary_host,
                "version": 2,
            },
        )
        return config_dir, host_dir, {
            "drives.zcfg": disko,
            "graphics.zcfg": graphics,
            "hardware-configuration.nix": hardware,
        }

    def _payload(self, password="oobe-plaintext-password"):
        data = {
            "oobe": True,
            "pages": [
                {"id": "computer_name", "hostname": "zen-final"},
                {
                    "id": "user",
                    "username": "zen",
                    "fullname": "Zen User",
                    "password": password,
                },
            ],
        }
        return data, {page["id"]: page for page in data["pages"]}

    def test_oobe_atomically_renames_host_transfers_hardware_and_uses_boot(self):
        logs = []
        password = "oobe-plaintext-password"
        data, pages = self._payload(password)
        with tempfile.TemporaryDirectory() as work_dir:
            config_dir, temporary_dir, artifacts = self._seed_pending(work_dir)
            with mock.patch("src.runner._read_current_host", return_value="oobe-abc123"):
                with mock.patch("src.builder.hash_password", return_value="$6$test$hash"):
                    runner._run_oobe(data, pages, work_dir, _progress, logs.append)

            final_dir = os.path.join(config_dir, "hosts", "zen-final")
            self.assertFalse(os.path.exists(temporary_dir))
            self.assertTrue(os.path.isdir(final_dir))
            for filename, expected in artifacts.items():
                with open(os.path.join(final_dir, filename), "rb") as file:
                    self.assertEqual(file.read(), expected)
            self.assertFalse(os.path.exists(os.path.join(final_dir, "install-plan.json")))
            with open(os.path.join(final_dir, "oobe-complete.json"), encoding="utf-8") as file:
                completion = json.load(file)
            self.assertEqual(completion["status"], "complete")
            self.assertEqual(completion["sourceHost"], "oobe-abc123")
            runner._validate_config_layout(config_dir)
            for directory, _subdirs, files in os.walk(config_dir):
                for filename in files:
                    with open(os.path.join(directory, filename), "rb") as file:
                        self.assertNotIn(password.encode(), file.read())

        joined = "\n".join(logs)
        self.assertIn("nixos-rebuild boot --flake", joined)
        self.assertNotIn("nixos-rebuild switch", joined)
        self.assertNotIn("chown -R root:root --", joined)
        self.assertNotIn("systemctl reboot", joined)

    def test_completion_follows_rebuild_and_is_atomic(self):
        events = []
        data, pages = self._payload()

        original_write_json = runner._write_json

        def record_json(path, value, *, atomic=False):
            if os.path.basename(path) == "oobe-complete.json":
                self.assertTrue(atomic)
                events.append("completion")
            return original_write_json(path, value, atomic=atomic)

        with tempfile.TemporaryDirectory() as work_dir:
            self._seed_pending(work_dir)
            with mock.patch("src.runner._read_current_host", return_value="oobe-abc123"):
                with mock.patch("src.builder.hash_password", return_value="$6$test$hash"):
                    with mock.patch(
                        "src.runner._nixos_rebuild_boot",
                        side_effect=lambda *_args, **_kwargs: events.append("rebuild"),
                    ):
                        with mock.patch("src.runner._write_json", side_effect=record_json):
                            runner._run_oobe(data, pages, work_dir, _progress, None)

        self.assertEqual(events[:2], ["rebuild", "completion"])

    def test_rebuild_failure_retains_marker_and_temporary_host(self):
        data, pages = self._payload()
        with tempfile.TemporaryDirectory() as work_dir:
            config_dir, temporary_dir, _hardware = self._seed_pending(work_dir)
            marker_path = os.path.join(temporary_dir, "oobe.json")
            with mock.patch("src.runner._read_current_host", return_value="oobe-abc123"):
                with mock.patch("src.builder.hash_password", return_value="$6$test$hash"):
                    with mock.patch(
                        "src.runner._nixos_rebuild_boot", side_effect=RuntimeError("failed")
                    ):
                        with self.assertRaisesRegex(RuntimeError, "failed"):
                            runner._run_oobe(data, pages, work_dir, _progress, None)

            self.assertTrue(os.path.isdir(temporary_dir))
            self.assertTrue(os.path.isfile(marker_path))
            self.assertFalse(os.path.exists(os.path.join(config_dir, "hosts", "zen-final")))

    def test_oobe_requires_unique_marker_for_current_host(self):
        data, pages = self._payload()
        with tempfile.TemporaryDirectory() as work_dir:
            self._seed_pending(work_dir)
            self._seed_pending(work_dir, temporary_host="oobe-other1")
            with mock.patch("src.runner._read_current_host", return_value="oobe-abc123"):
                with self.assertRaisesRegex(RuntimeError, "exactly one"):
                    runner._run_oobe(data, pages, work_dir, _progress, None)

    def test_hardware_checksum_failure_retains_pending_state(self):
        data, pages = self._payload()
        with tempfile.TemporaryDirectory() as work_dir:
            _config_dir, temporary_dir, _hardware = self._seed_pending(work_dir)
            runner._write_text(
                os.path.join(temporary_dir, "hardware-configuration.nix"), "tampered\n"
            )
            with mock.patch("src.runner._read_current_host", return_value="oobe-abc123"):
                with self.assertRaisesRegex(RuntimeError, "checksum mismatch"):
                    runner._run_oobe(data, pages, work_dir, _progress, None)
            self.assertTrue(os.path.isfile(os.path.join(temporary_dir, "oobe.json")))


class GraphicsConfigTests(unittest.TestCase):
    def test_amd_config_enables_amdgpu_early(self):
        config = runner.build_graphics_config(
            [{"address": "0000:03:00.0", "bootVga": True, "vendor": 0x1002}]
        )
        self.assertIn('legacy.services.xserver.videoDrivers = [ "amdgpu" ];', config)
        self.assertIn('legacy.boot.initrd.kernelModules = [ "amdgpu" ];', config)
        self.assertNotIn("hardware.nvidia", config)

    def test_intel_nvidia_hybrid_enables_prime_offload(self):
        config = runner.build_graphics_config(
            [
                {"address": "0000:00:02.0", "bootVga": True, "vendor": 0x8086},
                {"address": "0000:01:00.0", "bootVga": False, "vendor": 0x10DE},
            ]
        )
        self.assertIn('legacy.services.xserver.videoDrivers = [ "modesetting" "nvidia" ];', config)
        self.assertIn('intelBusId = "PCI:0:2:0";', config)
        self.assertIn('nvidiaBusId = "PCI:1:0:0";', config)
        self.assertIn("offload.enableOffloadCmd = true", config)

    def test_unknown_gpu_keeps_generic_graphics_support(self):
        config = runner.build_graphics_config(
            [{"address": "0000:00:01.0", "bootVga": True, "vendor": 0x1AF4}]
        )
        self.assertIn("legacy.hardware.graphics.enable = true", config)
        self.assertNotIn("videoDrivers", config)


class KernelSelectionTests(unittest.TestCase):
    def test_popcorn_variant_matches_chassis(self):
        self.assertIn('"D-generic"', runner.build_kernel_config(False))
        self.assertIn('"L-generic"', runner.build_kernel_config(True))

    def test_laptop_detection_uses_dmi_then_battery_fallback(self):
        with tempfile.TemporaryDirectory() as root:
            dmi = os.path.join(root, "class", "dmi", "id")
            os.makedirs(dmi)
            runner._write_text(os.path.join(dmi, "chassis_type"), "10\n")
            self.assertTrue(runner.is_laptop_environment(root))

        with tempfile.TemporaryDirectory() as root:
            battery = os.path.join(root, "class", "power_supply", "BAT0")
            os.makedirs(battery)
            runner._write_text(os.path.join(battery, "type"), "Battery\n")
            self.assertTrue(runner.is_laptop_environment(root))


if __name__ == "__main__":
    unittest.main()
