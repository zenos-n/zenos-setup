import importlib
from gi.repository import Adw, Gtk, GObject, GLib

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
        self.history = []
        self.loaded_pages = {}

        self.btn_back.connect("clicked", lambda _: self.navigate_back())
        self.btn_next.connect("clicked", lambda _: self.navigate_next("next"))

        self.preload_all_views()

        # jump right in
        start_step = FLOWS[self.active_flow_id]["start"]
        self.navigate_to_step(start_step)

    def preload_all_views(self):
        """cranks through the flow map and loads every view into memory"""
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

    def _apply_navigation_effects(self, view_name):
        """animates the UI widgets when changing pages"""
        self.carousel.scroll_to(self.loaded_pages[view_name], True)

        is_welcome = "welcome" in view_name or "boot" in view_name

        page_count = self.carousel.get_n_pages()

        self.carousel_indicator_dots.set_visible(not is_welcome and page_count >= 3)

        should_show_back = not is_welcome and len(self.history) > 0

        if should_show_back:
            if not self.btn_back.get_visible():
                self.btn_back.set_visible(True)
                self.animate_spring(self.btn_back)
        else:
            self.btn_back.set_visible(False)

        current_node = FLOWS[self.active_flow_id]["steps"].get(self.current_step_id, {})
        has_next = "next" in current_node.get("routes", {})

        if has_next:
            if not self.btn_next.get_visible():
                self.btn_next.set_visible(True)
                self.animate_spring(self.btn_next)
        else:
            self.btn_next.set_visible(False)

    def animate_spring(self, widget):
        """bouncy opacity flex"""
        target = Adw.CallbackAnimationTarget.new(
            lambda value, _: widget.set_opacity(max(0.0, min(1.0, value))),
            None
        )
        params = Adw.SpringParams.new(0.50, 1.0, 100.0)
        animation = Adw.SpringAnimation.new(widget, 0.0, 1.0, params, target)
        animation.play()

    def navigate_to_step(self, step_id, is_back=False):
        """the big brain router logic"""
        if step_id == self.current_step_id:
            return

        step_config = FLOWS[self.active_flow_id]["steps"].get(step_id)
        if not step_config:
            print(f"[-] router dead end: step '{step_id}' doesn't exist in flow '{self.active_flow_id}'")
            return

        view_name = step_config["view"]

        if not is_back and self.current_step_id:
            self.history.append(self.current_step_id)

        # prune branches we didn't take ONLY when moving forward.
        # we keep the history views in the carousel so the dots indicator works.
        if not is_back:
            valid_path = self.history + [step_id]
            valid_views = [FLOWS[self.active_flow_id]["steps"][s]["view"] for s in valid_path]

            for k, p in list(self.loaded_pages.items()):
                # if it's in the carousel but NOT in our current valid history path, nuke it
                if p.get_parent() == self.carousel and k not in valid_views:
                    self.carousel.remove(p)

        target_view = self.loaded_pages[view_name]
        just_mounted = False

        if target_view.get_parent() != self.carousel:
            self.carousel.append(target_view)
            just_mounted = True

        self.current_step_id = step_id

        if just_mounted:
            GLib.timeout_add(50, self._apply_navigation_effects, view_name)
        else:
            self._apply_navigation_effects(view_name)

    def navigate_next(self, route_key="next"):
        """looks up what the next step is based on the current step and the route picked"""
        current_step_config = FLOWS[self.active_flow_id]["steps"].get(self.current_step_id, {})
        next_step_id = current_step_config.get("routes", {}).get(route_key)

        if next_step_id:
            self.navigate_to_step(next_step_id)
        else:
            print(f"[-] router dead end: nowhere to go from '{self.current_step_id}' via route '{route_key}'")

    def navigate_back(self):
        if not self.history:
            return

        prev_step_id = self.history.pop()
        # pass is_back=True so we don't accidentally push the current page onto the history stack we just popped
        self.navigate_to_step(prev_step_id, is_back=True)
