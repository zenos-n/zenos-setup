import copy
import json
from pathlib import Path
import unittest

from src.builder import (
    GNOME_EXTENSION_IDS,
    GVariant,
    PackageFile,
    PkgsRef,
    build_config_documents,
    build_config_tree,
    build_execution_plan,
    process_installer_payload,
    serialize_zcfg,
)


FULL_PAYLOAD = {
    "oobe": False,
    "pages": [
        {"id": "language", "locale": "pl_PL.UTF-8", "display_name": "Polski"},
        {"id": "timezone", "timezone": {"region": "Europe", "zone": "Warsaw"}},
        {
            "id": "keyboard",
            "keyboard": [{"layout": "pl", "variant": "", "model": "pc105"}],
        },
        {"id": "network", "network_status": "connected"},
        {"id": "computer_name", "hostname": "zen-box"},
        {
            "id": "user",
            "fullname": "Zen User",
            "username": "zen",
            "password": "not-written-to-config",
        },
        {
            "id": "desktop",
            "install_de": True,
            "desktop_environment": "gnome",
            "gnome_options": {
                "theme": False,
                "extensions": True,
                "extension_ids": ["forge", "user-themes"],
                "tiling": False,
            },
        },
        {"id": "shortcuts", "directions": "standard", "actions": "traditional"},
        {"id": "theme", "dark_mode": True, "accent": "purple"},
        {
            "id": "software",
            "apps": [
                {"app": "firefox", "enabled": True, "extraOptions": ["gnome_theme"]},
                {"app": "steam", "enabled": False, "extraOptions": []},
            ],
        },
        {"id": "disks", "mode": "auto", "disks": ["vda"], "partitions": []},
    ],
}


def default_payload():
    payload = copy.deepcopy(FULL_PAYLOAD)
    root = Path(__file__).resolve().parent.parent
    extensions = json.loads((root / "data/gnome-extensions.json").read_text())
    apps = json.loads((root / "src/views/extra_software/apps.json").read_text())
    for page in payload["pages"]:
        if page["id"] == "desktop":
            page["gnome_options"] = {
                "theme": True,
                "extensions": True,
                "tiling": True,
                "extension_ids": [
                    entry["id"] for entry in extensions if entry.get("recommended")
                ],
            }
        elif page["id"] == "shortcuts":
            page.update(directions="vim", actions="zenos")
        elif page["id"] == "software":
            page["apps"] = []
            for category_id, category in apps.items():
                if category_id.startswith("core-") and category_id not in {
                    "core-gnome",
                    "core-generic",
                }:
                    continue
                included = category.get("includedByDesktop", False)
                for app in category["apps"]:
                    if not app.get("available", True):
                        continue
                    page["apps"].append(
                        {
                            "app": app["id"],
                            "enabled": app.get("default", included),
                            "includedByDesktop": included,
                            "extraOptions": [
                                option["id"]
                                for option in app.get("extraOptions", [])
                                if option.get("implemented") and option.get("default")
                            ],
                        }
                    )
    return payload


class BuilderTests(unittest.TestCase):
    def test_full_payload_maps_to_declarative_config(self):
        tree = build_config_tree(FULL_PAYLOAD, password_hash="$6$test$hash")

        self.assertEqual(tree["legacy"]["i18n"]["defaultLocale"], "pl_PL.UTF-8")
        self.assertEqual(
            tree["legacy"]["i18n"]["supportedLocales"], ["pl_PL.UTF-8/UTF-8"]
        )
        self.assertEqual(tree["legacy"]["time"]["timeZone"], "Europe/Warsaw")
        self.assertEqual(tree["legacy"]["networking"]["hostName"], "zen-box")
        self.assertTrue(tree["desktops"]["gnome"]["enable"])
        self.assertFalse(
            tree["desktops"]["gnome"]["extensions"]["forge"]["tiling"]["enable"]
        )
        self.assertEqual(tree["desktops"]["gnome"]["defaultAccentColor"], "purple")
        self.assertNotIn("gnomeProfile", tree)
        self.assertNotIn("release", tree["system"])
        self.assertTrue(tree["users"]["zen"]["legacy"]["isNormalUser"])
        self.assertEqual(tree["users"]["zen"]["legacy"]["uid"], 1000)
        self.assertEqual(tree["users"]["zen"]["legacy"]["home"], "/Users/zen")
        self.assertNotIn("zenfs", tree["legacy"])
        self.assertTrue(tree["system"]["packages"]["apps"]["browsers"]["firefox"])
        self.assertTrue(
            tree["desktops"]["gnome"]["tweaks"]["firefox-theming"]["enable"]
        )
        self.assertNotIn("disks", tree)

    def test_output_is_deterministic_and_never_contains_plaintext_password(self):
        first = process_installer_payload(FULL_PAYLOAD, password_hash="$6$test$hash")
        second = process_installer_payload(FULL_PAYLOAD, password_hash="$6$test$hash")

        self.assertEqual(first, second)
        self.assertNotIn("not-written-to-config", first)
        self.assertIn('initialHashedPassword = "$6$test$hash";', first)
        self.assertIn("legacy = {", first)
        self.assertNotIn("$pkgs.catalog.firefox", first)
        self.assertIn("firefox-theming", first)
        self.assertNotIn("zenos = {", first)
        self.assertNotIn("$pkgs.zenos", first)

    def test_generated_config_is_split_into_zcfg_documents(self):
        documents = build_config_documents(FULL_PAYLOAD, password_hash="$6$test$hash")

        self.assertEqual(
            set(documents),
            {
                "apps.zcfg",
                "desktop.zcfg",
                "host.zcfg",
                "system.zcfg",
                "users/zen/main.zcfg",
            },
        )
        self.assertIn('_import "./apps.zcfg";', documents["host.zcfg"])
        self.assertIn('_import "./users/zen/main.zcfg";', documents["host.zcfg"])
        self.assertIn("legacy = {", documents["users/zen/main.zcfg"])
        self.assertNotIn("zenfs", documents["users/zen/main.zcfg"])
        self.assertIn("firefox = true;", documents["apps.zcfg"])
        self.assertIn("forge = {", documents["desktop.zcfg"])
        self.assertIn("window-focus-left = [", documents["desktop.zcfg"])
        self.assertNotIn("forge", documents["apps.zcfg"])

    def test_execution_plan_owns_disk_and_network_state(self):
        plan = build_execution_plan(FULL_PAYLOAD)

        self.assertEqual(plan["disk"]["mode"], "auto")
        self.assertEqual(plan["disk"]["devices"], ["vda"])
        self.assertEqual(plan["networkStatus"], "connected")
        self.assertEqual(plan["theme"], {"accent": "purple", "darkMode": True})

    def test_default_user_gets_private_zsh_environment(self):
        tree = build_config_tree(default_payload(), password_hash="$6$test$hash")
        user = tree["users"]["zen"]["legacy"]
        self.assertEqual(user["shell"], PkgsRef(("legacy", "zsh")))
        self.assertEqual(user["packages"], [PkgsRef(("legacy", "zsh"))])
        home = user["homeManager"]
        self.assertTrue(home["programs"]["direnv"]["enable"])
        self.assertTrue(home["programs"]["direnv"]["nix-direnv"]["enable"])
        self.assertTrue(home["programs"]["zoxide"]["enableZshIntegration"])
        self.assertTrue(home["programs"]["zsh"]["autosuggestion"]["enable"])
        self.assertTrue(home["programs"]["zsh"]["syntaxHighlighting"]["enable"])
        self.assertEqual(home["programs"]["zsh"]["history"]["size"], 10000)
        self.assertEqual(
            home["xdg"]["configFile"]["zsh/p10k.zsh"]["source"],
            PackageFile(PkgsRef(("system", "zenos-shell-defaults")), "/share/zenos-shell/p10k.zsh"),
        )
        self.assertIn("powerlevel10k", home["programs"]["zsh"]["plugins"][0]["name"])

    def test_invalid_dynamic_identifier_is_rejected(self):
        payload = {"pages": [{"id": "user", "username": "bad user", "password": "x"}]}
        with self.assertRaisesRegex(ValueError, "invalid username"):
            build_config_tree(payload, password_hash="$6$test$hash")

    def test_unavailable_registry_package_is_rejected(self):
        payload = {
            "pages": [
                {
                    "id": "software",
                    "apps": [{"app": "zen-browser", "enabled": True}],
                }
            ]
        }
        with self.assertRaisesRegex(ValueError, "unavailable"):
            build_config_tree(payload)

    def test_unknown_application_is_rejected_before_nix_evaluation(self):
        payload = {
            "pages": [
                {
                    "id": "software",
                    "apps": [{"app": "unknown-editor", "enabled": True}],
                }
            ]
        }
        with self.assertRaisesRegex(ValueError, "unknown application"):
            build_config_tree(payload)

    def test_unimplemented_application_option_is_rejected(self):
        payload = {
            "pages": [
                {
                    "id": "software",
                    "apps": [
                        {
                            "app": "firefox",
                            "enabled": True,
                            "extraOptions": ["privacy-hardening"],
                        }
                    ],
                }
            ]
        }
        with self.assertRaisesRegex(ValueError, "unsupported options"):
            build_config_tree(payload)

    def test_unknown_gnome_extension_is_rejected(self):
        payload = {
            "pages": [
                {
                    "id": "desktop",
                    "install_de": True,
                    "desktop_environment": "gnome",
                    "gnome_options": {"extension_ids": ["unknown-extension"]},
                }
            ]
        }
        with self.assertRaisesRegex(ValueError, "unknown GNOME extension"):
            build_config_tree(payload)

    def test_desktop_owned_core_apps_are_not_emitted_twice(self):
        payload = {
            "pages": [
                {
                    "id": "software",
                    "apps": [
                        {
                            "app": "nautilus",
                            "enabled": True,
                            "includedByDesktop": True,
                        },
                        {"app": "firefox", "enabled": True},
                    ],
                }
            ]
        }
        tree = build_config_tree(payload)
        self.assertNotIn("software", tree["system"])

    def test_disabled_desktop_core_app_is_excluded(self):
        payload = {
            "pages": [
                {
                    "id": "desktop",
                    "install_de": True,
                    "desktop_environment": "gnome",
                },
                {
                    "id": "software",
                    "apps": [
                        {
                            "app": "nautilus",
                            "enabled": False,
                            "includedByDesktop": True,
                        }
                    ],
                },
            ]
        }
        tree = build_config_tree(payload)
        self.assertEqual(
            tree["legacy"]["environment"]["gnome"]["excludePackages"],
            [PkgsRef(("legacy", "nautilus"))],
        )

    def test_all_disabled_gnome_defaults_use_native_exclusions(self):
        payload = {
            "pages": [
                {
                    "id": "desktop",
                    "install_de": True,
                    "desktop_environment": "gnome",
                },
                {
                    "id": "software",
                    "apps": [
                        {
                            "app": "epiphany",
                            "enabled": False,
                            "includedByDesktop": True,
                        },
                        {
                            "app": "gnome-disk-utility",
                            "enabled": False,
                            "includedByDesktop": True,
                        },
                        {
                            "app": "gnome-extensions-app",
                            "enabled": False,
                            "includedByDesktop": True,
                        },
                    ],
                },
            ]
        }

        tree = build_config_tree(payload)
        self.assertEqual(
            tree["legacy"]["environment"]["gnome"]["excludePackages"],
            [
                PkgsRef(("legacy", "epiphany")),
                PkgsRef(("legacy", "gnome-disk-utility")),
                PkgsRef(("legacy", "gnome-extension-manager")),
            ],
        )

    def test_serializer_escapes_interpolation_and_supports_typed_floats(self):
        source = serialize_zcfg({"networking": {"hostName": "host-${unsafe}"}})
        self.assertIn(r"host-\u0024{unsafe}", source)
        for value, expected in (
            (0.0, "0.0"),
            (1.5, "1.5"),
            (-0.7, "-0.7"),
            (1e-7, "0.0000001"),
            (1e20, "100000000000000000000.0"),
        ):
            with self.subTest(value=value):
                self.assertIn(f"value = {expected};", serialize_zcfg({"value": value}))
        for value in (float("inf"), float("-inf"), float("nan")):
            with (
                self.subTest(value=value),
                self.assertRaisesRegex(ValueError, "non-finite"),
            ):
                serialize_zcfg({"value": value})

    def test_default_selected_profile_is_fully_rendered(self):
        tree = build_config_tree(default_payload(), password_hash="$6$test$hash")
        gnome = tree["desktops"]["gnome"]
        extensions = gnome["extensions"]
        self.assertTrue(extensions["dash-stacks"]["enable"])
        self.assertTrue(extensions["forge"]["enable"])
        self.assertTrue(extensions["alphabetical-app-grid"]["enable"])
        self.assertTrue(extensions["clipboard-indicator"]["enable"])
        self.assertFalse(extensions["app-hider"]["enable"])
        self.assertFalse(extensions["burn-my-windows"]["enable"])
        self.assertFalse(extensions["hide-top-bar"]["enable"])
        self.assertTrue(tree["system"]["packages"]["theming"]["icons"]["adwaita-hacks"])
        settings = tree["legacy"]["programs"]["dconf"]["profiles"]["user"]["databases"][
            0
        ]["settings"]
        self.assertEqual(
            settings["org/gnome/desktop/wm/keybindings"]["close"], ["<Super>q"]
        )
        self.assertEqual(
            settings["org/gnome/desktop/wm/keybindings"]["switch-to-workspace-left"],
            ["<Super><Control>h"],
        )
        self.assertEqual(
            extensions["forge"]["keybindings"]["window-focus-left"],
            ["super", "h"],
        )
        self.assertTrue(extensions["forge"]["tiling"]["enable"])
        self.assertFalse(extensions["forge"]["tiling"]["stacked"])
        self.assertFalse(extensions["forge"]["tiling"]["tabbed"]["enable"])
        self.assertEqual(
            extensions["forge"]["appearance"],
            {
                "borders": {"focus": {"toggle": False}, "split": {"toggle": False}},
                "gaps": {"size": 4},
            },
        )
        self.assertEqual(
            extensions["forge"]["interaction"],
            {
                "dnd-center-layout": "swap",
                "float-always-on-top": False,
            },
        )
        self.assertEqual(extensions["forge"]["general"], {"quick-settings": False})
        self.assertEqual(
            extensions["date-menu-formatter"],
            {
                "enable": True,
                "font-size": 12,
                "formatter": "01_luxon",
                "pattern": "dd.MM  HH:mm",
                "text-align": "center",
                "update-level": 1,
            },
        )
        self.assertEqual(
            extensions["coverflow-alt-tab"],
            {
                "enable": True,
                "desaturate-factor": 0.0,
                "icon-style": "Classic",
                "use-glitch-effect": True,
            },
        )
        self.assertIs(type(extensions["coverflow-alt-tab"]["desaturate-factor"]), float)
        self.assertEqual(
            extensions["mouse-tail"], {"enable": True, "render-mode": "precise"}
        )
        self.assertEqual(
            extensions["notification-timeout"], {"enable": True, "timeout": 2000}
        )
        self.assertEqual(
            settings["org/gnome/desktop/interface"]["gtk-theme"], "adw-gtk3-dark"
        )

    def test_all_shortcut_combinations_and_stock_branding(self):
        for directions in ("vim", "standard"):
            for actions in ("zenos", "traditional"):
                payload = copy.deepcopy(FULL_PAYLOAD)
                next(
                    page for page in payload["pages"] if page["id"] == "shortcuts"
                ).update(directions=directions, actions=actions)
                tree = build_config_tree(payload, password_hash="$6$test$hash")
                settings = tree["legacy"]["programs"]["dconf"]["profiles"]["user"][
                    "databases"
                ][0]["settings"]
                self.assertNotIn("org/gnome/desktop/interface", settings)
                self.assertEqual(
                    "close" in settings["org/gnome/desktop/wm/keybindings"],
                    actions == "zenos",
                )
                self.assertEqual(
                    tree["desktops"]["gnome"]["extensions"]["user-themes"],
                    {"enable": True},
                )
                bindings = tree["desktops"]["gnome"]["extensions"]["forge"][
                    "keybindings"
                ]
                keys = (
                    ("h", "j", "k", "l")
                    if directions == "vim"
                    else ("Left", "Down", "Up", "Right")
                )
                for direction, key in zip(("left", "down", "up", "right"), keys):
                    self.assertEqual(
                        bindings[f"window-focus-{direction}"], ["super", key]
                    )
                    self.assertEqual(
                        bindings[f"window-move-{direction}"], ["shift", "super", key]
                    )
                    self.assertEqual(bindings[f"window-swap-{direction}"], [])
                if actions == "zenos":
                    self.assertEqual(bindings["prefs-tiling-toggle"], [])
                else:
                    self.assertNotIn("prefs-tiling-toggle", bindings)

    def test_extension_selection_and_independent_tiling_toggle(self):
        selections = (
            [],
            ["forge"],
            ["dash-stacks", "date-menu-formatter"],
            sorted(GNOME_EXTENSION_IDS),
        )
        for selected in selections:
            for enabled in (False, True):
                for tiling in (False, True):
                    with self.subTest(
                        selected=selected, enabled=enabled, tiling=tiling
                    ):
                        payload = {
                            "pages": [
                                {
                                    "id": "desktop",
                                    "install_de": True,
                                    "desktop_environment": "gnome",
                                    "gnome_options": {
                                        "theme": False,
                                        "extensions": enabled,
                                        "extension_ids": selected,
                                        "tiling": tiling,
                                    },
                                }
                            ]
                        }
                        tree = build_config_tree(payload)
                        self.assertTrue(tree["desktops"]["gnome"]["enable"])
                        modules = tree["desktops"]["gnome"]["extensions"]
                        expected = set(selected) if enabled else set()
                        if tiling:
                            expected.add("forge")
                        self.assertEqual(
                            {
                                name
                                for name, config in modules.items()
                                if config["enable"]
                            },
                            expected,
                        )
                        for name, config in modules.items():
                            if name not in expected:
                                self.assertEqual(config, {"enable": False})
                        if "forge" in expected:
                            self.assertEqual(
                                modules["forge"]["tiling"]["enable"], tiling
                            )
                        source = serialize_zcfg(tree)
                        for forbidden in (
                            "extensionPackages",
                            "extensionUuids",
                            "extensionUuid",
                            "enabled-extensions",
                            "org/gnome/shell/extensions/",
                            "$pkgs.apps.gnome-extensions",
                            "$pkgs.desktops.gnome.extensions",
                            "configure = true;",
                            "/Users/zenos/",
                            "com.negzero.zenos.setup.desktop",
                        ):
                            self.assertNotIn(forbidden, source)

    def test_missing_extension_ids_use_recommendations_not_live_choices(self):
        payload = default_payload()
        expected = build_config_tree(payload, password_hash="$6$test$hash")
        options = next(page for page in payload["pages"] if page["id"] == "desktop")[
            "gnome_options"
        ]
        del options["extension_ids"]
        self.assertEqual(
            build_config_tree(payload, password_hash="$6$test$hash"), expected
        )
        options["extension_ids"] = ["dash-stacks", "forge", "dash-stacks"]
        first = build_config_documents(payload, password_hash="$6$test$hash")
        options["extension_ids"] = ["forge", "dash-stacks"]
        self.assertEqual(
            build_config_documents(payload, password_hash="$6$test$hash"), first
        )

    def test_branding_clock_gdm_and_firefox_flags_remain_independent(self):
        for branding in (False, True):
            for enabled in (False, True):
                for dark in (False, True):
                    for firefox_theme in (False, True):
                        with self.subTest(
                            branding=branding,
                            enabled=enabled,
                            dark=dark,
                            firefox_theme=firefox_theme,
                        ):
                            payload = copy.deepcopy(FULL_PAYLOAD)
                            pages = {page["id"]: page for page in payload["pages"]}
                            pages["desktop"]["gnome_options"].update(
                                theme=branding, extensions=enabled
                            )
                            pages["theme"].update(dark_mode=dark, accent="grey")
                            pages["software"]["apps"][0]["extraOptions"] = (
                                ["gnome_theme"] if firefox_theme else []
                            )
                            tree = build_config_tree(
                                payload, password_hash="$6$test$hash"
                            )
                            gnome = tree["desktops"]["gnome"]
                            self.assertEqual(gnome["defaultDarkMode"], dark)
                            self.assertEqual(gnome["defaultAccentColor"], "grey")
                            self.assertEqual(
                                "firefox-theming" in gnome.get("tweaks", {}),
                                firefox_theme,
                            )
                            self.assertTrue(
                                tree["system"]["packages"]["apps"]["browsers"][
                                    "firefox"
                                ]
                            )
                            modules = gnome["extensions"]
                            clock = modules["customize-clock-on-lockscreen"]
                            self.assertEqual(clock["enable"], branding and enabled)
                            self.assertEqual(
                                "theme" in modules["user-themes"], branding and enabled
                            )
                            if branding and enabled:
                                self.assertEqual(
                                    modules["user-themes"]["name"], "ClockOverride"
                                )
                                self.assertIn(
                                    "font-family: 'Zero'",
                                    modules["user-themes"]["theme"]["cssOverride"],
                                )
                                self.assertFalse(clock["command"]["enable"])
                                self.assertEqual(clock["time"]["text"], "%H\n%M")
                                self.assertEqual(
                                    clock["time"]["font"],
                                    {
                                        "family": "Zero Mono Thin",
                                        "size": 96,
                                        "weight": "Thin",
                                        "color": "rgba(255, 255, 255, 1.0)",
                                    },
                                )
                                self.assertEqual(clock["date"]["text"], "%d.%m.%Y")
                                self.assertEqual(
                                    clock["date"]["font"],
                                    {
                                        "family": "Zero",
                                        "size": 24,
                                        "color": "rgba(255, 255, 255, 1.0)",
                                    },
                                )
                            profiles = tree["legacy"]["programs"]["dconf"]["profiles"]
                            settings = profiles["user"]["databases"][0]["settings"]
                            self.assertEqual("gdm" in profiles, branding)
                            self.assertEqual(
                                "org/gnome/desktop/background" in settings, branding
                            )
                            self.assertNotIn(
                                "org/gnome/shell/extensions/", serialize_zcfg(tree)
                            )
                            if branding:
                                self.assertEqual(
                                    settings["org/gnome/desktop/interface"][
                                        "gtk-theme"
                                    ],
                                    "adw-gtk3-dark" if dark else "adw-gtk3",
                                )
                                wallpaper = settings["org/gnome/desktop/background"][
                                    "picture-uri"
                                ]
                                self.assertEqual(
                                    wallpaper,
                                    PackageFile(
                                        PkgsRef(
                                            ("theming", "wallpapers", "destination-2")
                                        ),
                                        f"/share/backgrounds/destination-2/slate{' dark' if dark else ''}.png",
                                        True,
                                    ),
                                )
                                gdm = profiles["gdm"]["databases"][0]["settings"]
                                self.assertFalse(
                                    gdm["org/gnome/login-screen"]["disable-user-list"]
                                )
                                self.assertEqual(
                                    gdm["org/gnome/login-screen"]["logo"],
                                    PackageFile(
                                        PkgsRef(("theming", "icons", "zenos-icons")),
                                        "/share/icons/hicolor/scalable/apps/zenos.svg",
                                    ),
                                )
                                self.assertTrue(
                                    gdm["org/gnome/desktop/lockdown"][
                                        "disable-lock-screen"
                                    ]
                                )
                                self.assertEqual(
                                    gdm["org/gnome/desktop/session"]["idle-delay"],
                                    GVariant("uint32", 0),
                                )
                                self.assertEqual(
                                    gdm["org/gnome/desktop/interface"]["color-scheme"],
                                    "prefer-dark" if dark else "prefer-light",
                                )
                            else:
                                self.assertNotIn("theming", tree["system"]["packages"])

    def test_other_desktops_do_not_emit_gnome_extension_modules(self):
        for desktop in ("none", "kde", "xfce", "cinnamon", "budgie", "mate"):
            with self.subTest(desktop=desktop):
                tree = build_config_tree(
                    {
                        "pages": [
                            {
                                "id": "desktop",
                                "install_de": desktop != "none",
                                "desktop_environment": desktop,
                                "gnome_options": {
                                    "theme": True,
                                    "extensions": True,
                                    "tiling": True,
                                },
                            }
                        ]
                    }
                )
                self.assertEqual(tree["desktops"]["gnome"], {"enable": False})
                if desktop == "none":
                    self.assertFalse(tree["system"]["zenfs"]["apps"]["enable"])

    def test_final_display_manager_matches_desktop(self):
        expected = {
            "kde": ("services", "displayManager", "plasma-login-manager"),
            "xfce": ("services", "xserver", "displayManager", "lightdm"),
            "cinnamon": ("services", "xserver", "displayManager", "lightdm"),
            "budgie": ("services", "xserver", "displayManager", "lightdm"),
            "mate": ("services", "xserver", "displayManager", "lightdm"),
        }
        gnome = build_config_tree({"pages": [{"id": "desktop", "install_de": True, "desktop_environment": "gnome"}]})
        self.assertNotIn("displayManager", gnome["legacy"].get("services", {}))
        for desktop, path in expected.items():
            with self.subTest(desktop=desktop):
                tree = build_config_tree({"pages": [{
                    "id": "desktop",
                    "install_de": True,
                    "desktop_environment": desktop,
                    "gnome_options": {"theme": False, "extensions": False, "tiling": False},
                }]})
                value = tree["legacy"]
                for part in path:
                    value = value[part]
                self.assertEqual(value, {"enable": True})
                if desktop == "kde":
                    self.assertFalse(tree["legacy"]["services"]["displayManager"]["sddm"]["enable"])

    def test_unknown_shortcut_presets_are_rejected(self):
        for option, value in (("directions", "unknown"), ("actions", "unknown")):
            payload = copy.deepcopy(FULL_PAYLOAD)
            next(page for page in payload["pages"] if page["id"] == "shortcuts")[
                option
            ] = value
            with self.assertRaisesRegex(ValueError, "unsupported shortcut"):
                build_config_tree(payload, password_hash="$6$test$hash")

    def test_multiple_keyboards_preserve_variant_positions(self):
        payload = {
            "pages": [
                {
                    "id": "keyboard",
                    "keyboard": [
                        {"layout": "us", "variant": "", "model": "pc105"},
                        {"layout": "pl", "variant": "dvorak", "model": "pc105"},
                    ],
                }
            ]
        }
        xkb = build_config_tree(payload)["legacy"]["services"]["xserver"]["xkb"]
        self.assertEqual(
            xkb, {"layout": "us,pl", "variant": ",dvorak", "model": "pc105"}
        )

    def test_no_desktop_explicitly_disables_gnome(self):
        tree = build_config_tree({"pages": [{"id": "desktop", "install_de": False}]})
        self.assertFalse(tree["desktops"]["gnome"]["enable"])

    def test_full_package_paths(self):
        tree = build_config_tree(
            {
                "pages": [
                    {
                        "id": "software",
                        "apps": [
                            {"app": "resources", "enabled": True},
                            {"app": "vscode", "enabled": True},
                            {"app": "steam", "enabled": False},
                        ],
                    }
                ]
            }
        )
        self.assertEqual(
            tree["system"]["packages"]["apps"],
            {
                "utilities": {"resources": True},
                "development": {"vscode": True},
            },
        )

    def test_quoted_filesystem_keys(self):
        self.assertIn(
            '"/boot" = {',
            serialize_zcfg({"legacy": {"fileSystems": {"/boot": {"fsType": "vfat"}}}}),
        )


if __name__ == "__main__":
    unittest.main()
