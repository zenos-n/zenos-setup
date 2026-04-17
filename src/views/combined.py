--- ./disks/logic.py ---
import json
import os
import subprocess
from gettext import gettext as _

import gi
gi.require_version('Adw', '1')
gi.require_version('Gtk', '4.0')
from gi.repository import Adw, Gtk, GLib

# --- Core Disk Backend (Merged) ---

class Diskutils:
    @staticmethod
    def pretty_size(size: int) -> str:
        """Converts raw bytes into a human-readable format."""
        if size > 1024**3:
            return f"{round(size / 1024 ** 3, 2)} GB"
        elif size > 1024**2:
            return f"{round(size / 1024 ** 2, 2)} MB"
        elif size > 1024:
            return f"{round(size / 1024, 2)} KB"
        else:
            return f"{size} B"

    @staticmethod
    def separate_device_and_partn(part_dev: str) -> tuple[str, str | None]:
        """Separates a partition path into device path and partition number."""
        try:
            info_json = subprocess.check_output(
                ["lsblk", "--json", "-o", "NAME,PKNAME,PARTN", part_dev]
            ).decode("utf-8")
            info_multiple = json.loads(info_json)["blockdevices"]

            if len(info_multiple) > 1:
                raise ValueError(f"{part_dev} returned more than one device")
            info = info_multiple[0]

            if not info.get("partn"):
                return "/dev/" + info["name"], None

            return "/dev/" + info.get("pkname", ""), str(info["partn"])
        except Exception:
            return part_dev, None


class Partition:
    def __init__(self, name):
        self.partition = name
        self.uuid = ""
        self.fs_type = ""
        self.size = ""
        self.mountpoint = ""

    def __eq__(self, other):
        if not isinstance(other, Partition):
            return False
        return self.uuid == other.uuid and self.fs_type == other.fs_type


class Disk:
    def __init__(self, name):
        self.disk = name
        self.name = name
        self.size = 0
        self.is_removable = False
        self.partitions = []
        self._load_sysfs_data()
        self._load_partitions()

    def _load_sysfs_data(self):
        """Loads physical properties from sysfs."""
        try:
            with open(f"/sys/block/{self.name}/size", "r") as f:
                self.size = int(f.read().strip()) * 512
        except Exception:
            pass

        try:
            with open(f"/sys/block/{self.name}/removable", "r") as f:
                self.is_removable = int(f.read().strip()) == 1
        except Exception:
            pass

    def _load_partitions(self):
        """Loads partitions dynamically using lsblk."""
        try:
            out = subprocess.check_output(
                ["lsblk", "-J", "-o", "NAME,FSTYPE,SIZE,MOUNTPOINT,UUID", f"/dev/{self.name}"]
            ).decode("utf-8")
            data = json.loads(out)

            if "blockdevices" in data and len(data["blockdevices"]) > 0:
                dev = data["blockdevices"][0]
                if "children" in dev:
                    for child in dev["children"]:
                        p = Partition(f"/dev/{child.get('name')}")
                        p.fs_type = child.get("fstype", "")
                        p.uuid = child.get("uuid", "")
                        p.size = child.get("size", "")
                        p.mountpoint = child.get("mountpoint", "")
                        self.partitions.append(p)
        except Exception:
            pass

    @property
    def pretty_size(self):
        return Diskutils.pretty_size(self.size)


class DisksManager:
    def __init__(self):
        self.__disks = self.__get_disks()

    def __get_disks(self):
        disks = []
        if not os.path.exists("/sys/block"):
            return disks

        for disk in os.listdir("/sys/block"):
            # Exclude virtual, ram, optical, or mapper devices
            if disk.startswith(("loop", "ram", "sr", "zram", "dm-")):
                continue
            disks.append(Disk(disk))
        return disks

    def all_disks(self, include_removable: bool = True):
        if include_removable:
            return self.__disks
        return [d for d in self.__disks if not d.is_removable]


# --- UI Components ---

@Gtk.Template(resource_path="/com/negzero/zenos/setup/views/disks/widget-disk.ui")
class ZenOSDefaultDiskEntry(Adw.ActionRow):
    __gtype_name__ = "ZenOSDefaultDiskEntry"

    chk_button = Gtk.Template.Child()

    def __init__(self, parent, disk, **kwargs):
        super().__init__(**kwargs)
        self.__parent = parent
        self.__disk = disk

        self.set_title(disk.name)
        self.set_subtitle(disk.pretty_size)

        self.chk_button.connect("toggled", self.__on_toggled)

    def __on_toggled(self, widget):
        self.__parent.on_disk_entry_toggled(widget, self.__disk)


# Ported PartitionRow
@Gtk.Template(resource_path="/com/negzero/zenos/setup/views/disks/widget-partition-row.ui")
class PartitionRow(Adw.ActionRow):
    __gtype_name__ = "ZenOSPartitionRow"

    select_button = Gtk.Template.Child()

    def __init__(self, partition, **kwargs):
        super().__init__(**kwargs)
        self.partition = partition

        size_str = f" ({self.partition.size})" if self.partition.size else ""
        self.set_title(f"{self.partition.partition}{size_str}")

        fs = self.partition.fs_type if self.partition.fs_type else "Unknown"
        self.set_subtitle(f"Format: {fs}")


# Ported PartitionSelector
@Gtk.Template(resource_path="/com/negzero/zenos/setup/views/disks/widget-partition.ui")
class PartitionSelector(Adw.PreferencesPage):
    __gtype_name__ = "ZenOSPartitionSelector"

    def __init__(self, parent_modal, partitions, **kwargs):
        super().__init__(**kwargs)
        self.parent_modal = parent_modal
        self.partitions = partitions
        self.selected_partitions = {}

        self.__populate()

    def _find_expander_rows(self, widget):
        """Recursively finds all Adw.ExpanderRow elements in the page."""
        expanders = []
        child = widget.get_first_child()
        while child:
            if isinstance(child, Adw.ExpanderRow):
                expanders.append(child)
            # Recurse into groups and boxes
            expanders.extend(self._find_expander_rows(child))
            child = child.get_next_sibling()
        return expanders

    def __populate(self):
        # Dynamically locate all dropdowns (e.g. swap_part_expand, boot_part_expand)
        expanders = self._find_expander_rows(self)

        for expander in expanders:
            original_subtitle = expander.get_subtitle()
            first_btn = None
            for part in self.partitions:
                # We instantiate a new row for each expander because GTK
                # widgets can strictly only have one parent at a time.
                row = PartitionRow(part)

                # Group the check buttons so only one partition can be chosen per dropdown
                if first_btn is None:
                    first_btn = row.select_button
                else:
                    row.select_button.set_group(first_btn)

                # Connect the signal to update the dropdown's title when selected
                row.select_button.connect("toggled", self._on_partition_selected, row, expander, original_subtitle)

                expander.add_row(row)

    def _on_partition_selected(self, button, row, expander, original_subtitle):
        """Updates the ExpanderRow label when a partition is chosen."""
        if button.get_active():
            self.selected_partitions[expander] = row.partition

            size_str = f" ({row.partition.size})" if row.partition.size else ""
            expander.set_title(f"{row.partition.partition}{size_str}")
            fs = row.partition.fs_type if row.partition.fs_type else "Unknown"
            expander.set_subtitle(f"Format: {fs}")
        else:
            # Handles when a previously selected item becomes inactive
            if self.selected_partitions.get(expander) == row.partition:
                del self.selected_partitions[expander]
                expander.set_title(_("No Partition Selected"))
                expander.set_subtitle(original_subtitle)

    def get_summary(self):
        """Returns a list of tuples containing (Role Name, Partition object)"""
        summary = []
        for expander, partition in self.selected_partitions.items():
            role_name = _("Selected Partition")
            parent = expander.get_parent()

            # Fetch the role name directly from the parent group title if possible
            if parent and hasattr(parent, "get_title") and parent.get_title():
                role_name = parent.get_title()

            summary.append((role_name, partition))
        return summary


@Gtk.Template(resource_path="/com/negzero/zenos/setup/views/disks/dialog-disk.ui")
class ZenOSDefaultDiskPartModal(Adw.Window):
    __gtype_name__ = "ZenOSDefaultDiskPartModal"

    btn_cancel = Gtk.Template.Child()
    btn_apply = Gtk.Template.Child()

    # Map the AdwToastOverlay from dialog-disk.ui
    group_partitions = Gtk.Template.Child()

    def __init__(self, parent_window, disk, router, **kwargs): # add router here
        super().__init__(**kwargs)
        self.set_transient_for(parent_window)
        self.disk = disk
        self.router = router # store it

        self.btn_cancel.connect("clicked", self.__on_cancel)
        self.btn_apply.connect("clicked", self.__on_apply)

        # Port the partition loading logic from disk.py
        self.__partitions = []
        for part in self.disk.partitions:
            self.__partitions.append(part)

        # Instantiate PartitionSelector and set it as the child
        self.__partition_selector = PartitionSelector(self, self.__partitions)

        if self.group_partitions:
            self.group_partitions.set_child(self.__partition_selector)

    def __on_cancel(self, *args):
        self.close()

    def __on_apply(self, *args):
        summary = self.__partition_selector.get_summary()
        # pass it to the next modal
        confirm = ZenOSDefaultDiskConfirmModal(self.get_transient_for(), self.disk, summary, self.router)
        self.close()
        confirm.present()


@Gtk.Template(resource_path="/com/negzero/zenos/setup/views/disks/dialog-disk-confirm.ui")
class ZenOSDefaultDiskConfirmModal(Adw.Window):
    __gtype_name__ = "ZenOSDefaultDiskConfirmModal"

    btn_cancel = Gtk.Template.Child()
    btn_apply = Gtk.Template.Child()

    # Maps the AdwPreferencesGroup inside the StatusPage
    group_partitions = Gtk.Template.Child()

    def __init__(self, parent_window, disk, summary, router, **kwargs): # add router here
        super().__init__(**kwargs)
        self.set_transient_for(parent_window)
        self.disk = disk
        self.summary = summary
        self.router = router # now self.router.navigate_next() won't crash

        self.btn_cancel.connect("clicked", self.__on_cancel)
        self.btn_apply.connect("clicked", self.__on_apply)

        self.__populate_summary()

    def __populate_summary(self):
        if not self.group_partitions:
            return

        if not self.summary:
            row = Adw.ActionRow(title=_("No partitions selected"), subtitle=_("No manual changes will be applied."))
            self.group_partitions.add(row)
            return

        for role_name, partition in self.summary:
            row = Adw.ActionRow(title=role_name)
            size_str = f" ({partition.size})" if partition.size else ""
            row.set_subtitle(f"{partition.partition}{size_str} - Format: {partition.fs_type or 'Unknown'}")
            self.group_partitions.add(row)

    def __on_cancel(self, *args):
        self.close()

    def __on_apply(self, *args):
        self.router.navigate_next("path_choice")
        self.close()


@Gtk.Template(resource_path="/com/negzero/zenos/setup/views/disks/layout.ui")
class Page(Adw.Bin):
    __gtype_name__ = "ZenOSDefaultDisks"

    MANIFEST = {
        "gated": True
    }

    # Template Children (IDs must match layout.ui exactly)
    btn_auto = Gtk.Template.Child()
    btn_manual = Gtk.Template.Child()
    disk_space_err_box = Gtk.Template.Child()
    group_disks = Gtk.Template.Child()

    def __init__(self, router, **kwargs):
        super().__init__(**kwargs)
        self.router = router
        self.__selected_disks = []
        self.__selected_disks_sum = 0
        self.min_disk_size_gb = 20
        self.__recipe = None

        # Lock the navigation initially (gated)
        self.router.set_next_enabled(False, caller=self)

        # Populate the disk list
        self.manager = DisksManager()
        self.__load_disks()

        # Connect action buttons
        if self.btn_auto:
            self.btn_auto.connect("clicked", self.__on_auto_clicked)
            self.btn_auto.set_sensitive(False)

        if self.btn_manual:
            self.btn_manual.connect("clicked", self.__on_manual_clicked)
            self.btn_manual.set_sensitive(False)

    def __load_disks(self):
        if not self.group_disks:
            return

        for disk in self.manager.all_disks(include_removable=False):
            row = ZenOSDefaultDiskEntry(self, disk)
            self.group_disks.add(row)

    def __on_auto_clicked(self, *args):
        self.router.navigate_next("path_choice")

    def __on_manual_clicked(self, *args):
        if not self.__selected_disks:
            return
        disk = self.__selected_disks[0]
        modal = ZenOSDefaultDiskPartModal(self.get_root(), disk, self.router)
        modal.present()

    def on_disk_entry_toggled(self, widget, disk):
        if widget.get_active():
            if disk not in self.__selected_disks:
                self.__selected_disks.append(disk)
                self.__selected_disks_sum += disk.size
        else:
            if disk in self.__selected_disks:
                self.__selected_disks.remove(disk)
                self.__selected_disks_sum -= disk.size

        # Convert raw bytes to GB
        size_gb = self.__selected_disks_sum / (1024**3)

        # Validation Logic
        has_selection = len(self.__selected_disks) > 0
        is_size_valid = size_gb >= self.min_disk_size_gb

        show_error = has_selection and not is_size_valid
        self.disk_space_err_box.set_visible(show_error)

        valid_ready = has_selection and is_size_valid

        if self.btn_auto:
            self.btn_auto.set_sensitive(len(self.__selected_disks) == 1 and is_size_valid)

        if self.btn_manual:
            self.btn_manual.set_sensitive(valid_ready)

        self.router.set_next_enabled(valid_ready, caller=self)

    def get_finals(self):
        """Returns the configuration for the installer script."""
        return {
            "disks": [d.name for d in self.__selected_disks],
            "recipe": self.__recipe,
            "total_size_gb": self.__selected_disks_sum / (1024**3)
        }

--- ./progress/logic.py ---
from gi.repository import Gtk, Adw, GObject

@Gtk.Template(resource_path='/com/negzero/zenos/setup/views/progress/layout.ui')
class Page(Gtk.Box):
    __gtype_name__ = 'ZenOSDefaultProgress'

    # mapping the ui definitions to the class
    carousel_tour = Gtk.Template.Child()
    tour_btn_back = Gtk.Template.Child()
    tour_btn_next = Gtk.Template.Child()
    tour_box = Gtk.Template.Child()
    console_box = Gtk.Template.Child()
    console_button = Gtk.Template.Child()
    tour_button = Gtk.Template.Child()
    progressbar = Gtk.Template.Child()

    MANIFEST = {
        "gated": True,
        "unclosable": True
    }

    def __init__(self, router, **kwargs):
        super().__init__(**kwargs)
        self.router = router
        self.install_state = None

        # hook up the slideshow nav
        self.tour_btn_back.connect("clicked", self._on_tour_prev)
        self.tour_btn_next.connect("clicked", self._on_tour_next)
        self.carousel_tour.connect("page-changed", self._update_tour_buttons)

        # toggle between console and tour
        self.console_button.connect("clicked", self._show_console)
        self.tour_button.connect("clicked", self._show_tour)

        # collect all page state before doing anything else
        self.install_state = self.router.collect_state()
        print("[+] install state collected:")
        print(self.install_state.to_json(indent=2))

        # TODO: hand self.install_state to your util here
        # e.g. threading.Thread(target=run_my_util, args=(self.install_state,), daemon=True).start()

        # fake progress for testing
        GObject.timeout_add(100, self._fake_progress)

    def _on_tour_next(self, _):
        current = self.carousel_tour.get_nth_page(self.carousel_tour.get_position())
        # adw.carousel doesn't have a simple "next", so we grab the next widget
        # this is assuming you've appended pages to carousel_tour elsewhere
        pass

    def _on_tour_prev(self, _):
        pass

    def _update_tour_buttons(self, *args):
        # logic to hide/show buttons based on carousel position
        pos = self.carousel_tour.get_position()
        self.tour_btn_back.set_visible(pos > 0)
        # add logic for the end of the carousel here

    def _show_console(self, _):
        self.tour_box.set_visible(False)
        self.console_box.set_visible(True)
        self.console_button.set_visible(False)
        self.tour_button.set_visible(True)

    def _show_tour(self, _):
        self.console_box.set_visible(False)
        self.tour_box.set_visible(True)
        self.tour_button.set_visible(False)
        self.console_button.set_visible(True)

    def _fake_progress(self):
        val = self.progressbar.get_fraction()
        if val < 1.0:
            self.progressbar.set_fraction(val + 0.01)
            return True
        self.router.set_next_enabled(True, caller=self)
        return False
--- ./extra_software/logic.py ---
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

    def get_finals(self):
        return {"apps": list(self.user_choices)}
--- ./path_choice/logic.py ---
from gi.repository import Adw, Gtk

@Gtk.Template(resource_path='/com/negzero/zenos/setup/views/path_choice/layout.ui')
class Page(Adw.Bin):
    __gtype_name__ = 'ZenOSDefaultPath'

    # grab the rows from the xml
    btn_now = Gtk.Template.Child()
    btn_setup = Gtk.Template.Child()

    def __init__(self, router, **kwargs):
        super().__init__(**kwargs)
        self.router = router

        # hook up the click events
        self.btn_now.connect('activated', self.on_now_clicked)
        self.btn_setup.connect('activated', self.on_manual_clicked)

    def on_now_clicked(self, *args):
        # use the key "install_now", not the destination id
        self.router.navigate_next("install_now")

    def on_manual_clicked(self, *args):
        # use the key "finish_setup"
        self.router.navigate_next("finish_setup")
