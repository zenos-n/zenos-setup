"""Build deterministic ZenOS configuration and installer execution plans."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
import json
from pathlib import Path
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


@dataclass(frozen=True)
class PackageFile:
    package: PkgsRef
    suffix: str
    uri: bool = False


@dataclass(frozen=True)
class GVariant:
    kind: str
    value: int | None = None


DESKTOP_OPTIONS = {
    "gnome": ("desktops", "gnome", "enable"),
    "kde": ("legacy", "services", "desktopManager", "plasma6", "enable"),
    "xfce": ("legacy", "services", "xserver", "desktopManager", "xfce", "enable"),
    "cinnamon": (
        "legacy",
        "services",
        "xserver",
        "desktopManager",
        "cinnamon",
        "enable",
    ),
    "budgie": ("legacy", "services", "desktopManager", "budgie", "enable"),
    "mate": ("legacy", "services", "xserver", "desktopManager", "mate", "enable"),
}

DISPLAY_MANAGER_OPTIONS = {
    "kde": ("legacy", "services", "displayManager", "plasma-login-manager", "enable"),
    "xfce": ("legacy", "services", "xserver", "displayManager", "lightdm", "enable"),
    "cinnamon": ("legacy", "services", "xserver", "displayManager", "lightdm", "enable"),
    "budgie": ("legacy", "services", "xserver", "displayManager", "lightdm", "enable"),
    "mate": ("legacy", "services", "xserver", "displayManager", "lightdm", "enable"),
}

UNAVAILABLE_PACKAGES = {"flatseal", "helium-browser", "ventoy", "zen-browser"}
SUPPORTED_APP_OPTIONS = {"firefox": {"gnome_theme"}}


def _catalog_ids(path: Path, category_key: str) -> set[str]:
    with path.open(encoding="utf-8") as catalog_file:
        catalog = json.load(catalog_file)
    if category_key == "apps":
        categories = catalog.values()
        entries = []
        for category in categories:
            entries.extend(
                category if isinstance(category, list) else category.get("apps", [])
            )
    else:
        entries = catalog
    return {entry["id"] for entry in entries}


_MODULE_ROOT = Path(__file__).resolve().parent
_PROJECT_ROOT = _MODULE_ROOT.parent
_GNOME_EXTENSION_CATALOG = _MODULE_ROOT / "data/gnome-extensions.json"
if not _GNOME_EXTENSION_CATALOG.is_file():
    _GNOME_EXTENSION_CATALOG = _PROJECT_ROOT / "data/gnome-extensions.json"
SOFTWARE_APP_IDS = _catalog_ids(_MODULE_ROOT / "views/extra_software/apps.json", "apps")
GNOME_EXTENSION_IDS = _catalog_ids(_GNOME_EXTENSION_CATALOG, "extensions")

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
    "nautilus": ("legacy", "nautilus"),
    "gnome-console": ("legacy", "gnome-console"),
    "gnome-contacts": ("legacy", "gnome-contacts"),
    "gnome-font-viewer": ("legacy", "gnome-font-viewer"),
    "gnome-logs": ("legacy", "gnome-logs"),
    "gnome-maps": ("legacy", "gnome-maps"),
    "gnome-music": ("legacy", "gnome-music"),
    "gnome-system-monitor": ("legacy", "gnome-system-monitor"),
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


# These are filesystem-derived public package identities, not catalog aliases.
APP_PACKAGE_PATHS = {
    app: ("apps", category, app)
    for category, apps in {
        "browsers": "firefox librewolf ungoogled-chromium brave-browser tor-browser",
        "gaming": "steam heroic lutris bottles prism-launcher retroarch",
        "development": "vscode zed gnome-builder neovim helix gitg github-cli docker jetbrains-toolbox",
        "system": "kitty btop fish zsh",
        "utilities": "pika-backup metadata-cleaner curtail gnome-boxes file-roller impression cipher resources mission-center",
        "office": "libreoffice onlyoffice thunderbird obsidian apostrophe foliate",
        "advanced": "virt-manager podman-desktop wireshark gparted keepassxc bitwarden cockpit nmap",
    }.items()
    for app in apps.split()
}


def _gnome_profile(tree, options, shortcuts, theme, enabled_extensions):
    """Map Setup choices to desktop settings and typed extension modules."""
    extensions = {
        name: {"enable": name in enabled_extensions}
        for name in sorted(GNOME_EXTENSION_IDS)
    }
    extensions["customize-clock-on-lockscreen"] = {"enable": False}
    _set_path(tree, ("desktops", "gnome", "extensions"), extensions)
    directions = shortcuts.get("directions", "vim")
    actions = shortcuts.get("actions", "zenos")
    if directions not in {"standard", "vim"}:
        raise ValueError(f"unsupported shortcut direction mode: {directions!r}")
    if actions not in {"traditional", "zenos"}:
        raise ValueError(f"unsupported shortcut action mode: {actions!r}")
    keys = dict(
        zip(
            ("left", "down", "up", "right"),
            ("h", "j", "k", "l")
            if directions == "vim"
            else ("Left", "Down", "Up", "Right"),
        )
    )
    empty = GVariant("empty-string-array")
    wm = {}
    for direction in ("left", "right"):
        key = keys[direction]
        wm[f"switch-to-workspace-{direction}"] = [f"<Super><Control>{key}"]
        wm[f"move-to-workspace-{direction}"] = [f"<Super><Control><Shift>{key}"]
        wm[f"move-to-monitor-{direction}"] = [f"<Super><Alt>{key}"]
    settings = {
        "org/gnome/desktop/wm/keybindings": wm,
        "org/gnome/mutter/keybindings": {
            "toggle-tiled-left": empty,
            "toggle-tiled-right": empty,
        },
    }
    if actions == "zenos":
        wm.update(
            {
                "close": ["<Super>q"],
                "toggle-maximized": ["<Super>w"],
                "minimize": ["<Super>Page_Down"],
                "activate-window-menu": ["<Alt>space"],
                "begin-resize": ["<Control><Super>c"],
                "switch-input-source": ["<Super>space"],
                "switch-input-source-backward": ["<Shift><Super>space"],
            }
        )
        media = "org/gnome/settings-daemon/plugins/media-keys"
        settings[media] = {
            "maximize": empty,
            "unmaximize": empty,
            "screensaver": ["<Super>Escape"],
            "custom-keybindings": [],
        }
        for name, title, command, binding in (
            ("files", "Files", "nautilus --new-window", "<Super>e"),
            ("terminal", "Console", "kgx", "<Super>t"),
            ("resources", "Resources", "resources", "<Control><Shift>Escape"),
        ):
            path = f"{media}/custom-keybindings/{name}"
            settings[media]["custom-keybindings"].append(f"/{path}/")
            settings[path] = {"name": title, "command": command, "binding": binding}
    if "forge" in enabled_extensions:
        bindings = {}
        for direction, key in keys.items():
            bindings[f"window-focus-{direction}"] = ["super", key]
            bindings[f"window-move-{direction}"] = ["shift", "super", key]
        # Forge's defaults otherwise steal workspace shortcuts and Super+W.
        for direction in keys:
            bindings[f"window-swap-{direction}"] = []
        if actions == "zenos":
            bindings["prefs-tiling-toggle"] = []
        extensions["forge"].update(
            {
                "keybindings": bindings,
                "tiling": {
                    "enable": bool(options.get("tiling", True)),
                    "stacked": False,
                    "tabbed": {"enable": False},
                },
                "interaction": {
                    "dnd-center-layout": "swap",
                    "float-always-on-top": False,
                },
                "appearance": {
                    "borders": {"focus": {"toggle": False}, "split": {"toggle": False}},
                    "gaps": {"size": 4},
                },
                "general": {"quick-settings": False},
            }
        )
    if "date-menu-formatter" in enabled_extensions:
        extensions["date-menu-formatter"].update(
            {
                "font-size": 12,
                "formatter": "01_luxon",
                "pattern": "dd.MM  HH:mm",
                "text-align": "center",
                "update-level": 1,
            }
        )
    if "coverflow-alt-tab" in enabled_extensions:
        extensions["coverflow-alt-tab"].update(
            {
                "desaturate-factor": 0.0,
                "icon-style": "Classic",
                "use-glitch-effect": True,
            }
        )
    if "mouse-tail" in enabled_extensions:
        extensions["mouse-tail"]["render-mode"] = "precise"
    if "notification-timeout" in enabled_extensions:
        extensions["notification-timeout"]["timeout"] = 2000
    if options.get("theme", True):
        for path in (
            ("apps", "cursors", "google-dot"),
            ("apps", "themes", "adw-gtk3"),
            ("theming", "fonts", "zero", "mono-thin"),
            ("theming", "fonts", "zero", "regular"),
            ("theming", "icons", "adwaita-hacks"),
            ("theming", "wallpapers", "destination-2"),
        ):
            _set_path(tree, ("system", "packages", *path), True)
        _set_path(
            tree,
            ("legacy", "fonts", "packages"),
            [
                PkgsRef(("legacy", "atkinson-hyperlegible")),
                PkgsRef(("legacy", "nerd-fonts", "atkynson-mono")),
                PkgsRef(("theming", "fonts", "zero", "mono-thin")),
                PkgsRef(("theming", "fonts", "zero", "regular")),
            ],
        )
        dark = theme.get("dark_mode", True)
        settings["org/gnome/desktop/interface"] = {
            "cursor-size": GVariant("int32", 24),
            "cursor-theme": "GoogleDot-Black",
            "document-font-name": "Atkinson Hyperlegible 11",
            "font-name": "Atkinson Hyperlegible 11",
            "gtk-theme": "adw-gtk3-dark" if dark else "adw-gtk3",
            "icon-theme": "Adwaita-hacks",
            "monospace-font-name": "AtkynsonMono NF 11",
        }
        color = theme.get("accent", "purple")
        color = "slate" if color == "grey" else color
        wallpaper = PackageFile(
            PkgsRef(("theming", "wallpapers", "destination-2")),
            f"/share/backgrounds/destination-2/{color}{' dark' if dark else ''}.png",
            True,
        )
        settings["org/gnome/desktop/background"] = {
            "color-shading-type": "solid",
            "picture-options": "zoom",
            "picture-uri": wallpaper,
            "picture-uri-dark": wallpaper,
            "primary-color": "#000000",
            "secondary-color": "#000000",
        }
        if "user-themes" in enabled_extensions:
            extensions["user-themes"].update(
                {
                    "name": "ClockOverride",
                    "theme": {
                        "cssOverride": ".clock-display { font-family: 'Zero', sans-serif !important; font-size: 12px; font-style: normal !important; font-weight: normal !important; letter-spacing: 0 !important; }"
                    },
                },
            )
        if options.get("extensions", True):
            extensions["customize-clock-on-lockscreen"].update(
                {
                    "enable": True,
                    "command": {"enable": False},
                    "time": {
                        "text": "%H\n%M",
                        "font": {
                            "family": "Zero Mono Thin",
                            "size": 96,
                            "weight": "Thin",
                            "color": "rgba(255, 255, 255, 1.0)",
                        },
                    },
                    "date": {
                        "text": "%d.%m.%Y",
                        "font": {
                            "family": "Zero",
                            "size": 24,
                            "color": "rgba(255, 255, 255, 1.0)",
                        },
                    },
                },
            )
        _set_path(
            tree,
            ("legacy", "programs", "dconf", "profiles", "gdm", "databases"),
            [
                {
                    "settings": {
                        "org/gnome/login-screen": {
                            "disable-user-list": False,
                            "logo": PackageFile(
                                PkgsRef(("theming", "icons", "zenos-icons")),
                                "/share/icons/hicolor/scalable/apps/zenos.svg",
                            ),
                        },
                        "org/gnome/desktop/lockdown": {"disable-lock-screen": True},
                        "org/gnome/desktop/session": {
                            "idle-delay": GVariant("uint32", 0)
                        },
                        "org/gnome/settings-daemon/plugins/power": {
                            "sleep-inactive-ac-type": "nothing",
                            "sleep-inactive-battery-type": "nothing",
                        },
                        "org/gnome/desktop/interface": {
                            "accent-color": theme.get("accent", "purple"),
                            "color-scheme": "prefer-dark" if dark else "prefer-light",
                            "cursor-theme": "GoogleDot-Black",
                            "font-name": "Atkinson Hyperlegible 11",
                            "icon-theme": "Adwaita-hacks",
                        },
                    }
                }
            ],
        )
    _set_path(
        tree,
        ("legacy", "programs", "dconf", "profiles", "user", "databases"),
        [{"settings": settings}],
    )


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

    # Branding, release state, boot, and ZenFS integration belong to the template.
    _set_path(tree, ("legacy", "networking", "networkmanager", "enable"), True)

    language = pages.get("language", {})
    _set_path(
        tree,
        ("legacy", "i18n", "defaultLocale"),
        language.get("locale") or "en_US.UTF-8",
    )
    locale = language.get("locale") or "en_US.UTF-8"
    _set_path(tree, ("legacy", "i18n", "supportedLocales"), [f"{locale}/UTF-8"])

    timezone = pages.get("timezone", {}).get("timezone", {})
    region = timezone.get("region") or "Europe"
    zone = timezone.get("zone") or "London"
    _set_path(tree, ("legacy", "time", "timeZone"), f"{region}/{zone}")

    keyboards = pages.get("keyboard", {}).get("keyboard", [])
    if keyboards:
        layouts = [item.get("layout", "us") for item in keyboards]
        variants = [item.get("variant", "") for item in keyboards]
        model = keyboards[0].get("model") or "pc105"
        if any((item.get("model") or "pc105") != model for item in keyboards):
            raise ValueError("multiple keyboard models are unsupported")
        _set_path(
            tree, ("legacy", "services", "xserver", "xkb", "layout"), ",".join(layouts)
        )
        _set_path(
            tree,
            ("legacy", "services", "xserver", "xkb", "variant"),
            ",".join(variants),
        )
        _set_path(tree, ("legacy", "services", "xserver", "xkb", "model"), model)
        _set_path(tree, ("legacy", "console", "useXkbConfig"), True)

    host_name = pages.get("computer_name", {}).get("hostname")
    if host_name:
        _validate_identifier(host_name, "hostname")
        _set_path(tree, ("legacy", "networking", "hostName"), host_name)

    user = pages.get("user")
    if user:
        username = user.get("username", "")
        _validate_identifier(username, "username")
        hashed = password_hash or hash_password(user.get("password", ""))
        if not hashed.startswith("$"):
            raise ValueError("password_hash must be a modular crypt hash")
        base = ("users", username, "legacy")
        _set_path(tree, (*base, "isNormalUser"), True)
        _set_path(tree, (*base, "uid"), 1000)
        _set_path(tree, (*base, "description"), user.get("fullname") or username)
        _set_path(tree, (*base, "home"), f"/Users/{username}")
        _set_path(tree, (*base, "initialHashedPassword"), hashed)
        _set_path(tree, (*base, "extraGroups"), ["networkmanager", "video", "wheel"])
        _set_path(tree, (*base, "shell"), PkgsRef(("legacy", "zsh")))
        _set_path(tree, (*base, "packages"), [PkgsRef(("legacy", "zsh"))])
        _set_path(tree, ("legacy", "programs", "zsh", "enable"), True)
        _set_path(
            tree,
            ("legacy", "programs", "zsh", "interactiveShellInit"),
            'private_config="$XDG_CONFIG_HOME"\n'
            '[[ -n "$private_config" ]] || private_config="$HOME/.private/Config"\n'
            'private_zshrc="$private_config/zsh/.zshrc"\n'
            '[[ ! -f "$private_zshrc" ]] || source "$private_zshrc"',
        )
        home = (*base, "homeManager")
        _set_path(
            tree,
            (*home, "xdg", "configFile"),
            {
                "zsh/p10k.zsh": {
                    "source": PackageFile(
                        PkgsRef(("system", "zenos-shell-defaults")),
                        "/share/zenos-shell/p10k.zsh",
                    ),
                },
            },
        )
        _set_path(tree, (*home, "programs", "direnv", "enable"), True)
        _set_path(tree, (*home, "programs", "direnv", "nix-direnv", "enable"), True)
        _set_path(tree, (*home, "programs", "zoxide", "enable"), True)
        _set_path(tree, (*home, "programs", "zoxide", "enableZshIntegration"), True)
        _set_path(tree, (*home, "programs", "zsh", "enable"), True)
        _set_path(tree, (*home, "programs", "zsh", "enableCompletion"), True)
        _set_path(tree, (*home, "programs", "zsh", "autosuggestion", "enable"), True)
        _set_path(tree, (*home, "programs", "zsh", "syntaxHighlighting", "enable"), True)
        _set_path(
            tree,
            (*home, "programs", "zsh", "dotDir"),
            f"/Users/{username}/.private/Config/zsh",
        )
        _set_path(tree, (*home, "programs", "zsh", "history", "size"), 10000)
        _set_path(
            tree,
            (*home, "programs", "zsh", "shellAliases"),
            {
                "g": "git",
                "ga": "git add",
                "gaa": "git add .",
                "gc": "git commit -m",
                "gs": "git status",
                "gp": "git push",
                "gl": "git log --oneline --graph --decorate",
                "da": "direnv allow",
                "dr": "direnv reload",
                "myip": "curl ifconfig.me",
            },
        )
        _set_path(
            tree,
            (*home, "programs", "zsh", "plugins"),
            [
                {
                    "name": "powerlevel10k",
                    "src": PkgsRef(("legacy", "zsh-powerlevel10k")),
                    "file": "share/zsh-powerlevel10k/powerlevel10k.zsh-theme",
                },
            ],
        )
        _set_path(
            tree,
            (*home, "programs", "zsh", "initContent"),
            '[[ ! -f "$XDG_CONFIG_HOME/zsh/p10k.zsh" ]] || source "$XDG_CONFIG_HOME/zsh/p10k.zsh"\n'
            "bindkey '^[[A' up-line-or-search\nbindkey '^[[B' down-line-or-search",
        )

    desktop = pages.get("desktop", {"install_de": True, "desktop_environment": "gnome"})
    selected = (
        desktop.get("desktop_environment", "") if desktop.get("install_de") else "none"
    )
    if selected == "none":
        _set_path(tree, ("system", "zenfs", "apps", "enable"), False)
    if payload.get("oobe"):
        _set_path(tree, ("system", "oobe", "enable"), True)
    _set_path(tree, DESKTOP_OPTIONS["gnome"], selected == "gnome")
    if desktop.get("install_de"):
        option = DESKTOP_OPTIONS.get(selected)
        if option is None:
            raise ValueError(f"unsupported desktop environment: {selected!r}")
        if selected != "gnome":
            _set_path(tree, option, True)
            _set_path(tree, ("legacy", "services", "xserver", "enable"), True)
        if selected != "gnome":
            _set_path(tree, DISPLAY_MANAGER_OPTIONS[selected], True)
        if selected == "kde":
            _set_path(
                tree, ("legacy", "services", "displayManager", "sddm", "enable"), False
            )
        if selected == "gnome":
            gnome_options = desktop.get(
                "gnome_options", {"theme": False, "extensions": False, "tiling": False}
            )
            extension_ids = gnome_options.get("extension_ids")
            if extension_ids is not None:
                if not isinstance(extension_ids, list) or not all(
                    isinstance(extension_id, str) and IDENTIFIER.fullmatch(extension_id)
                    for extension_id in extension_ids
                ):
                    raise ValueError("GNOME extension ids must be valid identifiers")
                unknown_extensions = set(extension_ids) - GNOME_EXTENSION_IDS
                if unknown_extensions:
                    raise ValueError(
                        f"unknown GNOME extension ids: {sorted(unknown_extensions)}"
                    )
            elif gnome_options.get("extensions", True):
                with _GNOME_EXTENSION_CATALOG.open(encoding="utf-8") as file:
                    extension_ids = [
                        entry["id"]
                        for entry in json.load(file)
                        if entry.get("recommended")
                    ]
            enabled_extensions = (
                set(extension_ids or [])
                if gnome_options.get("extensions", True)
                else set()
            )
            if gnome_options.get("tiling", True):
                enabled_extensions.add("forge")
            _gnome_profile(
                tree,
                gnome_options,
                pages.get("shortcuts", {}),
                pages.get("theme", {}),
                enabled_extensions,
            )
            theme = pages.get("theme", {})
            accent = theme.get("accent", "purple")
            accent = "grey" if accent == "slate" else accent
            if accent not in {
                "blue",
                "teal",
                "purple",
                "red",
                "orange",
                "yellow",
                "green",
                "pink",
                "grey",
            }:
                raise ValueError(f"unsupported GNOME accent: {accent!r}")
            _set_path(tree, ("desktops", "gnome", "defaultAccentColor"), accent)
            _set_path(
                tree,
                ("desktops", "gnome", "defaultDarkMode"),
                theme.get("dark_mode", True),
            )

    packages = []
    core_exclusions = []
    firefox_enabled = False
    firefox_gnome_theme = False
    for app in pages.get("software", {}).get("apps", []):
        app_id = app.get("app", "")
        _validate_identifier(app_id, "application id")
        if app_id not in SOFTWARE_APP_IDS:
            raise ValueError(f"unknown application: {app_id!r}")
        extra_options = app.get("extraOptions", [])
        if not isinstance(extra_options, list) or not all(
            isinstance(option, str) for option in extra_options
        ):
            raise ValueError(f"invalid application options for {app_id!r}")
        unsupported_options = set(extra_options) - SUPPORTED_APP_OPTIONS.get(
            app_id, set()
        )
        if app.get("enabled") and unsupported_options:
            raise ValueError(
                f"unsupported options for {app_id!r}: {sorted(unsupported_options)}"
            )
        if app.get("includedByDesktop"):
            if not app.get("enabled"):
                package_path = CORE_PACKAGE_PATHS.get(app_id)
                if package_path is None:
                    raise ValueError(f"unknown desktop core application: {app_id!r}")
                core_exclusions.append(PkgsRef(package_path))
            continue
        if not app.get("enabled"):
            continue
        if app_id in UNAVAILABLE_PACKAGES:
            raise ValueError(
                f"application is unavailable in the current ZenPkgs registry: {app_id}"
            )
        if app_id == "firefox":
            firefox_enabled = True
            firefox_gnome_theme = "gnome_theme" in extra_options
        if app_id != "firefox":
            package_path = APP_PACKAGE_PATHS.get(app_id) or CORE_PACKAGE_PATHS.get(
                app_id
            )
            if package_path is None:
                raise ValueError(
                    f"application is unavailable in the current ZenPkgs registry: {app_id}"
                )
            packages.append(package_path)
    if firefox_enabled:
        packages.append(APP_PACKAGE_PATHS["firefox"])
        if firefox_gnome_theme and selected == "gnome":
            _set_path(
                tree,
                ("desktops", "gnome", "tweaks", "firefox-theming", "enable"),
                True,
            )
        elif firefox_gnome_theme:
            raise ValueError("Firefox GNOME theme requires the GNOME desktop")
    if core_exclusions:
        selected = pages.get("desktop", {}).get("desktop_environment", "")
        option = CORE_EXCLUDE_OPTIONS.get(selected)
        if option is None:
            raise ValueError(
                f"desktop core exclusions are unsupported for: {selected!r}"
            )
        _set_path(
            tree,
            option,
            sorted(set(core_exclusions), key=lambda item: item.path),
        )
    if packages:
        for path in sorted(set(packages)):
            _set_path(tree, ("system", "packages", *path), True)

    return tree


def build_execution_plan(payload: dict[str, Any]) -> dict[str, Any]:
    pages = _pages(payload)
    disk = pages.get("disks", {})
    online = pages.get("online", {})
    theme = pages.get("theme", {})
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
        "theme": {
            "accent": theme.get("accent", "purple"),
            "darkMode": theme.get("dark_mode", True),
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
        decimal = Decimal(str(value))
        if not decimal.is_finite():
            raise ValueError(
                "non-finite floating-point values are not supported by zcfg"
            )
        # ZCFG accepts decimal literals, not Python's exponent notation.
        rendered = format(decimal, "f")
        return rendered if "." in rendered else rendered + ".0"
    if isinstance(value, str):
        return _quote(value)
    if isinstance(value, PkgsRef):
        return "$pkgs." + ".".join(value.path)
    if isinstance(value, PackageFile):
        suffix = _quote(value.suffix)[1:-1]
        return (
            '"'
            + ("file://" if value.uri else "")
            + "${"
            + _serialize_value(value.package, indent)
            + "}"
            + suffix
            + '"'
        )
    if isinstance(value, GVariant):
        # ZCFG forbids calls/lambdas. Nix's standard outPath coercion supplies
        # the serialized value for the upstream GVariant record, without code.
        if value.kind == "empty-string-array":
            return _serialize_value(
                {"_type": "gvariant", "type": "as", "value": [], "outPath": "@as []"},
                indent,
            )
        code = {"int32": "i", "uint32": "u", "double": "d"}[value.kind]
        return _serialize_value(
            {
                "_type": "gvariant",
                "type": code,
                "value": value.value,
                "outPath": f"@{code} {value.value}",
            },
            indent,
        )
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
        rendered_key = key if IDENTIFIER.fullmatch(key) else _quote(key)
        lines.append(
            f"{padding}{rendered_key} = {_serialize_value(value[key], indent + 2)};"
        )
    return "{\n" + "\n".join(lines) + "\n" + " " * indent + "}"


def serialize_zcfg(tree: dict[str, Any]) -> str:
    lines = [
        "# Generated by ZenOS Setup. Edit through Scaffold or regenerate from Setup.",
        "# Disk layout is stored in drives.zcfg.",
        "",
    ]
    for key in sorted(tree):
        _validate_identifier(key, "configuration key")
        lines.append(f"{key} = {_serialize_value(tree[key], 0)};")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def build_config_documents(
    payload: dict[str, Any],
    *,
    password_hash: str | None = None,
) -> dict[str, str]:
    tree = build_config_tree(payload, password_hash=password_hash)
    documents: dict[str, dict[str, Any]] = {}

    desktop = {}
    for key in ("desktops",):
        if key in tree:
            desktop[key] = tree.pop(key)
    if desktop:
        documents["desktop.zcfg"] = desktop

    users = tree.pop("users", {})
    legacy = tree.get("legacy", {})
    for username, config in users.items():
        documents[f"users/{username}/main.zcfg"] = {"users": {username: config}}

    apps = {}
    system = tree.get("system", {})
    if "packages" in system:
        apps["system"] = {"packages": system.pop("packages")}
    legacy_apps = {}
    for key in ("environment", "programs"):
        if key in legacy:
            legacy_apps[key] = legacy.pop(key)
    if legacy_apps:
        apps["legacy"] = legacy_apps
    if apps:
        documents["apps.zcfg"] = apps

    if not legacy:
        tree.pop("legacy", None)
    if not system:
        tree.pop("system", None)
    documents["system.zcfg"] = tree

    rendered = {name: serialize_zcfg(value) for name, value in documents.items()}
    imports = "".join(f'_import "./{name}";\n' for name in sorted(rendered))
    return {"host.zcfg": imports, **rendered}


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
    raise ValueError(
        f"legacy configuration behavior is no longer supported: {behavior_key}"
    )
