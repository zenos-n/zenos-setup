import importlib
from gi.repository import Adw, Gtk, GObject, GLib

FLOW_MAP = {
    "oobe_welcome": {
        "start": "language"
    },
    "language": {
        "next": "timezone"
    },
    "installer_welcome": {
        "install": "language",
        "recovery": "recovery_mode"
    },
    "timezone": {
        "next": "keyboard"
    }
}

@Gtk.Template(resource_path='/com/negzero/zenos/setup/window.ui')
class ZenosSetupWindow(Adw.ApplicationWindow):
    __gtype_name__ = 'ZenosSetupWindow'

    carousel = Gtk.Template.Child()
    btn_back = Gtk.Template.Child()
    btn_next = Gtk.Template.Child()

    def __init__(self, start_in_oobe=False, **kwargs):
        super().__init__(**kwargs)

        self.current_page_key = None
        self.history = []
        self.loaded_pages = {}

        # Connect signals
        self.btn_back.connect("clicked", lambda _: self.navigate_back())
        self.btn_next.connect("clicked", lambda _: self.navigate_next())

        # Start initial navigation
        start_page = "oobe_welcome" if start_in_oobe else "installer_welcome"
        self.navigate_to(start_page)

    def _apply_navigation_effects(self, page_key):
        """Internal helper to handle all UI changes when the page changes"""
        self.current_page_key = page_key

        # Scroll the carousel
        self.carousel.scroll_to(self.loaded_pages[page_key], True)

        # Update Back Button: Hide if "welcome" is in the name
        should_show_back = "welcome" not in page_key and len(self.history) > 0

        if should_show_back:
            if not self.btn_back.get_visible():
                self.btn_back.set_visible(True)
                self.animate_spring(self.btn_back)
        else:
            self.btn_back.set_visible(False)

        # Update Next Button: Show if linear 'next' exists in FLOW_MAP
        current_node = FLOW_MAP.get(page_key, {})
        has_next = "next" in current_node

        if has_next:
            if not self.btn_next.get_visible():
                self.btn_next.set_visible(True)
                self.animate_spring(self.btn_next)
        else:
            self.btn_next.set_visible(False)

    def animate_spring(self, widget):
        """Spring animation with clamping to prevent opacity overflow"""
        # use a callback to clamp the value between 0.0 and 1.0
        target = Adw.CallbackAnimationTarget.new(
            lambda value, _: widget.set_opacity(max(0.0, min(1.0, value))),
            None
        )
        params = Adw.SpringParams.new(0.50, 1.0, 100.0)
        animation = Adw.SpringAnimation.new(widget, 0.0, 1.0, params, target)
        animation.play()

    def navigate_to(self, page_key):
        if page_key == self.current_page_key:
            return

        is_new = page_key not in self.loaded_pages

        if is_new:
            try:
                mod = importlib.import_module(f".views.{page_key}.logic", package=__package__)
                new_page = mod.Page(router=self)
                self.loaded_pages[page_key] = new_page
                self.carousel.append(new_page)
                # force a show so it's ready for layout
                new_page.show()
            except Exception as e:
                print(f"fatal router error loading '{page_key}': {e}")
                return

        if self.current_page_key:
            self.history.append(self.current_page_key)

        # if it's a new page, 50ms is the sweet spot for the carousel to wake up
        if is_new:
            GLib.timeout_add(50, self._apply_navigation_effects, page_key)
        else:
            self._apply_navigation_effects(page_key)

    def navigate_next(self, branch="next"):
        current_node = FLOW_MAP.get(self.current_page_key, {})
        next_key = current_node.get(branch)

        if next_key:
            self.navigate_to(next_key)
        else:
            print(f"router dead end: nowhere to go from '{self.current_page_key}' via '{branch}'")

    def navigate_back(self):
        if not self.history:
            return

        prev_key = self.history.pop()
        self._apply_navigation_effects(prev_key)
