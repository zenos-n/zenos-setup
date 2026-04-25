import json
from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, GObject, Gtk, GLib

with open(Path(__file__).parent / "apps.json", encoding="utf-8") as _f:
    APPS = json.load(_f)


def get_desktop_from_state(router):
    """
    Attempts to get the selected desktop from the router's install state.
    Returns the desktop id (e.g., 'gnome', 'kde', etc.) or None if not found.
    """
    try:
        router.collect_state()
        state = router.install_state
        desktop_data = state.get_page("desktop")
        # The correct key is 'desktop_environment' (see desktop_picker/logic.py)
        if desktop_data and "desktop_environment" in desktop_data:
            return desktop_data["desktop_environment"]
    except Exception as e:
        print(f"[!] Could not determine selected desktop: {e}")
    return None


@Gtk.Template(resource_path="/com/negzero/zenos/setup/views/extra_software/popup.ui")
class AppsPopup(Adw.Window):
    __gtype_name__ = "ZenOSApplicationsDialog"

    applications_group = Gtk.Template.Child()
    apply_button = Gtk.Template.Child()

    def __init__(
        self, category_name, category_apps, current_choices, apply_cb, category_id, **kwargs
    ):
        super().__init__(**kwargs)
        self.apply_cb = apply_cb
        self.category_id = category_id
        self.set_title(f"Select {category_name.capitalize()}")

        self.local_choices = {c["app"]: c for c in current_choices}
        self.row_widgets = {}

        for app in category_apps:
            app_id = app["id"]

            existing = self.local_choices.get(
                app_id, {"app": app_id, "enabled": True, "extraOptions": []}
            )

            row = Adw.ExpanderRow(title=app["name"], icon_name=app.get("icon", ""))

            check = Gtk.CheckButton(valign=Gtk.Align.CENTER, can_focus=False)
            check.set_active(existing["enabled"])
            row.add_prefix(check)

            extras_switches = {}

            for opt in app.get("extraOptions", []):
                opt_row = Adw.ActionRow(
                    title=opt["title"], subtitle=opt.get("subtitle", ""), activatable=True
                )
                opt_switch = Gtk.Switch(
                    valign=Gtk.Align.CENTER, halign=Gtk.Align.CENTER
                )
                opt_switch.set_active(opt["id"] in existing["extraOptions"])

                opt_row.add_suffix(opt_switch)
                opt_row.set_activatable_widget(opt_switch)

                check.bind_property(
                    "active", opt_row, "sensitive", GObject.BindingFlags.SYNC_CREATE
                )

                row.add_row(opt_row)
                extras_switches[opt["id"]] = opt_switch

            v_row = Adw.ActionRow(title="Version", subtitle=app.get("version", "Unknown"))
            v_row.add_css_class("property")
            row.add_row(v_row)

            l_row = Adw.ActionRow(title="License", subtitle=app.get("license", "Unknown"))
            l_row.add_css_class("property")
            row.add_row(l_row)

            d_row = Adw.ActionRow(title=app.get("description", ""))
            d_row.set_halign(Gtk.Align.START)
            d_row.set_title_lines(0)
            d_row.add_css_class("dim-label")
            row.add_row(d_row)

            self.applications_group.add(row)
            self.row_widgets[app_id] = {"check": check, "extras": extras_switches}

        self.apply_button.connect("clicked", self._on_apply)

    def _on_apply(self, _btn):
        results = []
        for app_id, widgets in self.row_widgets.items():
            is_enabled = widgets["check"].get_active()
            active_extras = [
                eid for eid, switch in widgets["extras"].items() if switch.get_active()
            ]

            results.append(
                {"app": app_id, "enabled": is_enabled, "extraOptions": active_extras}
            )

        self.apply_cb(results, self.category_id)
        self.close()


@Gtk.Template(resource_path="/com/negzero/zenos/setup/views/extra_software/layout.ui")
class Page(Adw.Bin):
    __gtype_name__ = "ZenOSLayoutApplications"

    bundles_list = Gtk.Template.Child()

    def __init__(self, router, **kwargs):
        super().__init__(**kwargs)
        self.router = router
        self.user_choices = []
        self.cat_checks = {}
        self._updating_ui = False
        self.selected_desktop = None
        self._built_once = False
        self._added_rows = []

        self.router.carousel.connect("page-changed", self._on_page_changed)

        # fire immediately in case we load directly into view
        GLib.idle_add(self._check_if_active)

    def _check_if_active(self):
        position = self.router.carousel.get_position()
        index = round(position)
        if index < len(self.router.carousel_steps):
            step_id = self.router.carousel_steps[index]
            target_bin = self.router.step_bins.get(step_id)
            if target_bin and self.get_parent() == target_bin:
                self._rebuild_ui()

    def _on_page_changed(self, carousel, index):
        if index < len(self.router.carousel_steps):
            step_id = self.router.carousel_steps[index]
            target_bin = self.router.step_bins.get(step_id)
            if target_bin and self.get_parent() == target_bin:
                self._rebuild_ui()

    def _rebuild_ui(self):
        new_desktop = get_desktop_from_state(self.router)

        # skip rebuild if they just navigated back/forward without changing desktop
        if self._built_once and new_desktop == self.selected_desktop:
            return

        self.selected_desktop = new_desktop
        self._built_once = True

        # nuke the old ui and reset choices if we actually need a rebuild
        for row in self._added_rows:
            self.bundles_list.remove(row)
        self._added_rows.clear()

        self.cat_checks.clear()
        self.user_choices.clear()

        for cat_id, cat_data in APPS.items():
            if '-' in cat_id:
                base_cat, desktop_name = cat_id.rsplit('-', 1)
                if not self.selected_desktop or self.selected_desktop != desktop_name:
                    continue
            else:
                base_cat = cat_id

            if isinstance(cat_data, list):
                apps_list = cat_data
                title = base_cat.capitalize()
                subtitle = ""
            else:
                apps_list = cat_data.get("apps", [])
                title = cat_data.get("title", base_cat.capitalize()).replace("&", "&amp;")
                subtitle = cat_data.get("subtitle", "").replace("&", "&amp;")

            row = Adw.ActionRow(title=title, subtitle=subtitle)

            check = Gtk.CheckButton(valign=Gtk.Align.CENTER)
            check.connect("toggled", self.on_category_toggled, cat_id)
            self.cat_checks[cat_id] = check
            row.add_prefix(check)

            btn = Gtk.Button(
                icon_name="go-next-symbolic",
                valign=Gtk.Align.CENTER,
                has_frame=False,
                tooltip_text=f"Customize {title}"
            )
            btn.add_css_class("flat")
            btn.connect("clicked", self.on_category_configure_clicked, cat_id)

            row.add_suffix(btn)
            row.set_activatable_widget(btn)

            self.bundles_list.add(row)
            self._added_rows.append(row)

            is_active = check.get_active()
            for app in apps_list:
                enabled = app.get("default", is_active)
                self.user_choices.append(
                    {"app": app["id"], "enabled": enabled, "extraOptions": []}
                )

    def get_finals(self):
        return {"apps": list(self.user_choices)}

    def on_category_toggled(self, checkbtn, cat_id):
        if self._updating_ui:
            return

        is_active = checkbtn.get_active()
        cat_data = APPS[cat_id]
        apps_in_cat = cat_data if isinstance(cat_data, list) else cat_data.get("apps", [])
        app_ids = {a["id"] for a in apps_in_cat}

        for choice in self.user_choices:
            if choice["app"] in app_ids:
                choice["enabled"] = is_active

        print(f"[+] mass toggled {cat_id} -> {is_active}")

        self._updating_ui = True
        checkbtn.set_inconsistent(False)
        self._updating_ui = False

    def on_category_configure_clicked(self, btn, cat_id):
        cat_data = APPS[cat_id]
        if isinstance(cat_data, list):
            category_apps = cat_data
            category_name = cat_id.capitalize()
        else:
            category_apps = cat_data.get("apps", [])
            category_name = cat_data.get("title", cat_id)

        popup = AppsPopup(
            category_name=category_name,
            category_apps=category_apps,
            current_choices=self.user_choices,
            apply_cb=self.update_choices,
            category_id=cat_id
        )

        parent_window = self.get_root()
        popup.set_transient_for(parent_window)
        popup.set_modal(True)
        popup.present()

    def update_choices(self, category_results, category_id):
        updated_app_ids = {r["app"] for r in category_results}
        self.user_choices = [
            c for c in self.user_choices if c["app"] not in updated_app_ids
        ]
        self.user_choices.extend(category_results)

        self.refresh_ui_for_category(category_id)
        print(f"[+] current software selections: {self.user_choices}")

    def refresh_ui_for_category(self, category_id):
        cat_data = APPS.get(category_id, {})
        apps_in_cat = cat_data if isinstance(cat_data, list) else cat_data.get("apps", [])

        if not apps_in_cat:
            return

        app_ids = [a["id"] for a in apps_in_cat]
        enabled_count = sum(
            1 for c in self.user_choices if c["app"] in app_ids and c["enabled"]
        )

        checkbtn = self.cat_checks[category_id]

        self._updating_ui = True

        if enabled_count == 0:
            checkbtn.set_inconsistent(False)
            checkbtn.set_active(False)
        elif enabled_count == len(app_ids):
            checkbtn.set_inconsistent(False)
            checkbtn.set_active(True)
        else:
            checkbtn.set_inconsistent(True)
            checkbtn.set_active(True)

        self._updating_ui = False
