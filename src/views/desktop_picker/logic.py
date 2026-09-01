import json
from pathlib import Path

from gi.repository import Adw, Gdk, Gio, GLib, Gtk, GObject


def load_extension_manifest():
    try:
        data = Gio.resources_lookup_data(
            "/com/negzero/zenos/setup/assets/gnome-extensions.json",
            Gio.ResourceLookupFlags.NONE,
        )
        return json.loads(data.get_data().decode("utf-8"))
    except GLib.Error:
        path = Path(__file__).parents[3] / "data/gnome-extensions.json"
        return json.loads(path.read_text(encoding="utf-8"))

@Gtk.Template(resource_path='/com/negzero/zenos/setup/views/desktop_picker/layout.ui')
class Page(Adw.Bin):
    __gtype_name__ = 'DesktopPicker'

    # main toggle
    switch_install_de = Gtk.Template.Child()

    # radio buttons
    radio_gnome = Gtk.Template.Child()
    radio_kde = Gtk.Template.Child()
    radio_xfce = Gtk.Template.Child()
    radio_cinnamon = Gtk.Template.Child()
    radio_budgie = Gtk.Template.Child()
    radio_mate = Gtk.Template.Child()
    radio_ii = Gtk.Template.Child()

    # gnome sub-options
    gnome_theme_switch = Gtk.Template.Child()
    gnome_ext_switch = Gtk.Template.Child()
    gnome_tile_switch = Gtk.Template.Child()
    gnome_ext_more_btn = Gtk.Template.Child()

    # kde sub-options
    kde_theme_switch = Gtk.Template.Child()

    MANIFEST = {
        "unclosable": False,
        "gated": False  # user can just click next, no validation needed
    }

    def __init__(self, router, **kwargs):
        super().__init__(**kwargs)
        self.router = router
        self._extensions_window = None
        self._extension_manifest = load_extension_manifest()
        self._selected_extension_ids = {
            extension["id"]
            for extension in self._extension_manifest
            if extension["recommended"]
        }
        self.gnome_ext_more_btn.connect("clicked", self._show_recommended_extensions)

    def _show_recommended_extensions(self, _button):
        window = Adw.Window(
            title="GNOME Extensions",
            transient_for=self.get_root(),
            modal=True,
            default_width=560,
            default_height=620,
        )
        toolbar = Adw.ToolbarView()
        toolbar.add_top_bar(Adw.HeaderBar())
        page = Adw.PreferencesPage()
        group = Adw.PreferencesGroup(
            title="Installation Media Set",
            description="Extensions available in the ZenOS live and installed GNOME profiles.",
        )
        for extension in self._extension_manifest:
            row = Adw.ActionRow(
                title=extension["name"],
                subtitle=extension["description"],
            )
            switch = Gtk.Switch(
                active=extension["id"] in self._selected_extension_ids,
                valign=Gtk.Align.CENTER,
            )
            switch.connect("notify::active", self._on_extension_toggled, extension["id"])
            row.add_suffix(switch)
            row.set_activatable_widget(switch)
            group.add(row)
        page.add(group)
        scroll = Gtk.ScrolledWindow(child=page, hscrollbar_policy=Gtk.PolicyType.NEVER)
        toolbar.set_content(scroll)
        window.set_content(toolbar)
        window.connect("close-request", self._clear_extensions_window)
        self._extensions_window = window
        window.present()

    def _on_extension_toggled(self, switch, _pspec, extension_id):
        if switch.get_active():
            self._selected_extension_ids.add(extension_id)
        else:
            self._selected_extension_ids.discard(extension_id)

    def _clear_extensions_window(self, _window):
        self._extensions_window = None
        return False

    @property
    def state(self):
        install_de = self.switch_install_de.get_active()

        selected_de = "none"
        if install_de:
            if self.radio_gnome.get_active(): selected_de = "gnome"
            elif self.radio_kde.get_active(): selected_de = "kde"
            elif self.radio_xfce.get_active(): selected_de = "xfce"
            elif self.radio_cinnamon.get_active(): selected_de = "cinnamon"
            elif self.radio_budgie.get_active(): selected_de = "budgie"
            elif self.radio_mate.get_active(): selected_de = "mate"
            elif self.radio_ii.get_active(): selected_de = "ii"

        return {
            "install_de": install_de,
            "desktop_environment": selected_de,
            # router in window.py specifically looks for this key to show the theme page
            "is_gnome": install_de and selected_de == "gnome",

            "gnome_options": {
                "theme": self.gnome_theme_switch.get_active(),
                "extensions": self.gnome_ext_switch.get_active(),
                "extension_ids": sorted(self._selected_extension_ids),
                "tiling": self.gnome_tile_switch.get_active(),
            } if selected_de == "gnome" else {}
        }

    def get_finals(self):
        return self.state
