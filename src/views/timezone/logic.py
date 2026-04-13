import datetime
import logging
import re
import threading
import unicodedata
import requests
from gettext import gettext as _
from zoneinfo import ZoneInfo
import gi

gi.require_version('GWeather', '4.0')
from gi.repository import Adw, GLib, Gtk, GWeather

logger = logging.getLogger("ZenOSInstaller::Timezone")

# --- locale.py dump ---

class Locale:
    def __init__(self, locales, region, location):
        self.locales = locales
        self.region = region
        self.location = location

    def __str__(self):
        return "<Locale: {} {} {}>".format(self.locales, self.region, self.location)

    def __repr__(self):
        return self.__str__()


# --- timezones.py dump ---

regions: dict[str, dict[str, dict[str, str]]] = {}
world = GWeather.Location.get_world()
parents = []
base = world
child = None

while True:
    child = base.next_child(child)
    if child is not None:
        if child.get_level() == GWeather.LocationLevel.REGION:
            regions[child.get_name()] = {}
            current_region = child.get_name()
        elif child.get_level() == GWeather.LocationLevel.COUNTRY:
            regions[current_region][child.get_name()] = {}
            current_country = child.get_name()
        elif child.get_level() == GWeather.LocationLevel.CITY:
            regions[current_region][current_country][child.get_city_name()] = (
                child.get_timezone_str()
            )

        if child.next_child(None) is not None:
            parents.append(child)
            base = child
            child = None
    else:
        base = base.get_parent()
        if base is None:
            break
        child = parents.pop()

all_timezones = dict(sorted(regions.items()))

def get_location(callback=None):
    logger.info("trying to retrieve timezone automatically")
    try:
        res = requests.get("http://ip-api.com/json?fields=49344", timeout=3).json()
        if res["status"] != "success":
            raise Exception(f"get_location: request failed with message '{res['message']}'")
        nearest = world.find_nearest_city(res["lat"], res["lon"])
    except Exception as e:
        logger.error(f"failed to retrieve timezone: {e}")
        nearest = None

    if callback:
        GLib.idle_add(callback, nearest)

tz_preview_cache: dict[str, tuple[str, str]] = {}

def get_timezone_preview(tzname):
    if tzname in tz_preview_cache:
        return tz_preview_cache[tzname]
    else:
        try:
            timezone = ZoneInfo(tzname)
            now = datetime.datetime.now(timezone)
            now_str = (
                "%02d:%02d" % (now.hour, now.minute),
                now.strftime("%A, %d %B %Y"),
            )
            tz_preview_cache[tzname] = now_str
            return now_str
        except Exception:
            return ("--:--", "Unknown Date")


# --- timezone.py dump (adapted for the new router) ---

@Gtk.Template(resource_path="/com/negzero/zenos/setup/views/timezone/widget-timezone.ui")
class TimezoneRow(Adw.ActionRow):
    __gtype_name__ = "TimezoneRow"

    select_button = Gtk.Template.Child()
    country_label = Gtk.Template.Child()

    def __init__(self, title, subtitle, tz_name, toggled_callback, parent_expander, **kwargs):
        super().__init__(**kwargs)
        self.title = title
        self.subtitle = subtitle
        self.tz_name = tz_name
        self.parent_expander = parent_expander

        self.set_title(title)
        self.country_label.set_label(tz_name)

        self.select_button.connect("toggled", toggled_callback, self)
        self.parent_expander.connect("notify::expanded", self.update_time_preview)

    def update_time_preview(self, *args):
        if self.parent_expander.get_expanded():
            tz_time, tz_date = get_timezone_preview(self.tz_name)
            self.set_subtitle(f"{tz_time} • {tz_date}")


@Gtk.Template(resource_path="/com/negzero/zenos/setup/views/timezone/layout.ui")
class Page(Adw.Bin):
    __gtype_name__ = "ZenOSDefaultTimezone"
    
    MANIFEST = {
        "gated": True
    }

    entry_search_timezone = Gtk.Template.Child()
    all_timezones_group = Gtk.Template.Child()
    current_tz_label = Gtk.Template.Child()
    current_location_label = Gtk.Template.Child()
    loading_spinner = Gtk.Template.Child()

    selected_timezone = {"region": None, "zone": None}

    expanders_list = dict(
        sorted(
            {
                country: region
                for region, countries in all_timezones.items()
                for country in countries.keys()
            }.items()
        )
    )

    def __init__(self, router, **kwargs):
        super().__init__(**kwargs)
        self.router = router
        self.detected_tz = None
        self._block_signals = False
        self._deltas_generated = False
        self.__expanders = []
        self.__tz_entries = []

        self.entry_search_timezone.connect("changed", self.__on_search)
        self.router.set_next_enabled(False, caller=self)
        self.connect("map", self._on_map)
        self.router.carousel.connect("page-changed", self.timezone_verify)

    def _on_map(self, *args):
        if not self._deltas_generated:
            self._deltas_generated = True
            self.gen_deltas()

    def gen_deltas(self):
        self.del_deltas()
        self._cancel_load = False
        
        self.loading_spinner.set_visible(True)
        self.loading_spinner.start()
        self.entry_search_timezone.set_sensitive(False)
        self.all_timezones_group.set_visible(False)

        GLib.timeout_add(400, self._start_generator)

    def _start_generator(self):
        if getattr(self, '_cancel_load', False):
            return False
        self._tz_generator = iter(self.expanders_list.items())
        GLib.idle_add(self._populate_chunk)
        return False

    def del_deltas(self):
        self._cancel_load = True
        self.__tz_entries = []
        for i in self.__expanders:
            self.all_timezones_group.remove(i)
        self.__expanders = []

    def _populate_chunk(self):
        if getattr(self, '_cancel_load', False):
            return False 

        try:
            country, region = next(self._tz_generator)

            if len(all_timezones[region][country]) > 0:
                self._block_signals = True
                expander = Adw.ExpanderRow.new()
                expander.set_title(country)
                expander.set_subtitle(region)
                self.all_timezones_group.add(expander)
                self.__expanders.append(expander)

                for city, tzname in all_timezones[region][country].items():
                    timezone_row = TimezoneRow(city, country, tzname, self.__on_row_toggle, expander)
                    self.__tz_entries.append(timezone_row)
                    
                    if len(self.__tz_entries) > 1:
                        timezone_row.select_button.set_group(self.__tz_entries[0].select_button)
                    
                    if self.detected_tz and tzname == self.detected_tz:
                        timezone_row.select_button.set_active(True)
                        self._update_selection_labels(timezone_row)
                        self.router.set_next_enabled(True, caller=self)
                    
                    expander.add_row(timezone_row)
                self._block_signals = False
            return True
        except StopIteration:
            self.loading_spinner.stop()
            self.loading_spinner.set_visible(False)
            self.entry_search_timezone.set_sensitive(True)
            self.all_timezones_group.set_visible(True)
            self._block_signals = False
            return False

    def timezone_verify(self, carousel=None, idx=None):
        if self.router.current_step_id != "timezone":
            return

        def timezone_verify_callback(result, *args):
            if result:
                self.detected_tz = result.get_timezone_str()
                for entry in self.__tz_entries:
                    if entry.tz_name == self.detected_tz:
                        self._block_signals = True
                        entry.select_button.set_active(True)
                        self._update_selection_labels(entry)
                        self._block_signals = False
                        self.router.set_next_enabled(True, caller=self)
                        break

        thread = threading.Thread(target=get_location, args=(timezone_verify_callback,))
        thread.start()

    def _update_selection_labels(self, widget):
        tz_split = widget.tz_name.split("/", 1)
        self.selected_timezone["region"] = tz_split[0]
        self.selected_timezone["zone"] = tz_split[1] if len(tz_split) > 1 else tz_split[0]
        self.current_tz_label.set_label(widget.tz_name)
        self.current_location_label.set_label(_("(at %s, %s)") % (widget.title, widget.subtitle))

    def get_finals(self):
        return {
            "timezone": {
                "region": self.selected_timezone["region"] or "Europe",
                "zone": self.selected_timezone["zone"] or "London",
            }
        }

    def __on_search(self, *args):
        self._block_signals = True
        
        def remove_accents(msg: str):
            out = unicodedata.normalize("NFD", msg).encode("ascii", "ignore").decode("utf-8")
            return str(out)

        search_entry = self.entry_search_timezone.get_text().lower()
        keywords = remove_accents(search_entry)

        if len(keywords) == 0:
            for expander in self.__expanders:
                expander.set_visible(True)
                expander.set_expanded(False)
            for entry in self.__tz_entries:
                entry.set_visible(True)
            self._block_signals = False
            return

        current_expander_idx = 0
        if not self.__tz_entries:
            self._block_signals = False
            return
            
        current_country = self.__tz_entries[0].subtitle
        visible_entries_in_current = 0
        
        for entry in self.__tz_entries:
            row_title = remove_accents(entry.get_title().lower())
            match = re.search(keywords, row_title, re.IGNORECASE) is not None
            entry.set_visible(match)
            
            if entry.subtitle != current_country:
                exp = self.__expanders[current_expander_idx]
                exp.set_visible(visible_entries_in_current > 0)
                exp.set_expanded(visible_entries_in_current > 0)
                
                visible_entries_in_current = 0
                current_country = entry.subtitle
                current_expander_idx += 1
            
            if match:
                visible_entries_in_current += 1
        
        if current_expander_idx < len(self.__expanders):
            exp = self.__expanders[current_expander_idx]
            exp.set_visible(visible_entries_in_current > 0)
            exp.set_expanded(visible_entries_in_current > 0)

        self._block_signals = False

    def __on_row_toggle(self, btn, widget):
        if self._block_signals or not btn.get_active():
            return
        
        self._update_selection_labels(widget)
        self.router.set_next_enabled(True, caller=self)
