"""Exercise installed GTK defaults under Xvfb, without running the installer."""

from pathlib import Path
import sys
from types import SimpleNamespace

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gio, GLib, Gtk

root = Path(sys.argv[1]) / "share/zenos-setup"
sys.path.insert(0, str(root))
Gio.Resource.load(str(root / "zenos-setup.gresource"))._register()
Adw.init()

from zenos_setup import runner
from zenos_setup.builder import build_config_documents
from zenos_setup.state import InstallState
from zenos_setup.views.desktop_picker.logic import Page as Desktop
from zenos_setup.views.extra_software.logic import Page as Software
from zenos_setup.views.installer_welcome.logic import Page as InstallerWelcome
from zenos_setup.views.keyboard.logic import all_keyboards
from zenos_setup.views.oobe_welcome.logic import Page as OOBEWelcome
from zenos_setup.views.path_choice.logic import Page as PathChoice
from zenos_setup.views.shortcuts.logic import Page as Shortcuts
from zenos_setup.views.theme.logic import Page as Theme

assert runner.DRY_RUN
assert all_keyboards
state = InstallState()
router = SimpleNamespace(
    install_state=state,
    collect_state=lambda: None,
    carousel=Adw.Carousel(),
    carousel_steps=[],
    step_bins={},
)
app_id = "com.negzero.zenos.setup"
desktop_entry = GLib.KeyFile()
desktop_entry.load_from_file(
    str(root.parent / "applications" / f"{app_id}.desktop"), GLib.KeyFileFlags.NONE
)
icons = [("desktop entry", desktop_entry.get_string("Desktop Entry", "Icon"), "zenos")]
for page_type, expected in (
    (InstallerWelcome, "zenos"),
    (OOBEWelcome, "zenos"),
    (PathChoice, "zenos-symbolic"),
):
    page = page_type(router)
    status = page.get_child()
    assert isinstance(status, Adw.StatusPage)
    icons.append((page_type.__gtype_name__, status.get_icon_name(), expected))
icon_theme = Gtk.IconTheme.get_for_display(page.get_display())
for source, icon_name, expected in icons:
    assert icon_name == expected, (source, icon_name)
    assert icon_theme.has_icon(icon_name), (source, icon_name)
    icon = icon_theme.lookup_icon(
        icon_name, None, 128, 1, Gtk.TextDirection.NONE, Gtk.IconLookupFlags(0)
    )
    kind = "symbolic" if icon_name.endswith("-symbolic") else "scalable"
    expected_file = root.parent / "icons/hicolor" / kind / "apps" / f"{icon_name}.svg"
    assert icon.get_file() is not None, (source, icon_name)
    assert icon.get_file().get_path() == str(expected_file), (source, icon.get_file())
    assert expected_file.is_file(), expected_file
print("PASS: installed welcome, OOBE, path-choice, and desktop icons resolve to packaged SVGs")
desktop = Desktop(router)
assert not desktop.radio_ii.get_sensitive()
state.set_page("desktop", desktop.get_finals())
assert state.get_page("desktop")["desktop_environment"] == "gnome"
assert state.get_page("desktop")["gnome_options"]["theme"]
shortcuts = Shortcuts(router)
assert shortcuts.get_finals() == {"directions": "vim", "actions": "zenos"}
state.set_page("shortcuts", shortcuts.get_finals())
theme = Theme(router)
state.set_page("theme", theme.get_finals())
software = Software(router)
software._rebuild_ui()
state.set_page("software", software.get_finals())
documents = build_config_documents(state.to_dict())
assert "dash-stacks" in documents["desktop.zcfg"]
assert "<Super>q" in documents["apps.zcfg"]
assert "adwaita-hacks" in documents["apps.zcfg"]
print("PASS: packaged GTK defaults, GResources, keyboard layouts, and GNOME rendering")
