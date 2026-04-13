import importlib
from gi.repository import Adw, Gtk, GObject, GLib, Gdk

FLOWS = {
    "installer": {
        "start": "installer_welcome",
        "steps": {
            "installer_welcome": {
                "view": "installer_welcome",
                "routes": {"install": "language", "recovery": "recovery_mode"}
            },
            "recovery_mode": {"view": "recovery_mode", "routes": {}},
            "language": {"view": "language", "routes": {"next": "timezone"}},
            "timezone": {"view": "timezone", "routes": {"next": "keyboard"}},
            "keyboard": {"view": "keyboard", "routes": {"next": "internet"}},
            "internet": {"view": "internet", "routes": {"next": "disks"}},
            "disks": {
                "view": "disks",
                "routes": {
                    "install_now": "run_install_script",
                    "finish_setup": "oobe_config_start"
                }
            },
            # path: install now
            "run_install_script": {"view": "progress", "routes": {"next": "reboot_to_oobe"}},
            "reboot_to_oobe": {"view": "reboot", "routes": {}},

            # path: finish setup first
            "oobe_config_start": {"view": "computer_name", "routes": {"next": "user_setup"}},
            "user_setup": {"view": "user_setup", "routes": {"next": "theme"}},
            "theme": {"view": "theme", "routes": {"next": "extra_software"}},
            "extra_software": {"view": "extra_software", "routes": {"next": "run_final_install"}},
            "run_final_install": {"view": "progress", "routes": {"next": "reboot_final"}},
            "reboot_final": {"view": "reboot", "routes": {}}
        }
    },
    "oobe": {
        "start": "oobe_welcome",
        "steps": {
            "oobe_welcome": {"view": "oobe_welcome", "routes": {"next": "computer_name"}},
            "computer_name": {"view": "computer_name", "routes": {"next": "user_setup"}},
            "user_setup": {"view": "user_setup", "routes": {"next": "theme"}},
            "theme": {"view": "theme", "routes": {"next": "extra_software"}},
            "extra_software": {"view": "extra_software", "routes": {"next": "run_rebuild"}},
            "run_rebuild": {"view": "progress", "routes": {"next": "last_reboot"}},
            "last_reboot": {"view": "reboot", "routes": {}}
        }
    }
}

@Gtk.Template(resource_path='/com/negzero/zenos/setup/window.ui')
class ZenosSetupWindow(Adw.ApplicationWindow):
    __gtype_name__ = 'ZenosSetupWindow'

    carousel = Gtk.Template.Child()
    btn_back = Gtk.Template.Child()
    btn_next = Gtk.Template.Child()
    carousel_indicator_dots = Gtk.Template.Child()

    def __init__(self, start_in_oobe=False, **kwargs):
        super().__init__(**kwargs)

        self.active_flow_id = "oobe" if start_in_oobe else "installer"
        self.current_step_id = None
        self.pending_step_id = None # track where we are GOING
        self.history = []
        self.loaded_pages = {}

        display = Gdk.Display.get_default()
        if display:
            icon_theme = Gtk.IconTheme.get_for_display(display)
            icon_theme.add_resource_path("/com/negzero/zenos/icons")

        self.btn_back.connect("clicked", lambda _: self.navigate_back())
        self.btn_next.connect("clicked", lambda _: self.navigate_next("next"))

        # connect to page-changed to update logic ONLY after the animation confirms
        self.carousel.connect("page-changed", self._on_carousel_page_changed)

        self.preload_all_views()

        start_step = FLOWS[self.active_flow_id]["start"]
        self.navigate_to_step(start_step)
        
    def set_next_enabled(self, enabled: bool, caller=None):
        if caller == "router":
            self.btn_next.set_sensitive(enabled)
            return

        # we check against current_step_id because that's the page the user is actually looking at
        current_node = FLOWS[self.active_flow_id]["steps"].get(self.current_step_id, {})
        current_view_name = current_node.get("view", "")
        current_page_widget = self.loaded_pages.get(current_view_name)

        if caller != current_page_widget:
            return

        self.btn_next.set_sensitive(enabled)

    def preload_all_views(self):
        flow_steps = FLOWS[self.active_flow_id]["steps"]
        unique_views = {step_config["view"] for step_config in flow_steps.values()}

        for view_name in unique_views:
            if view_name not in self.loaded_pages:
                try:
                    mod = importlib.import_module(f".views.{view_name}.logic", package=__package__)
                    self.loaded_pages[view_name] = mod.Page(router=self)
                    self.loaded_pages[view_name].show()
                except Exception as e:
                    print(f"[-] failed to preload '{view_name}': {e}")

    def _on_carousel_page_changed(self, carousel, index):
        """
        this triggers after the scroll animation finishes.
        we finally update the logical current_step_id here.
        """
        if self.pending_step_id:
            self.current_step_id = self.pending_step_id
            self.pending_step_id = None
            
            step_config = FLOWS[self.active_flow_id]["steps"].get(self.current_step_id)
            view_name = step_config["view"]
            self._apply_navigation_effects(view_name)

    def _apply_navigation_effects(self, view_name):
        is_welcome = "welcome" in view_name or "boot" in view_name
        page_count = self.carousel.get_n_pages()
        self.carousel_indicator_dots.set_visible(not is_welcome and page_count >= 3)

        target_page = self.loaded_pages[view_name]
        manifest = getattr(target_page, "MANIFEST", {})
        is_gated = manifest.get("gated", False)
        
        self.set_next_enabled(not is_gated, caller="router")

        should_show_back = not is_welcome and len(self.history) > 0
        self.btn_back.set_visible(should_show_back)

        current_node = FLOWS[self.active_flow_id]["steps"].get(self.current_step_id, {})
        has_next = "next" in current_node.get("routes", {})
        self.btn_next.set_visible(has_next)

    def navigate_to_step(self, step_id, is_back=False):
        if step_id == self.current_step_id or step_id == self.pending_step_id:
            return

        step_config = FLOWS[self.active_flow_id]["steps"].get(step_id)
        if not step_config:
            return

        view_name = step_config["view"]

        # handle history before we move
        if not is_back and self.current_step_id:
            self.history.append(self.current_step_id)

        target_view = self.loaded_pages[view_name]
        if target_view.get_parent() != self.carousel:
            self.carousel.append(target_view)

        # we set pending, but current_step_id remains the old one until page-changed fires
        self.pending_step_id = step_id
        
        # trigger the animation
        self.carousel.scroll_to(target_view, True)

    def navigate_next(self, route_key="next"):
        # important: we check routes based on the current step, NOT the pending one
        current_step_config = FLOWS[self.active_flow_id]["steps"].get(self.current_step_id, {})
        next_step_id = current_step_config.get("routes", {}).get(route_key)
        if next_step_id:
            self.navigate_to_step(next_step_id)

    def navigate_back(self):
        if self.history:
            prev_step_id = self.history.pop()
            self.navigate_to_step(prev_step_id, is_back=True)
