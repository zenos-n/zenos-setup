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
            "gnome_options": {"theme": True, "extensions": True, "tiling": False},
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


class BuilderTests(unittest.TestCase):
    def test_full_payload_maps_to_declarative_config(self):
        tree = build_config_tree(FULL_PAYLOAD, password_hash="$6$test$hash")

        self.assertEqual(tree["system"]["localization"]["locale"], "pl_PL.UTF-8")
        self.assertEqual(tree["system"]["localization"]["timeZone"], "Europe/Warsaw")
        self.assertEqual(tree["system"]["network"]["hostName"], "zen-box")
        self.assertTrue(tree["desktops"]["gnome"]["enable"])
        self.assertTrue(tree["gnomeProfile"]["enable"])
        self.assertTrue(tree["gnomeProfile"]["enableBranding"])
        self.assertTrue(tree["gnomeProfile"]["enableExtensions"])
        self.assertEqual(tree["gnomeProfile"]["directionKeys"], "standard")
        self.assertEqual(tree["gnomeProfile"]["actionKeys"], "traditional")
        self.assertEqual(tree["system"]["release"]["stateVersion"], "26.05")
        self.assertEqual(
            tree["system"]["software"]["packages"],
            [PkgsRef(("catalog", "firefox"))],
        )
        self.assertTrue(tree["legacy"]["users"]["users"]["zen"]["isNormalUser"])
        self.assertEqual(tree["legacy"]["users"]["users"]["zen"]["uid"], 1000)
        self.assertTrue(tree["legacy"]["programs"]["firefox"]["enable"])
        self.assertNotIn("disks", tree)

    def test_output_is_deterministic_and_never_contains_plaintext_password(self):
        first = process_installer_payload(FULL_PAYLOAD, password_hash="$6$test$hash")
        second = process_installer_payload(FULL_PAYLOAD, password_hash="$6$test$hash")

        self.assertEqual(first, second)
        self.assertNotIn("not-written-to-config", first)
        self.assertIn('initialHashedPassword = "$6$test$hash";', first)
        self.assertIn("legacy = {", first)
        self.assertIn("$pkgs.catalog.firefox", first)
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
                "users.zcfg",
            },
        )
        self.assertIn("import ./apps.zcfg;", documents["host.zcfg"])
        self.assertIn("legacy = {", documents["users.zcfg"])
        self.assertIn("zenfs = {", documents["users.zcfg"])
        self.assertIn("software = {", documents["apps.zcfg"])

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
        self.assertEqual(
            tree["system"]["software"]["packages"],
            [PkgsRef(("catalog", "firefox"))],
        )

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
            [PkgsRef(("catalog", "nautilus"))],
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


if __name__ == "__main__":
    unittest.main()
