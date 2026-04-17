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

    def __init__(self, parent_window, disks, router, parent_page=None, **kwargs):
        super().__init__(**kwargs)
        self.set_transient_for(parent_window)
        self.disks = disks
        self.router = router
        self.parent_page = parent_page

        self.btn_cancel.connect("clicked", self.__on_cancel)
        self.btn_apply.connect("clicked", self.__on_apply)

        # loop through every disk in the list and grab its partitions
        self.__partitions = []
        for disk in self.disks:
            for part in disk.partitions:
                self.__partitions.append(part)

        self.__partition_selector = PartitionSelector(self, self.__partitions)

        if self.group_partitions:
            self.group_partitions.set_child(self.__partition_selector)

    def __on_apply(self, *args):
        summary = self.__partition_selector.get_summary()
        # pass the disks list and the parent page to the confirm modal
        confirm = ZenOSDefaultDiskConfirmModal(self.get_transient_for(), self.disks, summary, self.router, parent_page=self.parent_page)
        self.close()
        confirm.present()

    def __on_cancel(self, *args):
        self.close()


@Gtk.Template(resource_path="/com/negzero/zenos/setup/views/disks/dialog-disk-confirm.ui")
class ZenOSDefaultDiskConfirmModal(Adw.Window):
    __gtype_name__ = "ZenOSDefaultDiskConfirmModal"

    btn_cancel = Gtk.Template.Child()
    btn_apply = Gtk.Template.Child()

    # Maps the AdwPreferencesGroup inside the StatusPage
    group_partitions = Gtk.Template.Child()

    def __init__(self, parent_window, disks, summary, router, parent_page=None, **kwargs):
        super().__init__(**kwargs)
        self.set_transient_for(parent_window)
        self.disks = disks
        self.summary = summary
        self.router = router
        self.parent_page = parent_page

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
        if self.parent_page:
            self.parent_page.set_manual_partitions(self.summary)
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
        self.install_mode = "auto"
        self.manual_partitions = []

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
        self.install_mode = "auto"
        self.router.navigate_next("path_choice")

    def __on_manual_clicked(self, *args):
        if not self.__selected_disks:
            return
        # pass self as parent_page so the modal can pass data back on confirm
        modal = ZenOSDefaultDiskPartModal(self.get_root(), self.__selected_disks, self.router, parent_page=self)
        modal.present()

    def set_manual_partitions(self, summary):
        """Called by the confirm modal to stash the user's manual choices."""
        self.install_mode = "manual"
        self.manual_partitions = summary

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
        config = {
            "mode": self.install_mode,
            "disks": [d.name for d in self.__selected_disks],
            "total_size_gb": self.__selected_disks_sum / (1024**3)
        }

        if self.install_mode == "manual":
            # format the partitions into something easy to digest downstream
            config["partitions"] = [
                {
                    "role": role,
                    "device": part.partition,
                    "uuid": part.uuid,
                    "fs_type": part.fs_type,
                    "size": part.size
                }
                for role, part in self.manual_partitions
            ]

        return config
