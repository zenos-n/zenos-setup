import importlib
import threading
from gi.repository import Adw, Gtk, GObject, GLib, Gdk
from .state import InstallState

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
                    "finish_setup": "oobe_config_start",
                    "online": "online_install"
                }
            },
            "online_install": {"view": "online_config", "routes": {"next": "run_install_script"}},
            "oobe_config_start": {"view": "computer_name", "routes": {"next": "user_setup"}},
            "user_setup": {"view": "user_setup", "routes": {"next": "desktop"}},
            "desktop": {
                "view": "desktop_picker",
                "routes": {
                    "next": [
                        {"target": "theme", "condition": "is_gnome"},
                        {"target": "extra_software"}
                    ]
                }
            },
            "theme": {"view": "theme", "routes": {"next": "extra_software"}},
            "extra_software": {"view": "extra_software", "routes": {"next": "run_install_script"}},

            # ACTUALLY DESTRUCTIVE
            "run_install_script": {"view": "progress", "routes": {"next": "reboot_to_oobe"}},
            "reboot_to_oobe": {"view": "reboot", "routes": {}},
        }
    },
    "oobe": {
        "start": "oobe_welcome",
        "steps": {
            "oobe_welcome": {"view": "oobe_welcome", "routes": {"start": "language"}},
            "language": {"view": "language", "routes": {"next": "timezone"}},
            "timezone": {"view": "timezone", "routes": {"next": "keyboard"}},
            "keyboard": {"view": "keyboard", "routes": {"next": "internet"}},
            "internet": {"view": "internet", "routes": {"next": "computer_name"}},
            "computer_name": {"view": "computer_name", "routes": {"next": "user_setup"}},
            "user_setup": {"view": "user_setup", "routes": {"next": "desktop"}},
            "desktop": {
                "view": "desktop_picker",
                "routes": {
                    "next": [
                        {"target": "theme", "condition": "is_gnome"},
                        {"target": "extra_software"}
                    ]
                }
            },
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
        self.flow_history = []

        self.install_state = InstallState(oobe=start_in_oobe)

        self.loaded_pages = {}
        self.carousel_steps = []
        self.step_bins = {}

        display = Gdk.Display.get_default()
        if display:
            icon_theme = Gtk.IconTheme.get_for_display(display)
            icon_theme.add_resource_path("/com/negzero/zenos/icons")

            css_provider = Gtk.CssProvider()
            css_provider.load_from_resource("/com/negzero/zenos/setup/style.css")
            Gtk.StyleContext.add_provider_for_display(
                display,
                css_provider,
                Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
            )

        self.btn_back.connect("clicked", lambda _: self.navigate_back())
        self.btn_next.connect("clicked", lambda _: self.navigate_next("next"))
        self.carousel.connect("page-changed", self._on_carousel_page_changed)

        start_step = FLOWS[self.active_flow_id]["start"]

        self.current_step_id = start_step
        self.flow_history.append(start_step)
        self._populate_path_placeholders(start_step)
        self._ensure_step_loaded(start_step)

        step_config = FLOWS[self.active_flow_id]["steps"].get(start_step)
        self._apply_navigation_effects(step_config["view"])
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
        segment = [start_step_id]
        current = start_step_id
        while True:
            routes = FLOWS[self.active_flow_id]["steps"][current].get("routes", {})
            if len(routes) == 1:
                route_key = list(routes.keys())[0]
                route_data = routes[route_key]

                if isinstance(route_data, list):
                    next_step = None
                    for choice in route_data:
                        if not choice.get("condition") or self._check_condition(choice["condition"]):
                            next_step = choice["target"]
                            break
                else:
                    next_step = route_data

                if next_step and next_step not in segment:
                    segment.append(next_step)
                    current = next_step
                else:
                    break
            else:
                break
        return segment

    def _populate_path_placeholders(self, start_step_id):
        segment = self._get_path_segment(start_step_id)

        # find where we are to inject immediately after
        if self.current_step_id in self.carousel_steps:
            insert_idx = self.carousel_steps.index(self.current_step_id) + 1
        else:
            insert_idx = len(self.carousel_steps)

        for step_id in segment:
            if step_id not in self.carousel_steps:
                dummy_bin = Adw.Bin()
                dummy_bin.set_hexpand(True)
                dummy_bin.set_vexpand(True)

                self.step_bins[step_id] = dummy_bin
                # inject into carousel and tracking list at the calculated position
                self.carousel.insert(dummy_bin, insert_idx)
                self.carousel_steps.insert(insert_idx, step_id)
                insert_idx += 1

    def _ensure_step_loaded(self, step_id, callback=None):
        view_name = FLOWS[self.active_flow_id]["steps"][step_id]["view"]

        if view_name in self.loaded_pages:
            self._attach_to_bin(step_id)
            if callback: callback()
            return self.loaded_pages[view_name]

        def _bg_load():
            try:
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

        targets = []
        for route_val in routes.values():
            if isinstance(route_val, list):
                targets.extend(c["target"] for c in route_val)
            else:
                targets.append(route_val)

        for target in targets:
            view_name = FLOWS[self.active_flow_id]["steps"][target].get("view")
            # prevent instantiating pages that run backend tasks on __init__
            if view_name not in ("progress", "reboot"):
                self._ensure_step_loaded(target)

    def _unload_forward_paths(self, from_step_id):
        try:
            idx = self.carousel_steps.index(from_step_id)
        except ValueError:
            return

        dead_steps = self.carousel_steps[idx+1:]
        if not dead_steps: return

        print(f"[-] unloading dead path: {dead_steps}")
        self.carousel_steps = self.carousel_steps[:idx+1]

        # dynamic slicing for the persistent history if we backtrack and take a new route
        if from_step_id in self.flow_history:
            f_idx = self.flow_history.index(from_step_id)
            self.flow_history = self.flow_history[:f_idx+1]

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

            if self.current_step_id not in self.flow_history:
                self.flow_history.append(self.current_step_id)

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
        if not target_page: return

        manifest = getattr(target_page, "MANIFEST", {})
        self.set_deletable(not manifest.get("unclosable", False))

        if "progress" in view_name:
            self.history = []
            try:
                current_idx = self.carousel_steps.index(self.current_step_id)
                if current_idx > 0:
                    to_purge = self.carousel_steps[:current_idx]
                    self.carousel_steps = self.carousel_steps[current_idx:]
                    for step_id in to_purge:
                        bin_widget = self.step_bins.pop(step_id, None)
                        if bin_widget: self.carousel.remove(bin_widget)
            except ValueError: pass

        self.set_next_enabled(not manifest.get("gated", False), caller="router")
        self.btn_back.set_visible(not is_welcome and len(self.history) > 0)

        current_node = FLOWS[self.active_flow_id]["steps"].get(self.current_step_id, {})
        self.btn_next.set_visible("next" in current_node.get("routes", {}))

    def navigate_to_step(self, step_id, is_back=False, force=False):
        if step_id == self.current_step_id or step_id == self.pending_step_id:
            return

        if step_id == "run_install_script" and not force:
            dialog = Adw.MessageDialog(
                heading="Ready to install?",
                body="This will permanently format the selected disks and install the system. This action cannot be undone. Are you sure you want to continue?",
                transient_for=self
            )

            # shut gtk up about min width/height calculation weirdness
            dialog.set_default_size(450, -1)

            dialog.add_response("cancel", "Cancel")
            dialog.add_response("install", "Install")
            dialog.set_response_appearance("install", Adw.ResponseAppearance.DESTRUCTIVE)

            # pull affected drives from state to show in the dialog
            state = self.collect_state()
            disk_data = state.get_page("disks") or {}

            targets = disk_data.get("disks", ["Unknown Drive"])

            pref_group = Adw.PreferencesGroup(title="Affected Drives")
            for t in targets:
                if not t: continue
                # logic.py saves just the name ('sda'), so we format it nicely
                display_name = f"/dev/{t}" if not str(t).startswith("/") and t != "Unknown Drive" else str(t)
                row = Adw.ActionRow(title=display_name, subtitle="All data will be permanently erased")
                row.add_prefix(Gtk.Image.new_from_icon_name("drive-harddisk-symbolic"))
                pref_group.add(row)

            dialog.set_extra_child(pref_group)

            def on_response(dlg, response):
                if response == "install":
                    self.navigate_to_step(step_id, is_back=is_back, force=True)

            dialog.connect("response", on_response)
            dialog.present()
            return

        step_config = FLOWS[self.active_flow_id]["steps"].get(step_id)
        if not step_config: return

        if not is_back and self.current_step_id:
            self.history.append(self.current_step_id)

        self.pending_step_id = step_id

        # always populate/inject before trying to load/scroll
        if step_id not in self.carousel_steps:
            self._populate_path_placeholders(step_id)

        self._ensure_step_loaded(step_id, lambda: GLib.timeout_add(50, self._do_scroll, step_id))

    def _do_scroll(self, step_id):
        if step_id != self.pending_step_id: return False
        target_bin = self.step_bins.get(step_id)
        if target_bin: self.carousel.scroll_to(target_bin, True)
        return False

    def _check_condition(self, condition_name):
        if not self.current_step_id:
            return False

        current_node = FLOWS[self.active_flow_id]["steps"].get(self.current_step_id)
        if not current_node:
            return False

        current_view_name = current_node["view"]
        current_page = self.loaded_pages.get(current_view_name)

        if current_page and hasattr(current_page, "state"):
            return current_page.state.get(condition_name, False)

        return False

    def navigate_next(self, route_key="next"):
        current_node = FLOWS[self.active_flow_id]["steps"].get(self.current_step_id, {})
        route_data = current_node.get("routes", {}).get(route_key)

        if not route_data: return

        if isinstance(route_data, list):
            target = next((r["target"] for r in route_data if self._check_condition(r.get("condition"))), None)
            if not target and not route_data[-1].get("condition"):
                target = route_data[-1]["target"]
            if target: self.navigate_to_step(target)
        elif isinstance(route_data, str):
            self.navigate_to_step(route_data)

    # -- view name → stable page id used in the output JSON --
    _PAGE_ID_MAP = {
        "language":      "language",
        "timezone":      "timezone",
        "keyboard":      "keyboard",
        "computer_name": "computer_name",
        "user_setup":    "user",
        "desktop_picker":"desktop",
        "theme":         "theme",
        "extra_software":"software",
        "disks":         "disks",
        "internet":      "network",
        "online_config": "online"
    }

    def collect_state(self) -> InstallState:
        """
        Walk the exact chronological path the user took and collect state.
        This prevents grabbing dead forks or injecting pages out of order.
        """
        path = self.flow_history.copy()
        if self.current_step_id and self.current_step_id not in path:
            path.append(self.current_step_id)

        collected_views = set()

        for step_id in path:
            step_config = FLOWS[self.active_flow_id]["steps"].get(step_id)
            if not step_config: continue

            view_name = step_config.get("view")
            if not view_name or view_name in collected_views:
                continue

            page_id = self._PAGE_ID_MAP.get(view_name)
            if not page_id:
                continue

            page = self.loaded_pages.get(view_name)
            if page is None or not hasattr(page, "get_finals"):
                continue

            try:
                data = page.get_finals()
                self.install_state.set_page(page_id, data)
                collected_views.add(view_name)
            except Exception as e:
                print(f"[-] collect_state: {view_name} raised {e}")

        return self.install_state

    def navigate_back(self):
        if self.history:
            prev_step_id = self.history.pop()
            self.navigate_to_step(prev_step_id, is_back=True)
