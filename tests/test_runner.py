import hashlib
import json
import os
from pathlib import Path
import subprocess
import stat
import tempfile
import unittest
from unittest import mock
from contextlib import ExitStack

from src import runner
from test_builder import default_payload


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
        self.assertIn("system.disks = {", zcfg)
        self.assertIn("disk.main = {", zcfg)
        self.assertIn('device = "/dev/nvme0n1";', zcfg)

    def test_config_layout_allows_only_flake_lock_and_host_files(self):
        with tempfile.TemporaryDirectory() as work_dir:
            root = runner._dry_config_root(work_dir)
            os.makedirs(os.path.join(root, "hosts", "zen-test"))
            runner._write_text(os.path.join(root, "flake.nix"), "{ }")
            for name in ("host.zcfg", "hardware.json"):
                runner._write_text(os.path.join(root, "hosts", "zen-test", name), "")
            runner._validate_config_layout(root)

            runner._write_text(os.path.join(root, "README"), "not allowed")
            with self.assertRaisesRegex(RuntimeError, "unexpected config root"):
                runner._validate_config_layout(root)

    def test_initial_config_copies_only_the_iso_flake_template(self):
        with tempfile.TemporaryDirectory() as source_dir:
            with tempfile.TemporaryDirectory() as work_dir:
                template = os.path.join(source_dir, "flake.nix")
                text = (
                    '{ inputs.setup-hardware.url = "path:@ZENOS_SETUP_HARDWARE@"; }\n'
                )
                runner._write_text(template, text)
                runner._write_text(
                    os.path.join(source_dir, "README"), "must not copy\n"
                )
                with mock.patch.object(runner, "ISO_CONFIG_TEMPLATE", template):
                    config_dir = runner._initialize_target_config(work_dir)

                self.assertEqual(set(os.listdir(config_dir)), {"flake.nix", "hosts"})
                with open(
                    os.path.join(config_dir, "flake.nix"), encoding="utf-8"
                ) as file:
                    self.assertEqual(file.read(), text)
                self.assertEqual(config_dir, runner._dry_config_root(work_dir))

    def test_oobe_config_layout_requires_an_existing_flake(self):
        with tempfile.TemporaryDirectory() as work_dir:
            root = runner._dry_config_root(work_dir)
            os.makedirs(os.path.join(root, "hosts"))

            with self.assertRaisesRegex(RuntimeError, "must contain flake.nix"):
                runner._validate_config_layout(root)


class UserSourceTests(unittest.TestCase):
    def _seed(self, work_dir):
        config = runner._initialize_target_config(work_dir)
        runner._write_host_documents(
            runner._host_dir(config, "zen-box"),
            runner.build_config_documents(
                default_payload(), password_hash="$6$test$hash"
            ),
        )
        machine = os.path.join(work_dir, "target")
        source = os.path.join(config, "hosts/zen-box/users/zen/main.zcfg")
        canonical = os.path.join(machine, "Users/zen/.private/Config/main.zcfg")
        return config, machine, source, canonical

    def test_publish_and_snapshot_preserve_one_canonical_source(self):
        with tempfile.TemporaryDirectory() as work:
            config, machine, source, canonical = self._seed(work)
            with open(source) as file:
                original = file.read()
            created = runner._publish_user_sources(config, "zen-box", machine)
            self.assertEqual(len(created), 1)
            self.assertEqual(created[0]["username"], "zen")
            self.assertEqual(
                created[0]["identity"][:2],
                [os.stat(canonical).st_dev, os.stat(canonical).st_ino],
            )
            self.assertEqual(
                os.readlink(source), "/Users/zen/.private/Config/main.zcfg"
            )
            with open(canonical) as file:
                self.assertEqual(file.read(), original)
            self.assertEqual(os.stat(canonical).st_mode & 0o777, 0o600)
            runner._write_text(canonical, original + "# user edit\n")
            snapshot = runner._config_snapshot(config, work, machine)
            copied = os.path.join(snapshot, "hosts/zen-box/users/zen/main.zcfg")
            self.assertFalse(os.path.islink(copied))
            with open(copied) as file:
                self.assertEqual(file.read(), original + "# user edit\n")
            self.assertTrue(os.path.islink(source))
            runner._remove_user_sources(created)
            self.assertTrue(os.path.exists(canonical))

    def test_privileged_rollback_preserves_mutations_with_injected_run(self):
        real_run = subprocess.run
        for mutation in (
            "unchanged",
            "edited",
            "replaced",
            "file-link",
            "parent-link",
            "parent-replaced",
            "missing",
        ):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as work:
                config, machine, source, canonical = self._seed(work)
                Path(machine).mkdir()

                # Execute the same stdlib helper without privilege escalation in
                # this unit regression; the VM smoke separately exercises sudo.
                def run_helper(command, **kwargs):
                    self.assertEqual(command[:2], ["sudo", "-n"])
                    self.assertEqual(command[3], runner.user_sources.__file__)
                    return real_run(command[2:], **kwargs)

                with (
                    mock.patch.object(runner, "DRY_RUN", False),
                    mock.patch.object(
                        runner.subprocess, "run", side_effect=run_helper
                    ) as run,
                ):
                    created = runner._publish_user_sources(config, "zen-box", machine)
                    path = Path(canonical)
                    original = path.read_bytes()
                    other = Path(work) / "user-owned.zcfg"
                    other.write_bytes(b"user-owned\n")
                    if mutation == "edited":
                        path.write_bytes(original + b"# edit\n")
                    elif mutation == "replaced":
                        replacement = path.with_name("replacement")
                        replacement.write_bytes(original)
                        replacement.replace(path)
                    elif mutation == "file-link":
                        path.unlink()
                        path.symlink_to(other)
                    elif mutation in {"parent-link", "parent-replaced"}:
                        moved = path.parent.with_name("OriginalConfig")
                        path.parent.rename(moved)
                        if mutation == "parent-link":
                            path.parent.symlink_to(moved, target_is_directory=True)
                        else:
                            path.parent.mkdir()
                            path.write_bytes(original)
                    elif mutation == "missing":
                        path.unlink()
                    runner._remove_user_sources(created)
                    self.assertEqual(run.call_count, 2)
                    if mutation in {"unchanged", "missing"}:
                        self.assertFalse(path.exists())
                    else:
                        self.assertTrue(path.exists())
                    if mutation == "edited":
                        self.assertEqual(path.read_bytes(), original + b"# edit\n")
                    if mutation in {"parent-link", "parent-replaced"}:
                        self.assertEqual((moved / "main.zcfg").read_bytes(), original)
                    self.assertEqual(other.read_bytes(), b"user-owned\n")

    def test_rollback_rechecks_file_after_hashing(self):
        with tempfile.TemporaryDirectory() as work:
            config, machine, source, canonical = self._seed(work)
            created = runner._publish_user_sources(config, "zen-box", machine)
            original_digest = hashlib.file_digest

            def mutate_during_read(file, algorithm):
                digest = original_digest(file, algorithm)
                Path(canonical).write_text("edited while hashing\n")
                return digest

            with mock.patch.object(
                runner.user_sources.hashlib,
                "file_digest",
                side_effect=mutate_during_read,
            ):
                runner._remove_user_sources(created)
            self.assertEqual(Path(canonical).read_text(), "edited while hashing\n")

    def test_existing_source_is_not_overwritten_or_removed(self):
        with tempfile.TemporaryDirectory() as work:
            config, machine, source, canonical = self._seed(work)
            runner._write_text(canonical, "user-owned\n")
            with self.assertRaisesRegex(RuntimeError, "already exists"):
                runner._publish_user_sources(config, "zen-box", machine)
            with open(canonical) as file:
                self.assertEqual(file.read(), "user-owned\n")
            self.assertFalse(os.path.islink(source))

    def test_invalid_host_links_and_generated_user_nix_are_rejected(self):
        with tempfile.TemporaryDirectory() as work:
            config, machine, source, canonical = self._seed(work)
            os.unlink(source)
            for target in (
                "/etc/passwd",
                "/Users/other/.private/Config/main.zcfg",
                "../main.zcfg",
            ):
                os.symlink(target, source)
                with self.assertRaisesRegex(
                    RuntimeError, "invalid canonical user link"
                ):
                    runner._config_snapshot(config, work, machine)
                os.unlink(source)
            runner._write_text(source, "")
            runner._write_text(os.path.join(os.path.dirname(source), "main.nix"), "{ }")
            with self.assertRaisesRegex(RuntimeError, "invalid user config directory"):
                runner._validate_config_layout(config)

    def test_missing_or_redirected_canonical_target_is_rejected(self):
        with tempfile.TemporaryDirectory() as work:
            config, machine, source, canonical = self._seed(work)
            runner._publish_user_sources(config, "zen-box", machine)
            os.unlink(canonical)
            with self.assertRaisesRegex(RuntimeError, "invalid canonical user source"):
                runner._config_snapshot(config, work, machine)
            os.symlink(os.path.join(config, "flake.nix"), canonical)
            with self.assertRaisesRegex(RuntimeError, "invalid canonical user source"):
                runner._config_snapshot(config, work, machine)


class InitialInstallTests(unittest.TestCase):
    def test_catalog_defaults_complete_full_installer_dry_run(self):
        for mode in ("auto", "manual"):
            data = default_payload()
            pages = {page["id"]: page for page in data["pages"]}
            if mode == "manual":
                pages["disks"].update(
                    mode="manual",
                    partitions=[
                        {"device": "/dev/vda1", "fs_type": "vfat"},
                        {"device": "/dev/vda2", "fs_type": "ext4"},
                    ],
                )
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as work_dir:
                with mock.patch(
                    "src.builder.hash_password", return_value="$6$test$hash"
                ):
                    with mock.patch("src.runner.subprocess.Popen") as popen:
                        runner._run_long(data, pages, work_dir, _progress, None)
                    popen.assert_not_called()
                host = os.path.join(
                    runner._dry_config_root(work_dir), "hosts", "zen-box"
                )
                with open(os.path.join(host, "desktop.zcfg")) as file:
                    self.assertIn("dash-stacks", file.read())
                self.assertFalse(os.path.exists(os.path.join(host, "oobe.json")))

    def test_preflight_failure_never_reaches_disk_or_install(self):
        disk = {"id": "disks", "mode": "auto", "disks": ["vda"]}
        for failure in ("_compile_host", "_lock_and_evaluate"):
            with (
                self.subTest(failure=failure),
                tempfile.TemporaryDirectory() as work_dir,
            ):
                with mock.patch.object(
                    runner, failure, side_effect=RuntimeError("invalid config")
                ):
                    with mock.patch.object(runner, "_cleanup_mount_root") as cleanup:
                        with mock.patch.object(runner, "_nixos_install") as install:
                            with mock.patch.object(runner, "_run") as command:
                                with self.assertRaisesRegex(
                                    RuntimeError, "invalid config"
                                ):
                                    runner._run_short(
                                        {"disks": disk}, work_dir, _progress, None
                                    )
                            self.assertFalse(
                                any(
                                    "disko" in call.args[0]
                                    for call in command.call_args_list
                                )
                            )
                        install.assert_not_called()
                    cleanup.assert_not_called()

    def test_invalid_template_fails_before_disk_operations(self):
        disk = {"id": "disks", "mode": "auto", "disks": ["vda"]}
        with tempfile.TemporaryDirectory() as work_dir:
            template = runner._write_text(
                os.path.join(work_dir, "bad-template.nix"), "{ }"
            )
            with mock.patch.object(runner, "ISO_CONFIG_TEMPLATE", template):
                with mock.patch.object(runner, "_cleanup_mount_root") as cleanup:
                    with self.assertRaisesRegex(RuntimeError, "exactly once"):
                        runner._run_short({"disks": disk}, work_dir, _progress, None)
                cleanup.assert_not_called()

    def test_unsupported_choice_fails_before_template_and_disk_work(self):
        disk = {"id": "disks", "mode": "auto", "disks": ["vda"]}
        data = {
            "pages": [
                disk,
                {"id": "computer_name", "hostname": "zen-final"},
                {
                    "id": "desktop",
                    "install_de": True,
                    "desktop_environment": "gnome",
                    "gnome_options": {
                        "theme": False,
                        "extensions": True,
                        "extension_ids": ["unknown-extension"],
                    },
                },
            ]
        }
        with tempfile.TemporaryDirectory() as work_dir:
            with mock.patch.object(runner, "_initialize_target_config") as initialize:
                with mock.patch.object(runner, "_cleanup_mount_root") as cleanup:
                    with self.assertRaisesRegex(ValueError, "unknown GNOME extension"):
                        runner._run_long(
                            data,
                            {page["id"]: page for page in data["pages"]},
                            work_dir,
                            _progress,
                            None,
                        )
                cleanup.assert_not_called()
            initialize.assert_not_called()

    def test_manual_preflight_is_provisional_and_target_hardware_owns_filesystems(self):
        disk = {
            "id": "disks",
            "mode": "manual",
            "partitions": [
                {"device": "/dev/vda1", "fs_type": "vfat"},
                {"device": "/dev/vda2", "fs_type": "ext4"},
            ],
        }
        logs = []
        with tempfile.TemporaryDirectory() as work_dir:
            runner._run_short({"disks": disk}, work_dir, _progress, logs.append)
            root = runner._dry_config_root(work_dir)
            host = os.listdir(os.path.join(root, "hosts"))[0]
            self.assertFalse(
                os.path.exists(os.path.join(root, "hosts", host, "drives.zcfg"))
            )
            with open(
                os.path.join(work_dir, "preflight", "hosts", host, "drives.zcfg")
            ) as file:
                self.assertIn('"/boot"', file.read())
            generated_nix = [
                os.path.relpath(os.path.join(directory, name), root)
                for directory, _, files in os.walk(root)
                for name in files
                if name.endswith(".nix")
            ]
            self.assertEqual(generated_nix, ["flake.nix"])
        commands = [line for line in logs if "would run:" in line]
        self.assertFalse(any(" disko " in line for line in commands))
        hardware = [line for line in commands if "nixos-generate-config" in line]
        self.assertNotIn("--root", hardware[0])
        self.assertIn("--no-filesystems --show-hardware-config", hardware[0])
        self.assertIn("--root /mnt --show-hardware-config", hardware[1])

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
                    "apps.zcfg",
                    "desktop.zcfg",
                    "drives.zcfg",
                    "graphics.zcfg",
                    "hardware.json",
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
            self.assertEqual(marker["version"], 3)
            self.assertEqual(
                set(marker["artifacts"]),
                {"disko", "graphics", "hardware"},
            )
            for metadata in marker["artifacts"].values():
                self.assertEqual(
                    metadata["sha256"],
                    runner._sha256(os.path.join(host_dir, metadata["file"])),
                )
            runner._validate_config_layout(config_dir)

        command_logs = [line for line in logs if "would run:" in line]
        disko = [line for line in command_logs if " disko --mode disko " in line]
        self.assertEqual(len(disko), 1)
        hardware = [line for line in command_logs if "nixos-generate-config" in line]
        self.assertEqual(len(hardware), 2)
        self.assertIn("--no-filesystems", hardware[0])
        self.assertFalse(any("wipefs" in line or "sgdisk" in line for line in logs))
        self.assertEqual(sum("umount --recursive /mnt" in line for line in logs), 2)

    def test_short_command_order_checks_template_before_disko(self):
        logs = []
        with tempfile.TemporaryDirectory() as work_dir:
            self._run_short(work_dir, logs)

        joined = "\n".join(logs)
        positions = [
            joined.index("nixos-generate-config"),
            joined.index("nix flake lock"),
            joined.index("nix eval --offline"),
            joined.index("disko --mode disko"),
            joined.rindex("nixos-generate-config"),
            joined.rindex("nix eval --offline"),
            joined.index("nixos-install --flake"),
        ]
        self.assertEqual(positions, sorted(positions))
        self.assertEqual(joined.count("nix flake lock\n"), 1)
        self.assertGreaterEqual(joined.count("nix flake lock --offline"), 1)
        self.assertRegex(
            joined, r"config-snapshot-[^\s#]+#nixosConfigurations.oobe-abc123"
        )

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
            snapshot = runner._config_snapshot(
                config_dir, work_dir, os.path.join(work_dir, "target")
            )
            for directory, _subdirs, files in os.walk(snapshot):
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

    def test_install_failure_removes_only_new_canonical_source(self):
        data = default_payload()
        pages = {page["id"]: page for page in data["pages"]}
        with tempfile.TemporaryDirectory() as work:
            with mock.patch("src.builder.hash_password", return_value="$6$test$hash"):
                with mock.patch.object(
                    runner, "_nixos_install", side_effect=RuntimeError("failed")
                ):
                    with self.assertRaisesRegex(RuntimeError, "failed"):
                        runner._run_long(data, pages, work, _progress, None)
            self.assertFalse(
                os.path.exists(
                    os.path.join(work, "target/Users/zen/.private/Config/main.zcfg")
                )
            )


class OobeTests(unittest.TestCase):
    def test_postcommit_failures_preserve_sources_and_retry_cleanup(self):
        for failure in (
            "completion",
            "plan",
            "validation",
            "temporary",
            "intent",
            "progress",
        ):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as work:
                config, temporary, _ = self._seed_pending(work)
                data, pages = self._payload()
                final = Path(config) / "hosts/zen-final"
                canonical = Path(work) / "target/Users/zen/.private/Config/main.zcfg"
                write_json = runner._write_json
                unlink = os.unlink
                validate = runner._validate_config_layout

                def write(path, value, **kwargs):
                    if (
                        failure == "completion"
                        and Path(path).name == "oobe-complete.json"
                    ):
                        raise OSError("marker write failed")
                    return write_json(path, value, **kwargs)

                def remove(path, *args, **kwargs):
                    if Path(path) == final / (
                        "install-plan.json"
                        if failure == "plan"
                        else "oobe-finalize.json"
                    ):
                        if failure in {"plan", "intent"}:
                            raise OSError("cleanup unlink failed")
                    return unlink(path, *args, **kwargs)

                def check(path):
                    if (
                        failure == "validation"
                        and (final / "oobe-complete.json").exists()
                    ):
                        raise OSError("cleanup validation failed")
                    return validate(path)

                def progress(value):
                    if failure == "progress" and value == 0.85:
                        raise RuntimeError("progress failed")

                with (
                    mock.patch.object(
                        runner, "_read_current_host", return_value="oobe-abc123"
                    ),
                    mock.patch(
                        "src.builder.hash_password", return_value="$6$test$hash"
                    ),
                    mock.patch.object(runner, "_nixos_rebuild_boot") as rebuild,
                ):
                    with ExitStack() as stack:
                        stack.enter_context(
                            mock.patch.object(runner, "_write_json", side_effect=write)
                        )
                        stack.enter_context(
                            mock.patch.object(runner.os, "unlink", side_effect=remove)
                        )
                        stack.enter_context(
                            mock.patch.object(
                                runner, "_validate_config_layout", side_effect=check
                            )
                        )
                        rollback = stack.enter_context(
                            mock.patch.object(runner, "_remove_user_sources")
                        )
                        if failure == "temporary":
                            stack.enter_context(
                                mock.patch.object(
                                    runner,
                                    "_remove_config_tree",
                                    side_effect=OSError("temporary cleanup failed"),
                                )
                            )
                        with self.assertRaisesRegex(
                            RuntimeError, "boot generation succeeded"
                        ):
                            runner._run_oobe(data, pages, work, progress, None)
                        rollback.assert_not_called()
                    self.assertTrue((final / "host.zcfg").is_file())
                    self.assertTrue((final / "users/zen/main.zcfg").is_symlink())
                    original = canonical.read_bytes()
                    with mock.patch.object(runner, "_publish_user_sources") as publish:
                        runner._run_oobe(data, pages, work, _progress, None)
                        publish.assert_not_called()
                    self.assertEqual(
                        rebuild.call_count, 2 if failure == "completion" else 1
                    )
                    self.assertEqual(canonical.read_bytes(), original)
                    self.assertFalse(Path(temporary).exists())
                    self.assertFalse((final / "install-plan.json").exists())
                    self.assertFalse((final / "oobe-finalize.json").exists())
                    self.assertTrue((final / "oobe-complete.json").is_file())
                    # Cleanup remains idempotent even after the pending host is gone.
                    runner._run_oobe(data, pages, work, _progress, None)

    def test_uncertain_commit_retry_never_rolls_back_on_rebuild_failure(self):
        with tempfile.TemporaryDirectory() as work:
            config, _, _ = self._seed_pending(work)
            data, pages = self._payload()
            write = runner._write_json

            def fail_completion(path, value, **kwargs):
                if Path(path).name == "oobe-complete.json":
                    raise OSError("marker unavailable")
                return write(path, value, **kwargs)

            with (
                mock.patch.object(
                    runner, "_read_current_host", return_value="oobe-abc123"
                ),
                mock.patch("src.builder.hash_password", return_value="$6$test$hash"),
            ):
                with (
                    mock.patch.object(runner, "_nixos_rebuild_boot"),
                    mock.patch.object(
                        runner, "_write_json", side_effect=fail_completion
                    ),
                ):
                    with self.assertRaisesRegex(
                        RuntimeError, "boot generation succeeded"
                    ):
                        runner._run_oobe(data, pages, work, _progress, None)
                with (
                    mock.patch.object(
                        runner,
                        "_nixos_rebuild_boot",
                        side_effect=RuntimeError("retry failed"),
                    ),
                    mock.patch.object(runner, "_remove_user_sources") as rollback,
                ):
                    with self.assertRaisesRegex(RuntimeError, "retry failed"):
                        runner._run_oobe(data, pages, work, _progress, None)
                    rollback.assert_not_called()
                self.assertTrue(Path(config, "hosts/zen-final/host.zcfg").is_file())
                self.assertTrue(
                    Path(work, "target/Users/zen/.private/Config/main.zcfg").is_file()
                )

    def test_catalog_defaults_complete_oobe_dry_run(self):
        data = default_payload()
        data["oobe"] = True
        pages = {page["id"]: page for page in data["pages"]}
        with tempfile.TemporaryDirectory() as work_dir:
            config_dir, temporary_dir, _ = self._seed_pending(work_dir)
            with mock.patch.object(
                runner, "_read_current_host", return_value="oobe-abc123"
            ):
                with mock.patch(
                    "src.builder.hash_password", return_value="$6$test$hash"
                ):
                    with mock.patch("src.runner.subprocess.Popen") as popen:
                        runner._run_oobe(data, pages, work_dir, _progress, None)
                    popen.assert_not_called()
            self.assertFalse(os.path.exists(temporary_dir))
            self.assertTrue(
                os.path.isfile(
                    os.path.join(config_dir, "hosts", "zen-box", "oobe-complete.json")
                )
            )

    def _seed_pending(self, work_dir, temporary_host="oobe-abc123"):
        config_dir = runner._dry_config_root(work_dir)
        host_dir = os.path.join(config_dir, "hosts", temporary_host)
        os.makedirs(host_dir)
        runner._write_text(os.path.join(config_dir, "flake.nix"), "{ }")
        hardware_source = os.path.join(work_dir, "immutable-hardware")
        runner._write_text(
            os.path.join(hardware_source, "hardware-configuration.nix"),
            "hardware-config-from-install\n",
        )
        hardware = (
            json.dumps(
                {
                    "version": 1,
                    "storePath": hardware_source,
                    "sha256": runner._sha256(
                        os.path.join(hardware_source, "hardware-configuration.nix")
                    ),
                }
            )
            + "\n"
        ).encode()
        graphics = b"graphics-config-from-install\n"
        disko = b"disko-config-from-install\n"
        with open(os.path.join(host_dir, "hardware.json"), "wb") as file:
            file.write(hardware)
        with open(os.path.join(host_dir, "graphics.zcfg"), "wb") as file:
            file.write(graphics)
        with open(os.path.join(host_dir, "drives.zcfg"), "wb") as file:
            file.write(disko)
        runner._write_text(os.path.join(host_dir, "host.zcfg"), "temporary\n")
        runner._write_json(
            os.path.join(host_dir, "install-plan.json"),
            {"disk": {"mode": "auto", "devices": ["vda"], "partitions": []}},
        )
        runner._write_json(
            os.path.join(host_dir, "oobe.json"),
            {
                "artifacts": {
                    "disko": {
                        "file": "drives.zcfg",
                        "sha256": hashlib.sha256(disko).hexdigest(),
                    },
                    "graphics": {
                        "file": "graphics.zcfg",
                        "sha256": hashlib.sha256(graphics).hexdigest(),
                    },
                    "hardware": {
                        "file": "hardware.json",
                        "sha256": hashlib.sha256(hardware).hexdigest(),
                    },
                },
                "status": "pending",
                "temporaryHost": temporary_host,
                "version": 3,
            },
        )
        return (
            config_dir,
            host_dir,
            {
                "drives.zcfg": disko,
                "graphics.zcfg": graphics,
                "hardware.json": hardware,
            },
        )

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
            with mock.patch(
                "src.runner._read_current_host", return_value="oobe-abc123"
            ):
                with mock.patch(
                    "src.builder.hash_password", return_value="$6$test$hash"
                ):
                    runner._run_oobe(data, pages, work_dir, _progress, logs.append)

            final_dir = os.path.join(config_dir, "hosts", "zen-final")
            self.assertFalse(os.path.exists(temporary_dir))
            self.assertTrue(os.path.isdir(final_dir))
            for filename, expected in artifacts.items():
                with open(os.path.join(final_dir, filename), "rb") as file:
                    self.assertEqual(file.read(), expected)
            self.assertFalse(
                os.path.exists(os.path.join(final_dir, "install-plan.json"))
            )
            with open(
                os.path.join(final_dir, "oobe-complete.json"), encoding="utf-8"
            ) as file:
                completion = json.load(file)
            self.assertEqual(completion["status"], "complete")
            self.assertEqual(completion["sourceHost"], "oobe-abc123")
            runner._validate_config_layout(config_dir)
            snapshot = runner._config_snapshot(
                config_dir, work_dir, os.path.join(work_dir, "target")
            )
            for directory, _subdirs, files in os.walk(snapshot):
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
            with mock.patch(
                "src.runner._read_current_host", return_value="oobe-abc123"
            ):
                with mock.patch(
                    "src.builder.hash_password", return_value="$6$test$hash"
                ):
                    with mock.patch(
                        "src.runner._nixos_rebuild_boot",
                        side_effect=lambda *_args, **_kwargs: events.append("rebuild"),
                    ):
                        with mock.patch(
                            "src.runner._write_json", side_effect=record_json
                        ):
                            runner._run_oobe(data, pages, work_dir, _progress, None)

        self.assertEqual(events[:2], ["rebuild", "completion"])

    def test_rebuild_failure_retains_marker_and_temporary_host(self):
        data, pages = self._payload()
        with tempfile.TemporaryDirectory() as work_dir:
            config_dir, temporary_dir, _hardware = self._seed_pending(work_dir)
            marker_path = os.path.join(temporary_dir, "oobe.json")
            with mock.patch(
                "src.runner._read_current_host", return_value="oobe-abc123"
            ):
                with mock.patch(
                    "src.builder.hash_password", return_value="$6$test$hash"
                ):
                    with mock.patch(
                        "src.runner._nixos_rebuild_boot",
                        side_effect=RuntimeError("failed"),
                    ):
                        with self.assertRaisesRegex(RuntimeError, "failed"):
                            runner._run_oobe(data, pages, work_dir, _progress, None)

            self.assertTrue(os.path.isdir(temporary_dir))
            self.assertTrue(os.path.isfile(marker_path))
            self.assertFalse(
                os.path.exists(os.path.join(config_dir, "hosts", "zen-final"))
            )
            self.assertFalse(
                os.path.exists(
                    os.path.join(work_dir, "target/Users/zen/.private/Config/main.zcfg")
                )
            )

    def test_oobe_requires_unique_marker_for_current_host(self):
        data, pages = self._payload()
        with tempfile.TemporaryDirectory() as work_dir:
            self._seed_pending(work_dir)
            self._seed_pending(work_dir, temporary_host="oobe-other1")
            with mock.patch(
                "src.runner._read_current_host", return_value="oobe-abc123"
            ):
                with self.assertRaisesRegex(RuntimeError, "exactly one"):
                    runner._run_oobe(data, pages, work_dir, _progress, None)

    def test_hardware_checksum_failure_retains_pending_state(self):
        data, pages = self._payload()
        with tempfile.TemporaryDirectory() as work_dir:
            _config_dir, temporary_dir, _hardware = self._seed_pending(work_dir)
            runner._write_text(
                os.path.join(temporary_dir, "hardware.json"), "tampered\n"
            )
            with mock.patch(
                "src.runner._read_current_host", return_value="oobe-abc123"
            ):
                with self.assertRaisesRegex(RuntimeError, "checksum mismatch"):
                    runner._run_oobe(data, pages, work_dir, _progress, None)
            self.assertTrue(os.path.isfile(os.path.join(temporary_dir, "oobe.json")))

    def test_immutable_hardware_checksum_is_verified(self):
        data, pages = self._payload()
        with tempfile.TemporaryDirectory() as work_dir:
            self._seed_pending(work_dir)
            runner._write_text(
                os.path.join(
                    work_dir, "immutable-hardware", "hardware-configuration.nix"
                ),
                "changed",
            )
            with mock.patch.object(
                runner, "_read_current_host", return_value="oobe-abc123"
            ):
                with mock.patch.object(runner, "_nixos_rebuild_boot") as rebuild:
                    with self.assertRaisesRegex(RuntimeError, "checksum mismatch"):
                        runner._run_oobe(data, pages, work_dir, _progress, None)
                rebuild.assert_not_called()

    def test_generated_nix_in_editable_tree_is_rejected(self):
        with tempfile.TemporaryDirectory() as work_dir:
            root, host_dir, _ = self._seed_pending(work_dir)
            for filename in ("host.nix", "hardware-configuration.nix", "kernel.nix"):
                path = runner._write_text(os.path.join(host_dir, filename), "{ }")
                with self.assertRaisesRegex(RuntimeError, "unexpected files"):
                    runner._validate_config_layout(root)
                os.unlink(path)


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
        self.assertIn(
            'legacy.services.xserver.videoDrivers = [ "modesetting" "nvidia" ];', config
        )
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
