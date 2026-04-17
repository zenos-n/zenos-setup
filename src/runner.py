"""
runner.py — zenos-setup installer backend

Translates an InstallState into real disk ops + nixos-install/rebuild calls.
Called from views/progress/logic.py in a background thread.

Modes (detected from InstallState):
  short   — oobe=false, no computer_name page
              -> oobe-XXXXXX host, minimal config, base OS install, reboots into OOBE
  long    — oobe=false, has computer_name page
              -> full config, permanent install
  oobe    — oobe=true
              -> same config as long but nixos-rebuild switch on the running system
  online  — has "online" page
              -> clone user flake, patch disk section, nixos-install
"""

# ------------------------------------------------------------------ dry run
# set to True to simulate the full install flow without touching disks or
# running any real nix commands. all subprocess calls are replaced with
# logged no-ops. safe to run on any machine for testing.
DRY_RUN = True
# ------------------------------------------------------------------

import os
import random
import shutil
import string
import subprocess
import tempfile
import threading
from datetime import datetime

from .builder import (
    BEHAVIORS,
    apply_behavior,
    format_nix,
    process_installer_payload,
    strip_disko_config,
)

# --- constants ---

ZENOS_CONFIG_REMOTE = "https://github.com/zenos-n/zenos-config"
# ISO bundles zenos-config here (read-only nix store path, so we copy it out)
ISO_CONFIG_PATH = "/iso-config"
MOUNT_ROOT = "/mnt"


# --- helpers ---

def _rand_suffix(n: int = 6) -> str:
    return "".join(random.choices(string.ascii_lowercase + string.digits, k=n))


def _emit(fn, msg: str):
    if fn:
        fn(str(msg))


def _run(cmd: list, log_fn=None, **popen_kwargs):
    """
    Run a subprocess, streaming stdout+stderr to log_fn line by line.
    In DRY_RUN mode, just logs the command instead of running it.
    """
    if DRY_RUN:
        _emit(log_fn, f"[dry-run] would run: {' '.join(str(c) for c in cmd)}")
        return

    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        **popen_kwargs,
    )
    for line in proc.stdout:
        _emit(log_fn, line.rstrip())
    proc.wait()
    if proc.returncode != 0:
        raise subprocess.CalledProcessError(proc.returncode, cmd)


def _print_config(log_fn, path: str, config_str: str):
    """Always prints the generated config to the log console."""
    _emit(log_fn, f"\n--- generated config: {path} ---\n{config_str}\n---\n")


# --- config source ---

def _get_config_src(work_dir: str, log_fn=None) -> str:
    """
    Returns a path to a writable copy of zenos-config.
    Prefers the ISO-bundled copy (/iso-config), falls back to cloning GitHub.
    In DRY_RUN mode, creates an empty skeleton so path ops don't crash.
    """
    dest = os.path.join(work_dir, "zenos-config")

    if DRY_RUN:
        _emit(log_fn, f"[dry-run] skipping config clone/copy, creating skeleton at {dest}")
        os.makedirs(os.path.join(dest, "hosts"), exist_ok=True)
        with open(os.path.join(dest, "flake.nix"), "w") as f:
            f.write("# dry-run stub\n{ outputs = _: {}; }\n")
        return dest

    if os.path.isdir(ISO_CONFIG_PATH):
        _emit(log_fn, f"copying bundled config from {ISO_CONFIG_PATH}")
        shutil.copytree(ISO_CONFIG_PATH, dest, symlinks=True)
        # drop .git so nixos-install doesn't complain about a dirty tree
        git_dir = os.path.join(dest, ".git")
        if os.path.isdir(git_dir):
            shutil.rmtree(git_dir)
    else:
        _emit(log_fn, f"cloning {ZENOS_CONFIG_REMOTE}...")
        _run(["git", "clone", "--depth=1", ZENOS_CONFIG_REMOTE, dest], log_fn)

    return dest


# --- disk ops ---

def _identify_partitions(partitions: list) -> tuple:
    efi_fstypes = ("vfat", "fat32", "fat16")
    root_p = next((p for p in partitions if p["fs_type"].lower() not in efi_fstypes), None)
    efi_p  = next((p for p in partitions if p["fs_type"].lower() in efi_fstypes), None)
    return root_p, efi_p


def _mount_manual(partitions: list, log_fn=None):
    """Mount user-selected partitions to /mnt before nixos-install."""
    root_p, efi_p = _identify_partitions(partitions)

    if not root_p:
        raise RuntimeError("manual mode: no root partition (non-vfat) found in partition list")

    if DRY_RUN:
        _emit(log_fn, f"[dry-run] would mount {root_p['device']} -> {MOUNT_ROOT}")
        if efi_p:
            _emit(log_fn, f"[dry-run] would mount {efi_p['device']} -> {MOUNT_ROOT}/boot/efi")
        return

    _emit(log_fn, f"mounting {root_p['device']} -> {MOUNT_ROOT}")
    subprocess.run(["mount", root_p["device"], MOUNT_ROOT], check=True)

    if efi_p:
        efi_target = os.path.join(MOUNT_ROOT, "boot", "efi")
        os.makedirs(efi_target, exist_ok=True)
        _emit(log_fn, f"mounting {efi_p['device']} -> {efi_target}")
        subprocess.run(["mount", efi_p["device"], efi_target], check=True)


# --- host config writer ---

def _write_host(config_dir: str, host_name: str, config_str: str) -> str:
    """Creates hosts/<host>/host.zcfg and returns its path."""
    host_dir = os.path.join(config_dir, "hosts", host_name)
    os.makedirs(host_dir, exist_ok=True)
    path = os.path.join(host_dir, "host.zcfg")
    with open(path, "w") as f:
        f.write(config_str)
    return path


# --- nixos operations ---

def _nixos_install(config_dir: str, host_name: str, use_disko: bool = False, log_fn=None):
    flake_ref = f"{config_dir}#{host_name}"

    if use_disko:
        _emit(log_fn, "partitioning and formatting with disko...")
        _run(
            [
                "nix", "run", "github:nix-community/disko/latest", "--",
                "--mode", "disko",
                "--flake", flake_ref,
            ],
            log_fn,
        )

    _emit(log_fn, f"running nixos-install ({host_name})...")
    _run(["nixos-install", "--flake", flake_ref, "--no-root-passwd"], log_fn)


def _nixos_rebuild(config_dir: str, host_name: str, log_fn=None):
    flake_ref = f"{config_dir}#{host_name}"
    _emit(log_fn, f"running nixos-rebuild switch ({host_name})...")
    _run(["nixos-rebuild", "switch", "--flake", flake_ref], log_fn)


# --- mode implementations ---

def _run_short(pages: dict, work_dir: str, progress_fn, log_fn):
    """
    Short install -- oobe=false, no computer_name page.
    Minimal config, temporary oobe-XXXXXX host.
    After reboot the user goes through OOBE to complete setup.
    """
    _emit(log_fn, "=== short install mode ===")
    progress_fn(0.05)

    config_dir = _get_config_src(work_dir, log_fn)
    host_name  = f"oobe-{_rand_suffix()}"
    _emit(log_fn, f"temporary host: {host_name}")
    progress_fn(0.15)

    cfg = apply_behavior("", "base")
    cfg = apply_behavior(cfg, "network", hostname=host_name)
    cfg = apply_behavior(cfg, "oobe_trigger")

    disk      = pages.get("disks", {})
    use_disko = disk.get("mode") == "auto"
    if use_disko:
        cfg = apply_behavior(cfg, "disko_auto", device=f'/dev/{disk["disks"][0]}')

    header = (
        f"# zenos-installer: short install\n"
        f"# generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n"
        f"# temporary host -- OOBE will apply the final configuration\n\n"
    )
    config_str = header + format_nix(cfg)
    zcfg_path  = _write_host(config_dir, host_name, config_str)
    _print_config(log_fn, zcfg_path, config_str)
    progress_fn(0.25)

    if not use_disko:
        _mount_manual(disk.get("partitions", []), log_fn)
    progress_fn(0.35)

    _nixos_install(config_dir, host_name, use_disko=use_disko, log_fn=log_fn)
    progress_fn(1.0)
    _emit(log_fn, "short install done -- reboot to start OOBE")


def _run_long(data: dict, pages: dict, work_dir: str, progress_fn, log_fn):
    """
    Long install -- oobe=false, has computer_name page.
    Full config (user, desktop, theme, apps), permanent install.
    """
    _emit(log_fn, "=== long install mode ===")
    progress_fn(0.05)

    config_dir = _get_config_src(work_dir, log_fn)
    host_name  = pages["computer_name"]["hostname"]
    _emit(log_fn, f"building config for host: {host_name}")
    progress_fn(0.15)

    config_str = process_installer_payload(data)
    zcfg_path  = _write_host(config_dir, host_name, config_str)
    _print_config(log_fn, zcfg_path, config_str)
    progress_fn(0.25)

    disk      = pages.get("disks", {})
    use_disko = disk.get("mode") == "auto"
    if not use_disko:
        _mount_manual(disk.get("partitions", []), log_fn)
    progress_fn(0.35)

    _nixos_install(config_dir, host_name, use_disko=use_disko, log_fn=log_fn)
    progress_fn(1.0)
    _emit(log_fn, "long install done")


def _run_oobe(data: dict, pages: dict, work_dir: str, progress_fn, log_fn):
    """
    OOBE mode -- oobe=true, running on the installed system.
    Builds full config, applies with nixos-rebuild switch.
    """
    _emit(log_fn, "=== oobe (rebuild) mode ===")
    progress_fn(0.05)

    config_dir = None
    for candidate in ("/etc/zenos", "/etc/nixos"):
        if os.path.isdir(candidate):
            config_dir = candidate
            break

    if not config_dir:
        if DRY_RUN:
            config_dir = work_dir
            _emit(log_fn, f"[dry-run] no /etc/zenos found, using {work_dir}")
        else:
            raise RuntimeError("no existing NixOS config at /etc/zenos or /etc/nixos")

    try:
        with open("/etc/hostname") as f:
            current_host = f.read().strip()
    except FileNotFoundError:
        current_host = "zenos"

    host_name = pages.get("computer_name", {}).get("hostname", current_host)
    _emit(log_fn, f"rebuilding host: {host_name}")
    progress_fn(0.20)

    config_str = process_installer_payload(data)
    zcfg_path  = _write_host(config_dir, host_name, config_str)
    _print_config(log_fn, zcfg_path, config_str)
    progress_fn(0.40)

    _nixos_rebuild(config_dir, host_name, log_fn=log_fn)
    progress_fn(1.0)
    _emit(log_fn, "oobe rebuild done")


def _run_online(pages: dict, work_dir: str, progress_fn, log_fn):
    """
    Online config mode -- clones user flake, patches disk section, nixos-install.
    """
    _emit(log_fn, "=== online config mode ===")
    o          = pages["online"]
    flake_url  = o["flake"]
    host_name  = o["host"]

    progress_fn(0.05)
    config_dir = os.path.join(work_dir, "online-config")
    _emit(log_fn, f"cloning {flake_url}...")
    _run(["git", "clone", "--depth=1", flake_url, config_dir], log_fn)

    if DRY_RUN:
        stub_path = os.path.join(config_dir, "hosts", host_name)
        os.makedirs(stub_path, exist_ok=True)
        with open(os.path.join(stub_path, "host.zcfg"), "w") as f:
            f.write(f"# dry-run stub for {host_name}\ndesktops.gnome.enable = true;\n")

    progress_fn(0.20)

    host_cfg_path = os.path.join(config_dir, "hosts", host_name, "host.zcfg")
    if not os.path.exists(host_cfg_path):
        raise RuntimeError(f"hosts/{host_name}/host.zcfg not found in cloned repo")

    with open(host_cfg_path) as f:
        cfg = f.read()

    _emit(log_fn, "stripping existing disk config and injecting new one...")
    cfg = strip_disko_config(cfg)

    disk      = pages.get("disks", {})
    use_disko = disk.get("mode") == "auto"
    if use_disko:
        cfg = apply_behavior(cfg, "disko_auto", device=f'/dev/{disk["disks"][0]}')

    header = (
        f"# patched by zenos-installer (online config mode)\n"
        f"# source: {flake_url}\n"
        f"# date: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n\n"
    )
    patched = header + format_nix(cfg)
    with open(host_cfg_path, "w") as f:
        f.write(patched)
    _print_config(log_fn, host_cfg_path, patched)
    progress_fn(0.30)

    if not use_disko:
        _mount_manual(disk.get("partitions", []), log_fn)
    progress_fn(0.35)

    _nixos_install(config_dir, host_name, use_disko=use_disko, log_fn=log_fn)
    progress_fn(1.0)
    _emit(log_fn, "online config install done")


# --- public entry point ---

def run_installer(install_state, progress_fn=None, log_fn=None, done_fn=None) -> threading.Thread:
    """
    Kick off the installer in a daemon thread.

    Args:
        install_state -- InstallState from state.py
        progress_fn   -- callable(float 0.0-1.0)  called from worker thread;
                         wrap in GLib.idle_add when touching GTK widgets
        log_fn        -- callable(str)  same threading caveat
        done_fn       -- callable(success: bool, error: str | None)

    Returns the Thread (joinable if needed).
    """
    if DRY_RUN and log_fn:
        log_fn("*** DRY RUN MODE -- no disk or nix operations will run ***")

    def _thread():
        data  = install_state.to_dict()
        pages = {p["id"]: p for p in data.get("pages", [])}

        is_oobe   = data.get("oobe", False)
        is_online = "online" in pages and pages["online"].get("method") == "online"
        has_full  = "computer_name" in pages  # distinguishes short from long

        _pfn     = progress_fn or (lambda _: None)
        work_dir = tempfile.mkdtemp(prefix="zenos-run-")
        try:
            if is_online:
                _run_online(pages, work_dir, _pfn, log_fn)
            elif is_oobe:
                _run_oobe(data, pages, work_dir, _pfn, log_fn)
            elif has_full:
                _run_long(data, pages, work_dir, _pfn, log_fn)
            else:
                _run_short(pages, work_dir, _pfn, log_fn)

            if done_fn:
                done_fn(True, None)
        except Exception as exc:
            _emit(log_fn, f"[fatal] {exc}")
            if done_fn:
                done_fn(False, str(exc))
        finally:
            shutil.rmtree(work_dir, ignore_errors=True)

    t = threading.Thread(target=_thread, daemon=True, name="zenos-installer")
    t.start()
    return t
