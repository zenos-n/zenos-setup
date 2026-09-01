import os
from pathlib import Path
import subprocess
from zoneinfo import ZoneInfo


TIMEZONE_READY_MARKER = "zenos-oobe-timezone-ready"


def apply_runtime_timezone(timezone_name, *, run=subprocess.run, environ=None):
    ZoneInfo(timezone_name)
    result = run(
        ["sudo", "-n", "timedatectl", "set-timezone", timezone_name],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        zoneinfo = f"/etc/zoneinfo/{timezone_name}"
        fallback = run(
            ["sudo", "-n", "ln", "-sfn", zoneinfo, "/etc/localtime"],
            check=False,
            capture_output=True,
            text=True,
        )
        if fallback.returncode != 0:
            detail = (fallback.stderr or result.stderr or "unknown error").strip()
            raise RuntimeError(f"could not update /etc/localtime: {detail}")

    environment = os.environ if environ is None else environ
    if environment.get("ZENOS_OOBE") != "1":
        return None
    runtime_dir = environment.get("XDG_RUNTIME_DIR")
    if not runtime_dir:
        raise RuntimeError("XDG_RUNTIME_DIR is unavailable in OOBE")
    marker = Path(runtime_dir) / TIMEZONE_READY_MARKER
    marker.touch(mode=0o600, exist_ok=True)
    return marker
