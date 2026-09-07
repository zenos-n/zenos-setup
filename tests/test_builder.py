import copy
import json
from pathlib import Path
import unittest

from src.builder import (
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
        self.assertEqual(tree["legacy"]["time"]["timeZone"], "Europe/Warsaw")
        self.assertEqual(tree["legacy"]["networking"]["hostName"], "zen-box")
        self.assertTrue(tree["desktops"]["gnome"]["enable"])
        self.assertFalse(
            tree["legacy"]["programs"]["dconf"]["profiles"]["user"]["databases"][0][
                "settings"
            ]["org/gnome/shell/extensions/forge"]["tiling-mode-enabled"]
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
        self.assertIn("import ./apps.zcfg;", documents["host.zcfg"])
        self.assertIn("import ./users/zen/main.zcfg;", documents["host.zcfg"])
        self.assertIn("legacy = {", documents["users/zen/main.zcfg"])
        self.assertNotIn("zenfs", documents["users/zen/main.zcfg"])
        self.assertIn("firefox = true;", documents["apps.zcfg"])

    def test_execution_plan_owns_disk_and_network_state(self):
        plan = build_execution_plan(FULL_PAYLOAD)

        self.assertEqual(plan["disk"]["mode"], "auto")
        self.assertEqual(plan["disk"]["devices"], ["vda"])
        self.assertEqual(plan["networkStatus"], "connected")

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

    def test_serializer_escapes_interpolation_and_rejects_floats(self):
        source = serialize_zcfg({"networking": {"hostName": "host-${unsafe}"}})
        self.assertIn(r"host-\u0024{unsafe}", source)
        with self.assertRaisesRegex(ValueError, "floating-point"):
            serialize_zcfg({"value": 1.5})

    def test_default_selected_profile_is_fully_rendered(self):
        tree = build_config_tree(default_payload(), password_hash="$6$test$hash")
        gnome = tree["desktops"]["gnome"]
        self.assertIn(
            PkgsRef(("desktops", "gnome", "extensions", "dash-stacks")),
            gnome["extensionPackages"],
        )
        self.assertIn(
            PkgsRef(("desktops", "gnome", "extensions", "forge")),
            gnome["extensionPackages"],
        )
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
            settings["org/gnome/shell/extensions/forge/keybindings"][
                "window-focus-left"
            ],
            ["<Super>h"],
        )
        self.assertTrue(
            settings["org/gnome/shell/extensions/forge"]["tiling-mode-enabled"]
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
                    settings["org/gnome/shell/extensions/forge/keybindings"][
                        "window-focus-left"
                    ],
                    ["<Super>h" if directions == "vim" else "<Super>Left"],
                )

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
