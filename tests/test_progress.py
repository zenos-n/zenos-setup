import unittest
import json
from pathlib import Path
from xml.etree import ElementTree

from src.views.progress import next_tour_index


class ProgressTourTests(unittest.TestCase):
    def test_tour_advances_and_wraps(self):
        self.assertEqual(next_tour_index(0.0, 3), 1)
        self.assertEqual(next_tour_index(1.0, 3), 2)
        self.assertEqual(next_tour_index(2.0, 3), 0)
        self.assertEqual(next_tour_index(0.8, 3), 2)

    def test_tour_ignores_zero_or_one_page(self):
        self.assertIsNone(next_tour_index(0.0, 0))
        self.assertIsNone(next_tour_index(0.0, 1))

    def test_layout_bundles_three_distinct_slides(self):
        layout = Path(__file__).parents[1] / "src/views/progress/layout.ui"
        root = ElementTree.parse(layout).getroot()
        carousel = root.find(".//object[@id='carousel_tour']")

        self.assertIsNotNone(carousel)
        pages = carousel.findall("./child/object")
        self.assertEqual(len(pages), 3)

        images = [
            page.find(".//object[@class='GtkPicture']/property[@name='file']").text
            for page in pages
        ]
        self.assertEqual(len(set(images)), 3)
        self.assertTrue(
            all(
                image.startswith("resource:///com/negzero/zenos/setup/assets/")
                for image in images
            )
        )

    def test_progress_hides_next_while_gated(self):
        logic = Path(__file__).parents[1] / "src/views/progress/logic.py"
        source = logic.read_text(encoding="utf-8")
        self.assertIn('"hide_next_while_gated": True', source)
        self.assertIn("self.live_mode_button.set_visible(True)", source)

    def test_extension_manifest_and_default_apps(self):
        project = Path(__file__).parents[1]
        extensions = json.loads(
            (project / "data/gnome-extensions.json").read_text(encoding="utf-8")
        )
        apps = json.loads(
            (project / "src/views/extra_software/apps.json").read_text(encoding="utf-8")
        )
        self.assertGreaterEqual(len(extensions), 15)
        self.assertTrue(any(item["id"] == "forge" for item in extensions))
        self.assertTrue(apps["browsers"]["apps"][0]["default"])
        resources = next(app for app in apps["utilities"]["apps"] if app["id"] == "resources")
        self.assertTrue(resources["default"])
        for desktop in ("gnome", "kde", "xfce", "cinnamon", "budgie", "mate"):
            self.assertTrue(apps[f"core-{desktop}"]["includedByDesktop"])

        upstream_gnome_apps = {
            "baobab", "decibels", "epiphany", "gnome-text-editor",
            "gnome-calculator", "gnome-calendar", "gnome-characters",
            "gnome-clocks", "gnome-console", "gnome-contacts",
            "gnome-font-viewer", "gnome-logs", "gnome-maps", "gnome-music",
            "gnome-system-monitor", "gnome-tecla", "gnome-weather", "loupe",
            "nautilus", "papers", "gnome-connections", "showtime",
            "simple-scan", "snapshot", "yelp", "gnome-disk-utility",
            "seahorse", "sushi",
        }
        configured_gnome_apps = {
            app["id"] for app in apps["core-gnome"]["apps"]
        }
        self.assertTrue(upstream_gnome_apps <= configured_gnome_apps)
        self.assertFalse(upstream_gnome_apps & {
            app["id"] for app in apps["browsers"]["apps"]
        })


if __name__ == "__main__":
    unittest.main()
