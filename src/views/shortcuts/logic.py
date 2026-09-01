from gi.repository import Adw, Gtk


@Gtk.Template(resource_path="/com/negzero/zenos/setup/views/shortcuts/layout.ui")
class Page(Adw.Bin):
    __gtype_name__ = "ZenOSShortcutPreferences"

    directions_standard = Gtk.Template.Child()
    directions_vim = Gtk.Template.Child()
    actions_zenos = Gtk.Template.Child()
    actions_traditional = Gtk.Template.Child()

    MANIFEST = {
        "gated": False,
        "unclosable": False,
    }

    def __init__(self, router, **kwargs):
        super().__init__(**kwargs)
        self.router = router

    def get_finals(self):
        return {
            "directions": "vim" if self.directions_vim.get_active() else "standard",
            "actions": "zenos" if self.actions_zenos.get_active() else "traditional",
        }
