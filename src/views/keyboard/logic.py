import os
import re
import gi

gi.require_version('GnomeDesktop', '4.0')
from gi.repository import Adw, Gio, GLib, Gtk
from gi.repository.GnomeDesktop import XkbInfo

class KeyMaps:
    def __init__(self):
        self.__all_keymaps = self.__get_all_keymaps()

    def __get_all_keymaps(self):
        xkb_info = XkbInfo()
        all_layouts = xkb_info.get_all_layouts()
        _all_keymaps = {}
        all_keymaps = {}
        cleanup_rules = ["A"]

        for layout in all_layouts:
            _all_keymaps[layout] = {}
            _info = xkb_info.get_layout_info(layout)
            _all_keymaps[layout]["display_name"] = _info[1]
            _all_keymaps[layout]["short_name"] = _info[2]
            _all_keymaps[layout]["xkb_layout"] = _info[3]
            _all_keymaps[layout]["xkb_variant"] = _info[4]

        for layout in _all_keymaps:
            country = _all_keymaps[layout]["display_name"].split(" ")[0]

            if country in cleanup_rules:
                continue

            if country not in all_keymaps:
                all_keymaps[country] = {}

            all_keymaps[country][layout] = _all_keymaps[layout]

        all_keymaps = {
            k: v for k, v in sorted(all_keymaps.items(), key=lambda item: item[0])
        }
        return all_keymaps

    @property
    def list_all(self):
        return self.__all_keymaps

keymaps_instance = KeyMaps()
raw_layouts = {}

for country in keymaps_instance.list_all.keys():
    for key, value in keymaps_instance.list_all[country].items():
        raw_layouts[value["display_name"]] = {
            "key": key,
            "country": country,
            "layout": value["xkb_layout"],
            "variant": value["xkb_variant"],
        }

if raw_layouts.get("Czech (with <\\|> key)"):
    raw_layouts["Czech (bksl)"] = raw_layouts.pop("Czech (with <\\|> key)")

all_keyboards = []
for title, data in raw_layouts.items():
    search_str = f"{title} {data['country']} {data['key']}".lower()
    search_blob = re.sub(r"[^a-zA-Z0-9 ]", "", search_str)
    
    all_keyboards.append({
        "title": title,
        "subtitle": data["country"],
        "layout": data["layout"],
        "variant": data["variant"],
        "key": data["key"],
        "search_blob": search_blob
    })

all_keyboards = sorted(all_keyboards, key=lambda k: k["title"])

class KeyboardRow(Adw.ActionRow):
    def __init__(self, title, subtitle, layout, variant, key, search_blob, selected_list, update_callback, **kwargs):
        super().__init__(**kwargs)
        self.set_title(title)
        self.set_subtitle(subtitle)
        
        self.__layout = layout
        self.__variant = variant
        self.search_blob = search_blob
        self.__selected_list = selected_list
        self.__update_callback = update_callback

        self.select_button = Gtk.CheckButton()
        self.select_button.set_valign(Gtk.Align.CENTER)
        self.add_prefix(self.select_button)
        
        self.suffix_label = Gtk.Label(label=key)
        self.suffix_label.set_valign(Gtk.Align.CENTER)
        self.add_suffix(self.suffix_label)

        self.select_button.connect("toggled", self.__on_toggled)
        self.set_activatable_widget(self.select_button)

    def __on_toggled(self, widget):
        item = {"layout": self.__layout, "model": "pc105", "variant": self.__variant}
        
        if widget.get_active():
            if item not in self.__selected_list:
                self.__selected_list.append(item)
        else:
            if item in self.__selected_list:
                self.__selected_list.remove(item)
                
        if self.__update_callback:
            self.__update_callback()

@Gtk.Template(resource_path="/com/negzero/zenos/setup/views/keyboard/layout.ui")
class Page(Adw.Bin):
    __gtype_name__ = "ZenOSDefaultKeyboard"

    # the manifest is checked by window.py to disable the next button on load
    MANIFEST = {
        "gated": True
    }

    entry_search_keyboard = Gtk.Template.Child()
    all_keyboards_group = Gtk.Template.Child()
    entry_test = Gtk.Template.Child()

    def __init__(self, router, **kwargs):
        super().__init__(**kwargs)
        self.router = router
        self.selected_keyboard = []
        self.__keyboard_rows = []

        # using 'changed' instead of key-released so the clear button works
        self.entry_search_keyboard.connect("changed", self.__on_search)

        self.test_focus_controller = Gtk.EventControllerFocus.new()
        if "VANILLA_NO_APPLY_XKB" not in os.environ:
            self.test_focus_controller.connect("enter", self.__apply_layout)
        self.entry_test.add_controller(self.test_focus_controller)

        self.__generate_rows()

    def __verify(self, *args):
        # ungrey the global next button if a valid kb is picked
        has_kb = len(self.selected_keyboard) > 0
        self.router.set_next_enabled(has_kb, caller=self)

    def __generate_rows(self):
        for data in all_keyboards:
            row = KeyboardRow(
                title=data["title"],
                subtitle=data["subtitle"],
                layout=data["layout"],
                variant=data["variant"],
                key=data["key"],
                search_blob=data["search_blob"],
                selected_list=self.selected_keyboard,
                update_callback=self.__verify
            )
            self.__keyboard_rows.append(row)
            self.all_keyboards_group.append(row)

    def __on_search(self, *args):
        # sanitize query
        query = re.sub(r"[^a-zA-Z0-9 ]", "", self.entry_search_keyboard.get_text().lower())
        
        # if empty (like when the clear button is clicked), unhide everything
        if not query:
            for row in self.__keyboard_rows:
                row.set_visible(True)
            return

        for row in self.__keyboard_rows:
            match = re.search(query, row.search_blob, re.IGNORECASE)
            row.set_visible(match is not None)

    def __apply_layout(self, *args):
        if not self.selected_keyboard:
            return
        
        layout_array = []
        for i in self.selected_keyboard:
            val = i["layout"]
            if i["variant"]:
                val += "+" + i["variant"]
            layout_array.append(GLib.Variant.new_tuple(
                GLib.Variant.new_string("xkb"), 
                GLib.Variant.new_string(val)
            ))

        Gio.Settings.new("org.gnome.desktop.input-sources").set_value(
            "sources",
            GLib.Variant.new_array(GLib.VariantType("(ss)"), layout_array)
        )

    def get_finals(self):
        if not self.selected_keyboard:
            return {
                "keyboard": [{"layout": "us", "model": "pc105", "variant": ""}]
            }
        return {
            "keyboard": self.selected_keyboard 
        }
