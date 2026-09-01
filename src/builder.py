"""Build deterministic ZenOS configuration and installer execution plans."""

from __future__ import annotations

from dataclasses import dataclass
import json
import re
import subprocess
from typing import Any, Callable


IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_'-]*$")


@dataclass(frozen=True)
class PkgsRef:
    path: tuple[str, ...]

    def __post_init__(self):
        if not self.path or not all(IDENTIFIER.fullmatch(part) for part in self.path):
            raise ValueError(f"invalid package reference: {'.'.join(self.path)}")


DESKTOP_OPTIONS = {
    "gnome": ("desktops", "gnome", "enable"),
    "kde": ("desktops", "plasma", "enable"),
    "xfce": ("desktops", "xfce", "enable"),
    "cinnamon": ("desktops", "cinnamon", "enable"),
    "budgie": ("desktops", "budgie", "enable"),
    "mate": ("desktops", "mate", "enable"),
}

UNAVAILABLE_PACKAGES = {"flatseal", "helium-browser", "ventoy", "zen-browser"}

CORE_EXCLUDE_OPTIONS = {
    "gnome": ("legacy", "environment", "gnome", "excludePackages"),
    "kde": ("legacy", "environment", "plasma6", "excludePackages"),
    "xfce": ("legacy", "environment", "xfce", "excludePackages"),
    "cinnamon": ("legacy", "environment", "cinnamon", "excludePackages"),
    "budgie": ("legacy", "environment", "budgie", "excludePackages"),
    "mate": ("legacy", "environment", "mate", "excludePackages"),
}

CORE_PACKAGE_PATHS = {
    "baobab": ("legacy", "baobab"),
    "decibels": ("legacy", "decibels"),
    "epiphany": ("legacy", "epiphany"),
    "gnome-text-editor": ("legacy", "gnome-text-editor"),
    "gnome-calculator": ("legacy", "gnome-calculator"),
    "gnome-calendar": ("legacy", "gnome-calendar"),
    "gnome-characters": ("legacy", "gnome-characters"),
    "gnome-clocks": ("legacy", "gnome-clocks"),
    "nautilus": ("catalog", "nautilus"),
    "gnome-console": ("catalog", "gnome-console"),
    "gnome-contacts": ("legacy", "gnome-contacts"),
    "gnome-font-viewer": ("legacy", "gnome-font-viewer"),
    "gnome-logs": ("legacy", "gnome-logs"),
    "gnome-maps": ("legacy", "gnome-maps"),
    "gnome-music": ("legacy", "gnome-music"),
    "gnome-system-monitor": ("catalog", "gnome-system-monitor"),
    "gnome-tecla": ("legacy", "gnome-tecla"),
    "gnome-weather": ("legacy", "gnome-weather"),
    "loupe": ("legacy", "loupe"),
    "papers": ("legacy", "papers"),
    "gnome-connections": ("legacy", "gnome-connections"),
    "showtime": ("legacy", "showtime"),
    "simple-scan": ("legacy", "simple-scan"),
    "snapshot": ("legacy", "snapshot"),
    "yelp": ("legacy", "yelp"),
    "gnome-disk-utility": ("legacy", "gnome-disk-utility"),
    "seahorse": ("legacy", "seahorse"),
    "sushi": ("legacy", "sushi"),
    "gnome-extensions-app": ("legacy", "gnome-extension-manager"),
    "gnome-tweaks": ("legacy", "gnome-tweaks"),
    "dolphin": ("legacy", "kdePackages", "dolphin"),
    "konsole": ("legacy", "kdePackages", "konsole"),
    "kate": ("legacy", "kdePackages", "kate"),
    "spectacle": ("legacy", "kdePackages", "spectacle"),
    "okular": ("legacy", "kdePackages", "okular"),
    "thunar": ("legacy", "xfce", "thunar"),
    "xfce4-terminal": ("legacy", "xfce", "xfce4-terminal"),
    "mousepad": ("legacy", "xfce", "mousepad"),
    "xfce4-taskmanager": ("legacy", "xfce", "xfce4-taskmanager"),
    "nemo": ("legacy", "nemo"),
    "gnome-terminal": ("legacy", "gnome-terminal"),
    "xreader": ("legacy", "xreader"),
    "pix": ("legacy", "pix"),
    "mate-system-monitor": ("legacy", "mate", "mate-system-monitor"),
    "atril": ("legacy", "mate", "atril"),
    "caja": ("legacy", "mate", "caja"),
    "mate-terminal": ("legacy", "mate", "mate-terminal"),
    "pluma": ("legacy", "mate", "pluma"),
}


def _pages(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        page["id"]: page
        for page in payload.get("pages", [])
        if isinstance(page, dict) and isinstance(page.get("id"), str)
    }


def _set_path(tree: dict[str, Any], path: tuple[str, ...], value: Any) -> None:
    if not path:
        raise ValueError("configuration path cannot be empty")
    current = tree
    for segment in path[:-1]:
        _validate_identifier(segment, "configuration key")
        existing = current.setdefault(segment, {})
        if not isinstance(existing, dict):
            raise ValueError(f"configuration path conflicts at {segment}")
        current = existing
    leaf = path[-1]
    _validate_identifier(leaf, "configuration key")
    if leaf in current:
        raise ValueError(f"configuration path assigned twice: {'.'.join(path)}")
    current[leaf] = value


def _validate_identifier(value: str, label: str) -> None:
    if not IDENTIFIER.fullmatch(value):
        raise ValueError(f"invalid {label}: {value!r}")


def hash_password(
    password: str,
    run: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> str:
    if not password:
        raise ValueError("password cannot be empty")
    result = run(
        ["openssl", "passwd", "-6", "-stdin"],
        input=password,
        text=True,
        capture_output=True,
        check=True,
    )
    hashed = result.stdout.strip()
    if not hashed.startswith("$6$"):
        raise ValueError("password hashing returned an unsupported format")
    return hashed


def build_config_tree(
    payload: dict[str, Any],
    *,
    password_hash: str | None = None,
) -> dict[str, Any]:
    pages = _pages(payload)
    tree: dict[str, Any] = {}

    _set_path(tree, ("system", "branding", "distroName"), "ZenOS")
    _set_path(tree, ("system", "branding", "distroId"), "zenos")
    _set_path(tree, ("system", "release", "stateVersion"), "26.05")
    _set_path(tree, ("system", "network", "networkManager"), True)

    language = pages.get("language", {})
    _set_path(tree, ("system", "localization", "locale"), language.get("locale") or "en_US.UTF-8")

    timezone = pages.get("timezone", {}).get("timezone", {})
    region = timezone.get("region") or "Europe"
    zone = timezone.get("zone") or "London"
    _set_path(tree, ("system", "localization", "timeZone"), f"{region}/{zone}")

    keyboards = pages.get("keyboard", {}).get("keyboard", [])
    if keyboards:
        layouts = [item.get("layout", "us") for item in keyboards]
        variants = [item.get("variant", "") for item in keyboards]
        model = keyboards[0].get("model") or "pc105"
        _set_path(tree, ("system", "keyboard", "layout"), ",".join(layouts))
        _set_path(tree, ("system", "keyboard", "variant"), ",".join(variants))
        _set_path(tree, ("system", "keyboard", "model"), model)

    host_name = pages.get("computer_name", {}).get("hostname")
    if host_name:
        _validate_identifier(host_name, "hostname")
        _set_path(tree, ("system", "network", "hostName"), host_name)

    user = pages.get("user")
    if user:
        username = user.get("username", "")
        _validate_identifier(username, "username")
        hashed = password_hash or hash_password(user.get("password", ""))
        if not hashed.startswith("$"):
            raise ValueError("password_hash must be a modular crypt hash")
        base = ("legacy", "users", "users", username)
        _set_path(tree, (*base, "isNormalUser"), True)
        _set_path(tree, (*base, "description"), user.get("fullname") or username)
        _set_path(tree, (*base, "initialHashedPassword"), hashed)
        _set_path(tree, (*base, "extraGroups"), ["networkmanager", "video", "wheel"])

    desktop = pages.get("desktop", {})
    if desktop.get("install_de"):
        selected = desktop.get("desktop_environment", "")
        option = DESKTOP_OPTIONS.get(selected)
        if option is None:
            raise ValueError(f"unsupported desktop environment: {selected!r}")
        _set_path(tree, option, True)
        if selected == "gnome":
            gnome_options = desktop.get("gnome_options", {})
            _set_path(tree, ("gnomeProfile", "enable"), True)
            _set_path(
                tree,
                ("gnomeProfile", "enableBranding"),
                gnome_options.get("theme", True),
            )
            _set_path(
                tree,
                ("gnomeProfile", "enableExtensions"),
                gnome_options.get("extensions", True),
            )
            extension_ids = gnome_options.get("extension_ids")
            if extension_ids is not None:
                if not isinstance(extension_ids, list) or not all(
                    isinstance(extension_id, str) and IDENTIFIER.fullmatch(extension_id)
                    for extension_id in extension_ids
                ):
                    raise ValueError("GNOME extension ids must be valid identifiers")
                _set_path(
                    tree,
                    ("gnomeProfile", "extensionIds"),
                    sorted(set(extension_ids)),
                )
            shortcuts = pages.get("shortcuts", {})
            directions = shortcuts.get("directions", "vim")
            actions = shortcuts.get("actions", "zenos")
            if directions not in {"standard", "vim"}:
                raise ValueError(f"unsupported shortcut direction mode: {directions!r}")
            if actions not in {"traditional", "zenos"}:
                raise ValueError(f"unsupported shortcut action mode: {actions!r}")
            _set_path(tree, ("gnomeProfile", "directionKeys"), directions)
            _set_path(tree, ("gnomeProfile", "actionKeys"), actions)

    packages = []
    core_exclusions = []
    firefox_enabled = False
    for app in pages.get("software", {}).get("apps", []):
        if app.get("includedByDesktop"):
            if not app.get("enabled"):
                app_id = app.get("app", "")
                package_path = CORE_PACKAGE_PATHS.get(app_id)
                if package_path is None:
                    raise ValueError(f"unknown desktop core application: {app_id!r}")
                core_exclusions.append(PkgsRef(package_path))
            continue
        if not app.get("enabled"):
            continue
        app_id = app.get("app", "")
        _validate_identifier(app_id, "application id")
        if app_id in UNAVAILABLE_PACKAGES:
            raise ValueError(f"application is unavailable in the current ZenPkgs registry: {app_id}")
        firefox_enabled = firefox_enabled or app_id == "firefox"
        packages.append(PkgsRef(("catalog", app_id)))
    if firefox_enabled:
        _set_path(tree, ("legacy", "programs", "firefox", "enable"), True)
    if core_exclusions:
        selected = pages.get("desktop", {}).get("desktop_environment", "")
        option = CORE_EXCLUDE_OPTIONS.get(selected)
        if option is None:
            raise ValueError(f"desktop core exclusions are unsupported for: {selected!r}")
        _set_path(
            tree,
            option,
            sorted(set(core_exclusions), key=lambda item: item.path),
        )
    if packages:
        unique_packages = sorted(set(packages), key=lambda item: item.path)
        _set_path(tree, ("system", "software", "packages"), unique_packages)

    return tree


def build_execution_plan(payload: dict[str, Any]) -> dict[str, Any]:
    pages = _pages(payload)
    disk = pages.get("disks", {})
    online = pages.get("online", {})
    return {
        "version": 1,
        "mode": "oobe" if payload.get("oobe") else "installer",
        "networkStatus": pages.get("network", {}).get("network_status", "unknown"),
        "disk": {
            "mode": disk.get("mode"),
            "devices": list(disk.get("disks", [])),
            "partitions": list(disk.get("partitions", [])),
        },
        "online": {
            "enabled": online.get("method") == "online",
            "flake": online.get("flake", ""),
            "host": online.get("host", ""),
        },
    }


def _quote(value: str) -> str:
    if any(ord(character) < 0x20 and character not in "\n\r\t" for character in value):
        raise ValueError("strings cannot contain control characters")
    return json.dumps(value, ensure_ascii=False).replace("${", "\\u0024{")


def _serialize_value(value: Any, indent: int) -> str:
    if value is None:
        return "null"
    if value is True:
        return "true"
    if value is False:
        return "false"
    if isinstance(value, int):
        if value < -(2**63) or value > 2**63 - 1:
            raise ValueError("integer is outside the signed 64-bit range")
        return str(value)
    if isinstance(value, float):
        raise ValueError("floating-point values are not supported by zcfg")
    if isinstance(value, str):
        return _quote(value)
    if isinstance(value, PkgsRef):
        return "$pkgs." + ".".join(value.path)
    if isinstance(value, list):
        if not value:
            return "[ ]"
        padding = " " * (indent + 2)
        items = [padding + _serialize_value(item, indent + 2) for item in value]
        return "[\n" + "\n".join(items) + "\n" + " " * indent + "]"
    if isinstance(value, dict):
        return _serialize_attr_set(value, indent)
    raise ValueError(f"unsupported zcfg value: {type(value).__name__}")


def _serialize_attr_set(value: dict[str, Any], indent: int) -> str:
    if not value:
        return "{ }"
    padding = " " * (indent + 2)
    lines = []
    for key in sorted(value):
        _validate_identifier(key, "configuration key")
        lines.append(f"{padding}{key} = {_serialize_value(value[key], indent + 2)};")
    return "{\n" + "\n".join(lines) + "\n" + " " * indent + "}"


def serialize_zcfg(tree: dict[str, Any]) -> str:
    lines = [
        "# Generated by ZenOS Setup. Edit through Scaffold or regenerate from Setup.",
        "# Disk choices and online sources are stored in the installer execution plan.",
        "",
    ]
    for key in sorted(tree):
        _validate_identifier(key, "configuration key")
        lines.append(f"{key} = {_serialize_value(tree[key], 0)};")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def process_installer_payload(
    payload: dict[str, Any],
    *,
    password_hash: str | None = None,
) -> str:
    return serialize_zcfg(build_config_tree(payload, password_hash=password_hash))


def strip_disko_config(text: str) -> str:
    """Legacy API retained only to fail safely until AST-aware online merging exists."""
    if re.search(r"(^|\n)\s*disko(?:\.|\s*=)", text):
        raise ValueError("online configurations with disko require AST-aware merging")
    return text


def format_nix(text: str) -> str:
    """Compatibility shim: new builder output is already deterministic."""
    return text.rstrip() + "\n"


BEHAVIORS: dict[str, tuple[()]] = {}


def apply_behavior(config_str: str, behavior_key: str, **_kwargs: Any) -> str:
    raise ValueError(f"legacy configuration behavior is no longer supported: {behavior_key}")
