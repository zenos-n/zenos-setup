from gi.repository import Adw, Gtk, GObject, Gio, Gdk
import os

@Gtk.Template(resource_path='/com/negzero/zenos/setup/views/theme/layout.ui')
class Page(Adw.Bin):
    __gtype_name__ = 'ZenOSTheme'

    btn_default = Gtk.Template.Child()
    btn_dark = Gtk.Template.Child()

    default_image = Gtk.Template.Child()
    dark_image = Gtk.Template.Child()

    accent_blue = Gtk.Template.Child()
    accent_teal = Gtk.Template.Child()
    accent_green = Gtk.Template.Child()
    accent_yellow = Gtk.Template.Child()
    accent_orange = Gtk.Template.Child()
    accent_red = Gtk.Template.Child()
    accent_pink = Gtk.Template.Child()
    accent_purple = Gtk.Template.Child()
    accent_slate = Gtk.Template.Child()

    MANIFEST = {
        "gated": False,
        "unclosable": False
    }

    def __init__(self, router, **kwargs):
        super().__init__(**kwargs)
        self.router = router

        self.state = {
            "dark_mode": True,
            "accent": "purple",
            "is_gnome": True
        }

        # get the base path from the environment variable or fallback to a sensible default
        self.base_wp_path = os.getenv("ZENOS_WALLPAPER_PATH", "/usr/share/backgrounds/zenos/")

        self.wallpaper_map = {
            "blue": "blue.png",
            "teal": "teal.png",
            "green": "green.png",
            "yellow": "yellow.png",
            "orange": "orange.png",
            "red": "red.png",
            "pink": "pink.png",
            "purple": "purple.png",
            "slate": "slate.png"
        }

        self._setup_view()
        self._connect_signals()

    def _setup_view(self):
        self.btn_dark.set_active(True)
        self.accent_purple.set_active(True)
        self._load_current_wallpaper()

    def _load_current_wallpaper(self):
        settings = Gio.Settings.new("org.gnome.desktop.background")

        wallpaper_path = settings.get_string("picture-uri")
        if wallpaper_path:
            self.default_image.set_file(Gio.File.new_for_uri(wallpaper_path))

        dark_wallpaper_path = settings.get_string("picture-uri-dark") or wallpaper_path
        if dark_wallpaper_path:
            self.dark_image.set_file(Gio.File.new_for_uri(dark_wallpaper_path))

    def _connect_signals(self):
        self.btn_default.connect("toggled", self._on_mode_toggled, False)
        self.btn_dark.connect("toggled", self._on_mode_toggled, True)

        accents = {
            self.accent_blue: "blue",
            self.accent_teal: "teal",
            self.accent_green: "green",
            self.accent_yellow: "yellow",
            self.accent_orange: "orange",
            self.accent_red: "red",
            self.accent_pink: "pink",
            self.accent_purple: "purple",
            self.accent_slate: "slate"
        }

        for btn, name in accents.items():
            btn.connect("toggled", self._on_accent_toggled, name)

    def _on_mode_toggled(self, btn, is_dark):
        if btn.get_active():
            self.state["dark_mode"] = is_dark

            style_manager = Adw.StyleManager.get_default()
            style_manager.set_color_scheme(
                Adw.ColorScheme.PREFER_DARK if is_dark else Adw.ColorScheme.PREFER_LIGHT
            )

            try:
                settings = Gio.Settings.new("org.gnome.desktop.interface")
                settings.set_string("color-scheme", "prefer-dark" if is_dark else "default")
            except Exception:
                pass

    def _on_accent_toggled(self, btn, name):
        if not btn.get_active():
            return

        self.state["accent"] = name

        try:
            settings = Gio.Settings.new("org.gnome.desktop.interface")
            settings.set_string("accent-color", name)
        except Exception:
            pass

        self._apply_wallpaper(name)
        self._apply_app_accent(name)

    def _apply_wallpaper(self, accent_name):
        filename = self.wallpaper_map.get(accent_name)
        if not filename:
            return

        # build the absolute path using the env var
        full_path = os.path.join(self.base_wp_path, filename)
        wp_uri = f"file://{full_path}"

        try:
            bg_settings = Gio.Settings.new("org.gnome.desktop.background")
            bg_settings.set_string("picture-uri", wp_uri)
            bg_settings.set_string("picture-uri-dark", wp_uri)

            # update the preview images in the UI
            file_obj = Gio.File.new_for_path(full_path)
            self.default_image.set_file(file_obj)
            self.dark_image.set_file(file_obj)
        except Exception as e:
            print(f"failed to set wallpaper: {e}")

    def _apply_app_accent(self, name):
        display = Gdk.Display.get_default()

        if hasattr(self, "_accent_provider"):
            Gtk.StyleContext.remove_provider_for_display(
                display,
                self._accent_provider
            )

        self._accent_provider = Gtk.CssProvider()

        hex_colors = {
            "blue": "#3584e4",
            "teal": "#2190a4",
            "green": "#26a269",
            "yellow": "#e5a50a",
            "orange": "#c64600",
            "red": "#e01b24",
            "pink": "#d63384",
            "purple": "#9141ac",
            "slate": "#6c7a89"
        }

        color = hex_colors.get(name, "#3584e4")

        css = f"""
        @define-color accent_color {color};
        @define-color accent_bg_color {color};
        """
        self._accent_provider.load_from_data(css.encode('utf-8'))

        Gtk.StyleContext.add_provider_for_display(
            display,
            self._accent_provider,
            Gtk.STYLE_PROVIDER_PRIORITY_USER
        )

    def get_finals(self):
        return dict(self.state)
