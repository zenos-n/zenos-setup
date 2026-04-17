import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Gtk, Adw, GObject

# throwing some dummy data in here so the UI actually populates when you click something.
# structure matches exactly what you asked for.
APPS = {
    "browsers": [
        {
            "id": "firefox",
            "name": "Mozilla Firefox",
            "icon": "firefox",
            "version": "125.0.1-stable",
            "license": "MPL-2.0",
            "description": "the default web browser. respects your privacy and doesn't hoard your ram (usually).",
            "extraOptions": [
                {
                    "id": "gnome_theme",
                    "title": "Gnome Theme",
                    "subtitle": "Make Firefox look like a gnome-native app thanks to the firefox gnome theme, made by rafaelmardojai"
                }
            ]
        },
        {
            "id": "chromium",
            "name": "Chromium",
            "icon": "chromium",
            "version": "124.0.0",
            "license": "BSD",
            "description": "open source base for chrome. eats ram for breakfast.",
            "extraOptions": []
        }
    ],
    "gaming": [
        {
            "id": "steam",
            "name": "Steam",
            "icon": "steam",
            "version": "latest",
            "license": "Proprietary",
            "description": "gabe newell's money printer. runs proton so you can actually game on linux.",
            "extraOptions": []
        }
    ],
    "dev": [
        {
            "id": "vscode",
            "name": "Visual Studio Code",
            "icon": "code",
            "version": "1.89.0",
            "license": "MIT / Proprietary",
            "description": "microsoft's text editor that everyone uses. electron based so it's heavy but it works.",
            "extraOptions": []
        }
    ]
}

@Gtk.Template(resource_path='/com/negzero/zenos/setup/views/extra_software/popup.ui')
class AppsPopup(Adw.Window):
    __gtype_name__ = 'ZenOSApplicationsDialog'

    applications_group = Gtk.Template.Child()
    apply_button = Gtk.Template.Child()

    def __init__(self, category_name, category_apps, current_choices, apply_cb, **kwargs):
        super().__init__(**kwargs)
        self.apply_cb = apply_cb
        self.set_title(f"Select {category_name.capitalize()}")

        # we hold state locally for the popup so if they just close the window
        # without hitting apply, it discards their changes.
        self.local_choices = {c["app"]: c for c in current_choices}
        self.row_widgets = {}

        for app in category_apps:
            app_id = app["id"]

            # default to checked if it's the first time they see it, otherwise grab saved state
            existing = self.local_choices.get(app_id, {"app": app_id, "enabled": True, "extraOptions": []})

            # the main expander row
            row = Adw.ExpanderRow(title=app["name"], icon_name=app["icon"])

            # prefix checkbutton
            check = Gtk.CheckButton(valign=Gtk.Align.CENTER, can_focus=False)
            check.set_active(existing["enabled"])
            row.add_prefix(check)

            extras_switches = {}

            # append the extra toggles if the app has any
            for opt in app.get("extraOptions", []):
                opt_row = Adw.ActionRow(title=opt["title"], subtitle=opt["subtitle"], activatable=True)
                opt_switch = Gtk.Switch(valign=Gtk.Align.CENTER, halign=Gtk.Align.CENTER)
                opt_switch.set_active(opt["id"] in existing["extraOptions"])

                # actually add the switch to the row this time
                opt_row.add_suffix(opt_switch)
                opt_row.set_activatable_widget(opt_switch)

                # bind the extra option's interactability to the main app's checkbutton
                check.bind_property("active", opt_row, "sensitive", GObject.BindingFlags.SYNC_CREATE)

                row.add_row(opt_row)
                extras_switches[opt["id"]] = opt_switch

            # simple metadata rows using the property style class
            v_row = Adw.ActionRow(title="Version", subtitle=app["version"])
            v_row.add_css_class("property")
            row.add_row(v_row)

            l_row = Adw.ActionRow(title="License", subtitle=app["license"])
            l_row.add_css_class("property")
            row.add_row(l_row)

            # description row
            d_row = Adw.ActionRow(title=app["description"])
            d_row.set_halign(Gtk.Align.START)
            d_row.set_title_lines(0)
            d_row.add_css_class("dim-label")
            row.add_row(d_row)

            self.applications_group.add(row)

            # store references to the widgets so we can pull their state on apply
            self.row_widgets[app_id] = {
                "check": check,
                "extras": extras_switches
            }

        self.apply_button.connect("clicked", self._on_apply)

    def _on_apply(self, _btn):
        results = []
        for app_id, widgets in self.row_widgets.items():
            is_enabled = widgets["check"].get_active()
            active_extras = [eid for eid, switch in widgets["extras"].items() if switch.get_active()]

            results.append({
                "app": app_id,
                "enabled": is_enabled,
                "extraOptions": active_extras
            })

        self.apply_cb(results)
        self.close()


@Gtk.Template(resource_path='/com/negzero/zenos/setup/views/extra_software/layout.ui')
class Page(Adw.Bin):
    __gtype_name__ = 'ZenOSLayoutApplications'

    # buttons
    core_button = Gtk.Template.Child()
    browsers_button = Gtk.Template.Child()
    utilities_button = Gtk.Template.Child()
    gaming_button = Gtk.Template.Child()
    dev_button = Gtk.Template.Child()
    office_button = Gtk.Template.Child()

    # checkbuttons for the categories
    core_check = Gtk.Template.Child()
    browsers_switch = Gtk.Template.Child()
    utilities_switch = Gtk.Template.Child()
    gaming_switch = Gtk.Template.Child()
    dev_switch = Gtk.Template.Child()
    office_switch = Gtk.Template.Child()

    def __init__(self, router, **kwargs):
        super().__init__(**kwargs)
        self.router = router
        self.MANIFEST = {"gated": False}
        self.user_choices = []

        # lock flag so we don't trigger mass-toggles when updating ui programmatically
        self._updating_ui = False

        self.cat_checks = {
            "core": self.core_check,
            "browsers": self.browsers_switch,
            "utilities": self.utilities_switch,
            "gaming": self.gaming_switch,
            "dev": self.dev_switch,
            "office": self.office_switch
        }

        btn_map = {
            self.core_button: "core",
            self.browsers_button: "browsers",
            self.utilities_button: "utilities",
            self.gaming_button: "gaming",
            self.dev_button: "dev",
            self.office_button: "office"
        }

        # wire up popups
        for btn, cat in btn_map.items():
            btn.connect("clicked", lambda _, c=cat: self.open_category_popup(c))

        # wire up mass toggles
        for cat, checkbtn in self.cat_checks.items():
            checkbtn.connect("toggled", lambda cb, c=cat: self.on_cat_toggled(cb, c))

            # prepopulate choices based on the initial xml state so we don't start empty
            is_active = checkbtn.get_active()
            for app in APPS.get(cat, []):
                self.user_choices.append({
                    "app": app["id"],
                    "enabled": is_active,
                    "extraOptions": []
                })

    def on_cat_toggled(self, checkbtn, category_name):
        if self._updating_ui:
            return

        is_active = checkbtn.get_active()

        # clear the dash state if they manually clicked it
        self._updating_ui = True
        checkbtn.set_inconsistent(False)
        self._updating_ui = False

        # blast the new state to all apps in the category
        app_ids = {a["id"] for a in APPS.get(category_name, [])}
        for choice in self.user_choices:
            if choice["app"] in app_ids:
                choice["enabled"] = is_active

        print(f"[+] mass toggled {category_name} to {is_active}")

    def open_category_popup(self, category_name):
        apps_for_cat = APPS.get(category_name, [])
        if not apps_for_cat:
            print(f"[-] no apps defined in APPS dict for category: {category_name}")
            return

        popup = AppsPopup(
            category_name=category_name,
            category_apps=apps_for_cat,
            current_choices=self.user_choices,
            apply_cb=lambda results: self.update_choices(results, category_name)
        )

        parent_window = self.get_root()
        popup.set_transient_for(parent_window)
        popup.set_modal(True)
        popup.present()

    def update_choices(self, category_results, category_name):
        # strip old states and inject new
        updated_app_ids = {r["app"] for r in category_results}
        self.user_choices = [c for c in self.user_choices if c["app"] not in updated_app_ids]
        self.user_choices.extend(category_results)

        self.refresh_ui_for_category(category_name)
        print(f"[+] current software selections: {self.user_choices}")

    def refresh_ui_for_category(self, category_name):
        apps_in_cat = APPS.get(category_name, [])
        if not apps_in_cat:
            return

        app_ids = [a["id"] for a in apps_in_cat]
        enabled_count = sum(1 for c in self.user_choices if c["app"] in app_ids and c["enabled"])

        checkbtn = self.cat_checks[category_name]

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
