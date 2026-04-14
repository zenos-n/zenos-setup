import importlib
import threading
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
            "disks": {"view": "disks", "routes": {"path_choice": "path_choice" }},
            "path_choice": {
                "view": "path_choice",
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
            "oobe_welcome": {"view": "oobe_welcome", "routes": {"start": "computer_name"}},
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
        self.pending_step_id = None
        self.history = []

        self.loaded_pages = {}
        self.carousel_steps = []
        self.step_bins = {} # maps step_id -> Adw.Bin dummy wrapper

        display = Gdk.Display.get_default()
        if display:
            icon_theme = Gtk.IconTheme.get_for_display(display)
            icon_theme.add_resource_path("/com/negzero/zenos/icons")

        self.btn_back.connect("clicked", lambda _: self.navigate_back())
        self.btn_next.connect("clicked", lambda _: self.navigate_next("next"))
        self.carousel.connect("page-changed", self._on_carousel_page_changed)

        # bootstrap the very first path into existence
        start_step = FLOWS[self.active_flow_id]["start"]
        self._populate_path_placeholders(start_step)

        # force synchronous load for the very first page so we don't start on a blank screen
        self._ensure_step_loaded(start_step)
        
        self.current_step_id = start_step
        step_config = FLOWS[self.active_flow_id]["steps"].get(start_step)
        self._apply_navigation_effects(step_config["view"])

        # speculative load forks on idle frames
        self._speculative_load_forks(start_step)

    def set_next_enabled(self, enabled: bool, caller=None):
        if caller == "router":
            self.btn_next.set_sensitive(enabled)
            return

        current_node = FLOWS[self.active_flow_id]["steps"].get(self.current_step_id, {})
        current_view_name = current_node.get("view", "")
        current_page_widget = self.loaded_pages.get(current_view_name)

        if caller != current_page_widget:
            return

        self.btn_next.set_sensitive(enabled)

    def _get_path_segment(self, start_step_id):
        # walks down the flow until it hits a fork (>1 routes) or a dead end (0 routes)
        segment = [start_step_id]
        current = start_step_id
        while True:
            routes = FLOWS[self.active_flow_id]["steps"][current].get("routes", {})
            if len(routes) == 1:
                next_step = list(routes.values())[0]
                segment.append(next_step)
                current = next_step
            else:
                break
        return segment

    def _populate_path_placeholders(self, start_step_id):
        segment = self._get_path_segment(start_step_id)
        for step_id in segment:
            if step_id not in self.carousel_steps:
                dummy_bin = Adw.Bin()
                dummy_bin.set_hexpand(True)
                dummy_bin.set_vexpand(True)

                self.step_bins[step_id] = dummy_bin
                self.carousel.append(dummy_bin)
                self.carousel_steps.append(step_id)

    def _ensure_step_loaded(self, step_id, callback=None):
        view_name = FLOWS[self.active_flow_id]["steps"][step_id]["view"]

        if view_name in self.loaded_pages:
            self._attach_to_bin(step_id)
            if callback: callback()
            return self.loaded_pages[view_name]

        def _bg_load():
            try:
                # the actual import is the slow part
                mod = importlib.import_module(f".views.{view_name}.logic", package=__package__)
                GLib.idle_add(_fg_init, mod)
            except Exception as e:
                print(f"[-] failed to load '{view_name}': {e}")
                if callback: GLib.idle_add(callback)

        def _fg_init(mod):
            widget = mod.Page(router=self)
            widget.set_hexpand(True)
            widget.set_vexpand(True)
            self.loaded_pages[view_name] = widget
            self._attach_to_bin(step_id)
            if callback: callback()

        # offload the import war crime to a thread
        threading.Thread(target=_bg_load, daemon=True).start()

    def _attach_to_bin(self, step_id):
        view_name = FLOWS[self.active_flow_id]["steps"][step_id]["view"]
        real_widget = self.loaded_pages.get(view_name)
        target_bin = self.step_bins.get(step_id)

        if target_bin and real_widget and real_widget.get_parent() != target_bin:
            if real_widget.get_parent():
                real_widget.get_parent().set_child(None)
            target_bin.set_child(real_widget)

    def _speculative_load_forks(self, step_id):
        routes = FLOWS[self.active_flow_id]["steps"][step_id].get("routes", {})
        for next_step_id in routes.values():
            self._ensure_step_loaded(next_step_id)

    def _unload_forward_paths(self, from_step_id):
        try:
            idx = self.carousel_steps.index(from_step_id)
        except ValueError:
            return

        dead_steps = self.carousel_steps[idx+1:]
        if not dead_steps:
            return

        print(f"[-] unloading dead path placeholders & ram: {dead_steps}")
        self.carousel_steps = self.carousel_steps[:idx+1]

        for step_id in dead_steps:
            dummy_bin = self.step_bins.pop(step_id, None)
            if dummy_bin:
                self.carousel.remove(dummy_bin)

            view_name = FLOWS[self.active_flow_id]["steps"][step_id]["view"]
            if view_name in self.loaded_pages:
                del self.loaded_pages[view_name]

    def _on_carousel_page_changed(self, carousel, index):
        if self.pending_step_id:
            self.current_step_id = self.pending_step_id
            self.pending_step_id = None
            
            step_config = FLOWS[self.active_flow_id]["steps"].get(self.current_step_id)
            view_name = step_config["view"]

            routes = step_config.get("routes", {})
            if len(routes) != 1:
                self._unload_forward_paths(self.current_step_id)

            self._speculative_load_forks(self.current_step_id)
            self._apply_navigation_effects(view_name)

    def _apply_navigation_effects(self, view_name):
        is_welcome = "welcome" in view_name or "boot" in view_name
        page_count = self.carousel.get_n_pages()
        self.carousel_indicator_dots.set_visible(not is_welcome and page_count >= 3)

        target_page = self.loaded_pages.get(view_name)
        if not target_page:
            return

        manifest = getattr(target_page, "MANIFEST", {})
        
        # toggle the close button/alt+f4 availability
        is_unclosable = manifest.get("unclosable", False)
        self.set_deletable(not is_unclosable)

        # burn the bridges if it's a progress page
        if "progress" in view_name:
            self.history = [] # clear back-button history

            # nuke everything in the carousel behind us
            try:
                current_idx = self.carousel_steps.index(self.current_step_id)
                if current_idx > 0:
                    to_purge = self.carousel_steps[:current_idx]
                    self.carousel_steps = self.carousel_steps[current_idx:]
                    for step_id in to_purge:
                        bin_widget = self.step_bins.pop(step_id, None)
                        if bin_widget:
                            self.carousel.remove(bin_widget)
                    print(f"[-] point of no return reached: purged {len(to_purge)} steps")
            except ValueError:
                pass

        self.set_next_enabled(not manifest.get("gated", False), caller="router")

        # back button should now naturally hide because history is empty
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

        if not is_back and self.current_step_id:
            self.history.append(self.current_step_id)

        self.pending_step_id = step_id

        if step_id not in self.carousel_steps:
            self._populate_path_placeholders(step_id)

        # ensure loaded before scrolling
        self._ensure_step_loaded(step_id, lambda: GLib.timeout_add(50, self._do_scroll, step_id))

    def _do_scroll(self, step_id):
        if step_id != self.pending_step_id:
            return False

        target_bin = self.step_bins.get(step_id)
        if target_bin:
            self.carousel.scroll_to(target_bin, True)

        return False

    def navigate_next(self, route_key="next"):
        current_step_config = FLOWS[self.active_flow_id]["steps"].get(self.current_step_id, {})
        next_step_id = current_step_config.get("routes", {}).get(route_key)
        if next_step_id:
            self.navigate_to_step(next_step_id)

    def navigate_back(self):
        if self.history:
            prev_step_id = self.history.pop()
            self.navigate_to_step(prev_step_id, is_back=True)
