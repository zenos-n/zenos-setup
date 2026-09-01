"""Persistent ZenOS installer and OOBE backend."""

from __future__ import annotations

import hashlib
import json
import os
import random
import re
import shutil
import stat
import string
import subprocess
import tempfile
import threading
from datetime import datetime, timezone

from .builder import (
    build_config_documents,
    build_execution_plan,
    format_nix,
    strip_disko_config,
)


# Destructive and system-changing commands require an explicit launch-time opt in.
DRY_RUN = os.environ.get("ZENOS_SETUP_DRY_RUN", "1") != "0"

ISO_CONFIG_TEMPLATE = "/iso-config-template/flake.nix"
MOUNT_ROOT = "/mnt"
TARGET_CONFIG_ROOT = "/mnt/etc/ZenOS/Flake"
OOBE_CONFIG_ROOT = "/Config/ZenOS/Flake"

_WHOLE_DISK_NAME = re.compile(
    r"(?:[hsv]d[a-z]+|xvd[a-z]+|nvme\d+n\d+|mmcblk\d+)"
)
_HOST_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_-]{0,62}")
_SHA256 = re.compile(r"[0-9a-f]{64}")
_ROOT_ENTRIES = {"flake.nix", "flake.lock", "hosts"}
_HOST_FILES = {
    "apps.zcfg",
    "desktop.zcfg",
    "drives.zcfg",
    "graphics.zcfg",
    "hardware-configuration.nix",
    "host.nix",
    "host.zcfg",
    "install-plan.json",
    "oobe-complete.json",
    "oobe.json",
    "system.zcfg",
    "users.zcfg",
}


def _rand_suffix(n: int = 6) -> str:
    return "".join(random.choices(string.ascii_lowercase + string.digits, k=n))


def _emit(fn, msg: str) -> None:
    if fn:
        fn(str(msg))


def _run(cmd: list[str], log_fn=None, **popen_kwargs) -> None:
    """Run a command with combined streamed output, or only log it in dry-run."""
    if DRY_RUN:
        _emit(log_fn, f"[dry-run] would run: {' '.join(str(part) for part in cmd)}")
        return

    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        **popen_kwargs,
    )
    assert proc.stdout is not None
    for line in proc.stdout:
        _emit(log_fn, line.rstrip())
    proc.wait()
    if proc.returncode != 0:
        raise subprocess.CalledProcessError(proc.returncode, cmd)


def _print_config(log_fn, path: str, config_str: str) -> None:
    _emit(log_fn, f"\n--- generated config: {path} ---\n{config_str}\n---\n")


def _validate_host_name(host_name: str) -> str:
    if not isinstance(host_name, str) or not _HOST_NAME.fullmatch(host_name):
        raise RuntimeError(f"invalid host name: {host_name!r}")
    return host_name


def _selected_auto_disk(disk: dict) -> str:
    selected = disk.get("disks", [])
    if not isinstance(selected, list) or len(selected) != 1:
        raise RuntimeError("automatic disk mode requires exactly one selected disk")

    value = selected[0]
    if not isinstance(value, str) or not value:
        raise RuntimeError("automatic disk mode requires a valid disk name")
    if value.startswith("/dev/"):
        device = value
    elif "/" not in value:
        device = f"/dev/{value}"
    else:
        raise RuntimeError(f"unsafe automatic disk path: {value!r}")

    name = device.removeprefix("/dev/")
    if device != f"/dev/{name}" or not _WHOLE_DISK_NAME.fullmatch(name):
        raise RuntimeError(
            f"automatic disk selection is not a supported whole disk: {device!r}"
        )

    if not DRY_RUN:
        try:
            mode = os.stat(device).st_mode
        except OSError as exc:
            raise RuntimeError(f"automatic disk is not available: {device}") from exc
        sysfs_device = f"/sys/class/block/{name}"
        if (
            os.path.realpath(device) != device
            or not stat.S_ISBLK(mode)
            or not os.path.exists(sysfs_device)
            or os.path.exists(os.path.join(sysfs_device, "partition"))
        ):
            raise RuntimeError(
                f"automatic disk selection is not a whole block device: {device}"
            )
    return device


def build_disko_config(device: str) -> str:
    """Render the fixed whole-disk layout accepted by the installer."""
    if not isinstance(device, str) or not device.startswith("/dev/"):
        raise ValueError("Disko device must be an absolute /dev path")
    name = device.removeprefix("/dev/")
    if device != f"/dev/{name}" or not _WHOLE_DISK_NAME.fullmatch(name):
        raise ValueError("Disko device must be a supported whole disk")
    return f'''{{
  disko.devices.disk.main = {{
    type = "disk";
    device = {json.dumps(device)};
    content = {{
      type = "gpt";
      partitions = {{
        ESP = {{
          size = "1G";
          type = "EF00";
          content = {{
            type = "filesystem";
            format = "vfat";
            mountpoint = "/boot";
            mountOptions = [ "umask=0077" ];
          }};
        }};
        root = {{
          size = "100%";
          content = {{
            type = "filesystem";
            format = "ext4";
            mountpoint = "/";
          }};
        }};
      }};
    }};
  }};
}}
'''


def build_disko_zcfg(device: str) -> str:
    if not isinstance(device, str) or not device.startswith("/dev/"):
        raise ValueError("Disko device must be an absolute /dev path")
    name = device.removeprefix("/dev/")
    if device != f"/dev/{name}" or not _WHOLE_DISK_NAME.fullmatch(name):
        raise ValueError("Disko device must be a supported whole disk")
    return f'''legacy.disko.devices.disk.main = {{
  type = "disk";
  device = {json.dumps(device)};
  content = {{
    type = "gpt";
    partitions = {{
      ESP = {{
        size = "1G";
        type = "EF00";
        content = {{
          type = "filesystem";
          format = "vfat";
          mountpoint = "/boot";
          mountOptions = [ "umask=0077" ];
        }};
      }};
      root = {{
        size = "100%";
        content = {{
          type = "filesystem";
          format = "ext4";
          mountpoint = "/";
        }};
      }};
    }};
  }};
}};
'''


def detect_graphics_devices(sysfs_root: str = "/sys/bus/pci/devices") -> list[dict]:
    """Read display-class PCI devices from sysfs without relying on lspci output."""
    devices = []
    try:
        entries = sorted(os.listdir(sysfs_root))
    except OSError:
        return devices

    for address in entries:
        directory = os.path.join(sysfs_root, address)
        try:
            with open(os.path.join(directory, "class"), encoding="ascii") as file:
                pci_class = int(file.read().strip(), 16)
            if pci_class >> 16 != 0x03:
                continue
            with open(os.path.join(directory, "vendor"), encoding="ascii") as file:
                vendor = int(file.read().strip(), 16)
            with open(os.path.join(directory, "device"), encoding="ascii") as file:
                device = int(file.read().strip(), 16)
        except (OSError, ValueError):
            continue

        boot_vga = False
        try:
            with open(os.path.join(directory, "boot_vga"), encoding="ascii") as file:
                boot_vga = file.read().strip() == "1"
        except OSError:
            pass

        driver_path = os.path.join(directory, "driver")
        driver = os.path.basename(os.path.realpath(driver_path)) if os.path.exists(driver_path) else None
        devices.append(
            {
                "address": address,
                "bootVga": boot_vga,
                "device": device,
                "driver": driver,
                "vendor": vendor,
            }
        )
    return devices


def _xorg_bus_id(address: str) -> str | None:
    match = re.fullmatch(
        r"(?P<domain>[0-9a-fA-F]{4}):(?P<bus>[0-9a-fA-F]{2}):"
        r"(?P<slot>[0-9a-fA-F]{2})\.(?P<function>[0-7])",
        address,
    )
    if not match or match.group("domain") != "0000":
        return None
    return "PCI:{bus}:{slot}:{function}".format(
        bus=int(match.group("bus"), 16),
        slot=int(match.group("slot"), 16),
        function=int(match.group("function"), 16),
    )


def build_graphics_config(devices: list[dict]) -> str:
    vendors = {device["vendor"] for device in devices}
    has_amd = 0x1002 in vendors
    has_intel = 0x8086 in vendors
    has_nvidia = 0x10DE in vendors
    drivers = []
    if has_amd:
        drivers.append("amdgpu")
    if has_intel:
        drivers.append("modesetting")
    if has_nvidia:
        drivers.append("nvidia")

    lines = ["legacy.hardware.graphics.enable = true;"]
    if drivers:
        rendered_drivers = " ".join(json.dumps(driver) for driver in drivers)
        lines.append(f"legacy.services.xserver.videoDrivers = [ {rendered_drivers} ];")
    if has_amd:
        lines.append('legacy.boot.initrd.kernelModules = [ "amdgpu" ];')
    if has_nvidia:
        lines.extend(
            [
                "legacy.hardware.nvidia = {",
                "  modesetting.enable = true;",
                "  nvidiaSettings = true;",
                "  open = false;",
            ]
        )
        nvidia = next((device for device in devices if device["vendor"] == 0x10DE), None)
        primary = next(
            (
                device
                for device in devices
                if device["vendor"] in {0x1002, 0x8086} and device.get("bootVga")
            ),
            None,
        )
        nvidia_bus = _xorg_bus_id(nvidia["address"]) if nvidia else None
        primary_bus = _xorg_bus_id(primary["address"]) if primary else None
        if nvidia_bus and primary_bus:
            lines.extend(
                [
                    "  prime = {",
                    "    offload.enable = true;",
                    "    offload.enableOffloadCmd = true;",
                    f"    nvidiaBusId = {json.dumps(nvidia_bus)};",
                    (
                        f"    intelBusId = {json.dumps(primary_bus)};"
                        if primary["vendor"] == 0x8086
                        else f"    amdgpuBusId = {json.dumps(primary_bus)};"
                    ),
                    "  };",
                ]
            )
        lines.append("};")
    return "\n".join(lines) + "\n"


_LAPTOP_CHASSIS_TYPES = {8, 9, 10, 11, 14, 30, 31, 32}


def is_laptop_environment(sysfs_root: str = "/sys") -> bool:
    chassis_path = os.path.join(sysfs_root, "class", "dmi", "id", "chassis_type")
    try:
        with open(chassis_path, encoding="ascii") as file:
            if int(file.read().strip()) in _LAPTOP_CHASSIS_TYPES:
                return True
    except (OSError, ValueError):
        pass

    power_root = os.path.join(sysfs_root, "class", "power_supply")
    try:
        supplies = os.listdir(power_root)
    except OSError:
        return False
    for supply in supplies:
        try:
            with open(os.path.join(power_root, supply, "type"), encoding="ascii") as file:
                if file.read().strip().casefold() == "battery":
                    return True
        except OSError:
            continue
    return False


def build_kernel_config(laptop: bool) -> str:
    variant = "L-generic" if laptop else "D-generic"
    return f'''{{ inputs, pkgs, ... }}:
{{
  boot.kernelPackages = pkgs.linuxPackagesFor inputs.popcorn.packages.${{pkgs.stdenv.hostPlatform.system}}."{variant}";
}}
'''


def _mount_root_has_mounts() -> bool:
    prefix = f"{MOUNT_ROOT}/"
    try:
        with open("/proc/self/mountinfo", encoding="utf-8") as mountinfo:
            for line in mountinfo:
                fields = line.split()
                if len(fields) < 5:
                    continue
                target = fields[4].replace("\\040", " ").replace("\\011", "\t")
                if target == MOUNT_ROOT or target.startswith(prefix):
                    return True
    except OSError as exc:
        raise RuntimeError("cannot inspect existing mounts under /mnt") from exc
    return False


def _cleanup_mount_root(log_fn=None) -> None:
    if DRY_RUN:
        _run(["sudo", "-n", "umount", "--recursive", MOUNT_ROOT], log_fn)
    elif _mount_root_has_mounts():
        _emit(log_fn, f"unmounting filesystems under {MOUNT_ROOT}")
        _run(["sudo", "-n", "umount", "--recursive", MOUNT_ROOT], log_fn)
    else:
        _emit(log_fn, f"{MOUNT_ROOT} is already unmounted")


def _identify_partitions(partitions: list[dict]) -> tuple[dict | None, dict | None]:
    efi_fstypes = ("vfat", "fat32", "fat16")
    root = next(
        (part for part in partitions if part.get("fs_type", "").lower() not in efi_fstypes),
        None,
    )
    efi = next(
        (part for part in partitions if part.get("fs_type", "").lower() in efi_fstypes),
        None,
    )
    return root, efi


def _mount_manual(partitions: list[dict], log_fn=None) -> None:
    root, efi = _identify_partitions(partitions)
    if not root or not root.get("device"):
        raise RuntimeError("manual mode: no root partition found")

    _emit(log_fn, f"mounting {root['device']} -> {MOUNT_ROOT}")
    _run(["sudo", "-n", "mount", root["device"], MOUNT_ROOT], log_fn)
    if efi and efi.get("device"):
        target = os.path.join(MOUNT_ROOT, "boot")
        _run(["sudo", "-n", "install", "-d", target], log_fn)
        _emit(log_fn, f"mounting {efi['device']} -> {target}")
        _run(["sudo", "-n", "mount", efi["device"], target], log_fn)


def _write_text(path: str, value: str) -> str:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as file:
        file.write(value)
    return path


def _write_json(path: str, value: dict, *, atomic: bool = False) -> str:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if not atomic:
        with open(path, "w", encoding="utf-8") as file:
            json.dump(value, file, indent=2, sort_keys=True)
            file.write("\n")
        return path

    descriptor, temporary = tempfile.mkstemp(prefix=".marker-", dir=os.path.dirname(path))
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as file:
            json.dump(value, file, indent=2, sort_keys=True)
            file.write("\n")
            file.flush()
            os.fsync(file.fileno())
        os.replace(temporary, path)
    except Exception:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise
    return path


def _host_dir(config_dir: str, host_name: str) -> str:
    return os.path.join(config_dir, "hosts", _validate_host_name(host_name))


def _write_host_documents(
    host_dir: str,
    documents: dict[str, str],
    *,
    extra_imports: tuple[str, ...] = (),
) -> str:
    names = sorted((set(documents) - {"host.zcfg"}) | set(extra_imports))
    for name, contents in documents.items():
        if name != "host.zcfg":
            _write_text(os.path.join(host_dir, name), contents)
    host = "".join(f"import ./{name};\n" for name in names)
    return _write_text(os.path.join(host_dir, "host.zcfg"), host)


def _write_plan(config_dir: str, host_name: str, plan: dict) -> str:
    return _write_json(
        os.path.join(_host_dir(config_dir, host_name), "install-plan.json"), plan
    )


def _compile_host(zcfg_path: str, log_fn=None) -> str:
    output = os.path.join(os.path.dirname(zcfg_path), "host.nix")
    _emit(log_fn, f"compiling {zcfg_path} -> {output}")
    _run(["zcfg", "compile", zcfg_path, "-o", output], log_fn)
    if DRY_RUN:
        _write_text(output, "# dry-run zcfg output\n{ ... }: { }\n")
    return output


def _generate_hardware_config(
    config_dir: str,
    host_name: str,
    log_fn=None,
    *,
    include_filesystems: bool = True,
) -> str:
    output = os.path.join(_host_dir(config_dir, host_name), "hardware-configuration.nix")
    _emit(log_fn, f"generating hardware configuration: {output}")
    command = [
        "sudo",
        "-n",
        "nixos-generate-config",
        "--root",
        MOUNT_ROOT,
    ]
    if not include_filesystems:
        command.append("--no-filesystems")
    command.append("--show-hardware-config")
    if DRY_RUN:
        _run(command, log_fn)
        return _write_text(output, "# dry-run hardware config\n{ ... }: { }\n")

    with open(output, "w", encoding="utf-8") as destination:
        subprocess.run(
            command,
            stdout=destination,
            stderr=subprocess.PIPE,
            text=True,
            check=True,
        )
    return output


def _generate_graphics_config(config_dir: str, host_name: str, log_fn=None) -> str:
    output = os.path.join(_host_dir(config_dir, host_name), "graphics.zcfg")
    devices = detect_graphics_devices()
    summary = ", ".join(
        f"{device['address']} vendor=0x{device['vendor']:04x}"
        for device in devices
    ) or "no PCI display devices detected"
    _emit(log_fn, f"generating graphics configuration ({summary}): {output}")
    return _write_text(output, build_graphics_config(devices))


def _generate_kernel_config(config_dir: str, host_name: str, log_fn=None) -> str:
    output = os.path.join(_host_dir(config_dir, host_name), "kernel.nix")
    laptop = is_laptop_environment()
    variant = "L-generic" if laptop else "D-generic"
    _emit(log_fn, f"selecting Popcorn {variant}: {output}")
    return _write_text(output, build_kernel_config(laptop))


def _sha256(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _artifact_metadata(path: str) -> dict:
    return {
        "file": os.path.basename(path),
        "sha256": _sha256(path),
    }


def _validate_config_layout(config_dir: str) -> None:
    root_entries = set(os.listdir(config_dir))
    unexpected = root_entries - _ROOT_ENTRIES
    if unexpected:
        raise RuntimeError(f"unexpected config root entries: {sorted(unexpected)}")
    if "flake.nix" not in root_entries or "hosts" not in root_entries:
        raise RuntimeError("config root must contain flake.nix and hosts")

    for name in root_entries:
        path = os.path.join(config_dir, name)
        if os.path.islink(path):
            raise RuntimeError(f"config layout cannot contain symlinks: {path}")
    hosts_dir = os.path.join(config_dir, "hosts")
    if not os.path.isdir(hosts_dir):
        raise RuntimeError("config hosts entry must be a directory")
    for host_name in os.listdir(hosts_dir):
        _validate_host_name(host_name)
        directory = os.path.join(hosts_dir, host_name)
        if os.path.islink(directory) or not os.path.isdir(directory):
            raise RuntimeError(f"invalid host config entry: {directory}")
        files = set(os.listdir(directory))
        unexpected_files = files - _HOST_FILES
        if unexpected_files:
            raise RuntimeError(
                f"unexpected files for host {host_name}: {sorted(unexpected_files)}"
            )
        for filename in files:
            path = os.path.join(directory, filename)
            if os.path.islink(path) or not os.path.isfile(path):
                raise RuntimeError(f"invalid host config file: {path}")


def _dry_config_root(work_dir: str) -> str:
    return os.path.join(work_dir, "Config", "ZenOS", "Flake")


def _initialize_target_config(work_dir: str, log_fn=None) -> str:
    config_dir = _dry_config_root(work_dir) if DRY_RUN else TARGET_CONFIG_ROOT
    if DRY_RUN:
        os.makedirs(config_dir, exist_ok=False)
    else:
        _run(
            [
                "sudo",
                "-n",
                "install",
                "-d",
                "-m",
                "0755",
                "-o",
                str(os.geteuid()),
                "-g",
                str(os.getegid()),
                config_dir,
            ],
            log_fn,
        )
        if os.listdir(config_dir):
            raise RuntimeError(f"target config root is not empty: {config_dir}")

    os.makedirs(os.path.join(config_dir, "hosts"), exist_ok=True)
    destination = os.path.join(config_dir, "flake.nix")
    if os.path.isfile(ISO_CONFIG_TEMPLATE) and not os.path.islink(ISO_CONFIG_TEMPLATE):
        shutil.copyfile(ISO_CONFIG_TEMPLATE, destination)
    elif DRY_RUN:
        _emit(log_fn, f"[dry-run] mocking template copy from {ISO_CONFIG_TEMPLATE}")
        _write_text(destination, "# dry-run ISO flake template\n{ outputs = _: { }; }\n")
    else:
        raise RuntimeError(f"missing ISO config template: {ISO_CONFIG_TEMPLATE}")
    _emit(log_fn, f"copied ISO flake template to {destination}")
    _validate_config_layout(config_dir)
    return config_dir


def _lock_and_evaluate(config_dir: str, host_name: str, log_fn=None) -> None:
    _validate_config_layout(config_dir)
    _run(["nix", "flake", "lock", "--offline"], log_fn, cwd=config_dir)
    _run(
        [
            "nix",
            "eval",
            "--offline",
            "--no-write-lock-file",
            f"{config_dir}#nixosConfigurations.{host_name}.config.system.build.toplevel",
        ],
        log_fn,
    )


def _nixos_install(config_dir: str, host_name: str, log_fn=None) -> None:
    _emit(log_fn, f"running nixos-install ({host_name})...")
    _run(
        [
            "sudo",
            "-n",
            "nixos-install",
            "--flake",
            f"{config_dir}#{host_name}",
            "--no-root-passwd",
        ],
        log_fn,
    )


def _nixos_rebuild_boot(config_dir: str, host_name: str, log_fn=None) -> None:
    _emit(log_fn, f"building the next boot generation ({host_name})...")
    _run(
        [
            "sudo",
            "-n",
            "nixos-rebuild",
            "boot",
            "--flake",
            f"{config_dir}#{host_name}",
        ],
        log_fn,
    )


def _request_reboot(log_fn=None) -> None:
    _emit(log_fn, "requesting system reboot")
    _run(["sudo", "-n", "systemctl", "reboot"], log_fn)


def _remove_config_tree(path: str, log_fn=None) -> None:
    _run(["sudo", "-n", "rm", "-rf", "--", path], log_fn)
    if DRY_RUN:
        shutil.rmtree(path, ignore_errors=True)


def _restore_oobe_writable(config_dir: str, log_fn=None) -> None:
    owner = f"{os.geteuid()}:{os.getegid()}"
    try:
        _run(
            ["sudo", "-n", "chown", "-R", owner, "--", config_dir],
            log_fn,
        )
        _run(["sudo", "-n", "chmod", "u+rwx", "--", config_dir], log_fn)
    except Exception as exc:
        _emit(log_fn, f"failed to restore writable OOBE config: {exc}")


def _install_local(
    data: dict,
    pages: dict,
    work_dir: str,
    progress_fn,
    log_fn,
    *,
    short: bool,
) -> None:
    mode = "short" if short else "long"
    _emit(log_fn, f"=== {mode} install mode ===")
    progress_fn(0.05)

    disk = pages.get("disks", {})
    if disk.get("mode") not in {"auto", "manual"}:
        raise RuntimeError("disk mode must be auto or manual")

    if short:
        host_name = f"oobe-{_rand_suffix()}"
        payload = {
            "oobe": False,
            "pages": [
                {"id": "computer_name", "hostname": host_name},
                {
                    "id": "desktop",
                    "install_de": True,
                    "desktop_environment": "gnome",
                },
                disk,
            ],
        }
        _emit(log_fn, f"temporary host: {host_name}")
    else:
        host_name = _validate_host_name(pages["computer_name"]["hostname"])
        payload = data
        _emit(log_fn, f"permanent host: {host_name}")

    documents = build_config_documents(payload)
    plan = build_execution_plan(payload)
    disko_text = None
    drives_text = None
    disko_staging_path = None
    if disk["mode"] == "auto":
        device = _selected_auto_disk(disk)
        disko_text = build_disko_config(device)
        drives_text = build_disko_zcfg(device)
        disko_staging_path = _write_text(
            os.path.join(work_dir, "hosts", host_name, "disko.nix"), disko_text
        )

    _cleanup_mount_root(log_fn)
    try:
        if disko_staging_path:
            _emit(log_fn, f"partitioning with Disko: {disko_staging_path}")
            _run(
                ["sudo", "-n", "disko", "--mode", "disko", disko_staging_path],
                log_fn,
            )
        else:
            _mount_manual(disk.get("partitions", []), log_fn)
        progress_fn(0.25)

        config_dir = _initialize_target_config(work_dir, log_fn)
        host_dir = _host_dir(config_dir, host_name)
        graphics_path = _generate_graphics_config(config_dir, host_name, log_fn)
        extra_imports = ["graphics.zcfg"]
        if drives_text is not None:
            _write_text(os.path.join(host_dir, "drives.zcfg"), drives_text)
            extra_imports.append("drives.zcfg")
        zcfg_path = _write_host_documents(
            host_dir,
            documents,
            extra_imports=tuple(extra_imports),
        )
        _compile_host(zcfg_path, log_fn)
        _write_plan(config_dir, host_name, plan)
        hardware_path = _generate_hardware_config(
            config_dir,
            host_name,
            log_fn,
            include_filesystems=disko_text is None,
        )
        # Popcorn is disabled until its binary cache can be consumed reliably.
        # kernel_path = _generate_kernel_config(config_dir, host_name, log_fn)
        with open(zcfg_path, encoding="utf-8") as host_file:
            _print_config(log_fn, zcfg_path, host_file.read())

        if short:
            artifacts = {
                "graphics": _artifact_metadata(graphics_path),
                "hardware": _artifact_metadata(hardware_path),
            }
            if disko_text is not None:
                artifacts["disko"] = _artifact_metadata(
                    os.path.join(host_dir, "drives.zcfg")
                )
            marker = {
                "artifacts": artifacts,
                "status": "pending",
                "temporaryHost": host_name,
                "version": 2,
            }
            _write_json(
                os.path.join(_host_dir(config_dir, host_name), "oobe.json"), marker
            )

        _validate_config_layout(config_dir)
        progress_fn(0.55)
        _lock_and_evaluate(config_dir, host_name, log_fn)
        progress_fn(0.75)
        _nixos_install(config_dir, host_name, log_fn)
        progress_fn(1.0)
        _emit(log_fn, f"{mode} install done")
    finally:
        _cleanup_mount_root(log_fn)


def _run_short(pages: dict, work_dir: str, progress_fn, log_fn) -> None:
    data = {"oobe": False, "pages": list(pages.values())}
    _install_local(data, pages, work_dir, progress_fn, log_fn, short=True)


def _run_long(
    data: dict, pages: dict, work_dir: str, progress_fn, log_fn
) -> None:
    _install_local(data, pages, work_dir, progress_fn, log_fn, short=False)


def _read_current_host() -> str:
    try:
        with open("/etc/hostname", encoding="utf-8") as file:
            return file.read().strip()
    except FileNotFoundError as exc:
        raise RuntimeError("cannot identify the current temporary host") from exc


def _find_pending_oobe(config_dir: str, current_host: str) -> tuple[str, dict]:
    pending: list[tuple[str, dict]] = []
    hosts_dir = os.path.join(config_dir, "hosts")
    for host_name in os.listdir(hosts_dir):
        marker_path = os.path.join(hosts_dir, host_name, "oobe.json")
        if not os.path.isfile(marker_path) or os.path.islink(marker_path):
            continue
        try:
            with open(marker_path, encoding="utf-8") as file:
                marker = json.load(file)
        except (OSError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"invalid OOBE marker: {marker_path}") from exc
        if marker.get("status") == "pending":
            pending.append((host_name, marker))

    if len(pending) != 1:
        raise RuntimeError(f"expected exactly one pending OOBE marker, found {len(pending)}")
    temporary_host, marker = pending[0]
    if marker.get("version") != 2 or marker.get("temporaryHost") != temporary_host:
        raise RuntimeError("pending OOBE marker does not match its temporary host")
    if current_host != temporary_host:
        raise RuntimeError(
            f"pending OOBE host {temporary_host!r} is not current host {current_host!r}"
        )
    artifacts = marker.get("artifacts")
    if not isinstance(artifacts, dict) or set(artifacts) not in (
        {"graphics", "hardware"},
        {"disko", "graphics", "hardware"},
    ):
        raise RuntimeError("pending OOBE marker has invalid artifact metadata")
    expected_files = {
        "disko": "drives.zcfg",
        "graphics": "graphics.zcfg",
        "hardware": "hardware-configuration.nix",
    }
    for name, metadata in artifacts.items():
        if (
            not isinstance(metadata, dict)
            or metadata.get("file") != expected_files[name]
            or not _SHA256.fullmatch(metadata.get("sha256", ""))
        ):
            raise RuntimeError(f"pending OOBE marker has invalid {name} metadata")
    return temporary_host, marker


def _run_oobe(
    data: dict, pages: dict, work_dir: str, progress_fn, log_fn
) -> None:
    _emit(log_fn, "=== OOBE finalization mode ===")
    progress_fn(0.05)
    config_dir = _dry_config_root(work_dir) if DRY_RUN else OOBE_CONFIG_ROOT
    if not os.path.isdir(config_dir):
        raise RuntimeError(f"no existing NixOS config at {config_dir}")
    _validate_config_layout(config_dir)

    temporary_host, marker = _find_pending_oobe(config_dir, _read_current_host())
    final_host = _validate_host_name(pages["computer_name"]["hostname"])
    if final_host == temporary_host:
        raise RuntimeError("final host name must differ from the temporary OOBE host")

    hosts_dir = os.path.join(config_dir, "hosts")
    temporary_dir = _host_dir(config_dir, temporary_host)
    final_dir = _host_dir(config_dir, final_host)
    if os.path.exists(final_dir):
        raise RuntimeError(f"final host already exists: {final_host}")

    source_artifacts = {}
    for name, metadata in marker["artifacts"].items():
        source = os.path.join(temporary_dir, metadata["file"])
        if _sha256(source) != metadata["sha256"]:
            raise RuntimeError(f"temporary {name} configuration checksum mismatch")
        source_artifacts[name] = source

    documents = build_config_documents(data)
    stage_dir = tempfile.mkdtemp(prefix=f".{final_host}.staging-", dir=hosts_dir)
    published = False
    completed = False
    try:
        for name, source in source_artifacts.items():
            metadata = marker["artifacts"][name]
            staged = os.path.join(stage_dir, metadata["file"])
            shutil.copyfile(source, staged)
            if _sha256(staged) != metadata["sha256"]:
                raise RuntimeError(f"copied {name} configuration checksum mismatch")

        imported_artifacts = tuple(
            metadata["file"]
            for metadata in marker["artifacts"].values()
            if metadata["file"].endswith(".zcfg")
        )
        zcfg_path = _write_host_documents(
            stage_dir,
            documents,
            extra_imports=imported_artifacts,
        )
        final_plan = build_execution_plan(data)
        with open(os.path.join(temporary_dir, "install-plan.json"), encoding="utf-8") as file:
            initial_plan = json.load(file)
        final_plan["disk"] = initial_plan.get("disk", final_plan["disk"])
        _write_json(os.path.join(stage_dir, "install-plan.json"), final_plan)
        _compile_host(zcfg_path, log_fn)
        with open(zcfg_path, encoding="utf-8") as host_file:
            _print_config(log_fn, zcfg_path, host_file.read())
        os.replace(stage_dir, final_dir)
        published = True
        _validate_config_layout(config_dir)
        progress_fn(0.45)

        _lock_and_evaluate(config_dir, final_host, log_fn)
        _nixos_rebuild_boot(config_dir, final_host, log_fn)
        progress_fn(0.85)

        completion = {
            "artifacts": marker["artifacts"],
            "completedAt": datetime.now(timezone.utc).isoformat(),
            "host": final_host,
            "sourceHost": temporary_host,
            "status": "complete",
            "version": 2,
        }
        _write_json(
            os.path.join(final_dir, "oobe-complete.json"), completion, atomic=True
        )
        _validate_config_layout(config_dir)
        _run(
            ["sudo", "-n", "chown", "-R", "root:root", "--", config_dir],
            log_fn,
        )
        _remove_config_tree(temporary_dir, log_fn)
        completed = True
        progress_fn(1.0)
        _emit(log_fn, f"OOBE finalized host {final_host}")
    except Exception:
        if published and not completed:
            _restore_oobe_writable(config_dir, log_fn)
            _remove_config_tree(final_dir, log_fn)
        raise
    finally:
        if os.path.isdir(stage_dir):
            shutil.rmtree(stage_dir, ignore_errors=True)

def _run_online(pages: dict, work_dir: str, progress_fn, log_fn) -> None:
    """Retain online manual installs without weakening local Disko safeguards."""
    _emit(log_fn, "=== online config mode ===")
    online = pages["online"]
    config_dir = os.path.join(work_dir, "online-config")
    _run(["git", "clone", "--depth=1", online["flake"], config_dir], log_fn)
    if DRY_RUN:
        host_dir = os.path.join(config_dir, "hosts", online["host"])
        os.makedirs(host_dir, exist_ok=True)
        _write_text(os.path.join(host_dir, "host.zcfg"), "# dry-run online host\n")

    host_path = os.path.join(config_dir, "hosts", online["host"], "host.zcfg")
    if not os.path.isfile(host_path):
        raise RuntimeError(f"hosts/{online['host']}/host.zcfg not found in cloned repo")
    with open(host_path, encoding="utf-8") as file:
        config = strip_disko_config(file.read())
    disk = pages.get("disks", {})
    if disk.get("mode") == "auto":
        raise RuntimeError("online auto-partitioning is not supported")
    _write_text(host_path, format_nix(config))
    _compile_host(host_path, log_fn)

    _cleanup_mount_root(log_fn)
    try:
        _mount_manual(disk.get("partitions", []), log_fn)
        _generate_hardware_config(config_dir, online["host"], log_fn)
        _generate_graphics_config(config_dir, online["host"], log_fn)
        # _generate_kernel_config(config_dir, online["host"], log_fn)
        _nixos_install(config_dir, online["host"], log_fn)
        progress_fn(1.0)
    finally:
        _cleanup_mount_root(log_fn)


def run_installer(
    install_state, progress_fn=None, log_fn=None, done_fn=None
) -> threading.Thread:
    """Run the selected installer flow in a daemon worker thread."""
    if DRY_RUN:
        _emit(log_fn, "*** DRY RUN MODE -- no disk or system operations will run ***")

    def _thread() -> None:
        data = install_state.to_dict()
        pages = {page["id"]: page for page in data.get("pages", [])}
        is_oobe = data.get("oobe", False)
        is_online = "online" in pages and pages["online"].get("method") == "online"
        has_full = "computer_name" in pages
        update_progress = progress_fn or (lambda _value: None)
        work_dir = tempfile.mkdtemp(prefix="zenos-run-")
        try:
            if is_online:
                _run_online(pages, work_dir, update_progress, log_fn)
            elif is_oobe:
                _run_oobe(data, pages, work_dir, update_progress, log_fn)
            elif has_full:
                _run_long(data, pages, work_dir, update_progress, log_fn)
            else:
                _run_short(pages, work_dir, update_progress, log_fn)
            if done_fn:
                done_fn(True, None)
        except Exception as exc:
            _emit(log_fn, f"[fatal] {exc}")
            if done_fn:
                done_fn(False, str(exc))
        finally:
            shutil.rmtree(work_dir, ignore_errors=True)

    thread = threading.Thread(target=_thread, daemon=True, name="zenos-installer")
    thread.start()
    return thread
