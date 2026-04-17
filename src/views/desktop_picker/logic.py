from gi.repository import Adw, Gtk, GObject

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

    # kde sub-options
    kde_theme_switch = Gtk.Template.Child()

    MANIFEST = {
        "unclosable": False,
        "gated": False  # user can just click next, no validation needed
    }

    def __init__(self, router, **kwargs):
        super().__init__(**kwargs)
        self.router = router

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
                "tiling": self.gnome_tile_switch.get_active(),
            } if selected_de == "gnome" else {}
        }
