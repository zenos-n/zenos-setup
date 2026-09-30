import os
import subprocess
import threading
import gi

# Fallback for gettext if not injected by the environment
try:
    _
except NameError:
    def _(text): return text

gi.require_version('Adw', '1')
gi.require_version('Gtk', '4.0')
from gi.repository import Adw, Gtk, Gdk, GLib, Gio

# --- CSS Injection for Transparent Spinner Row ---
CSS_DATA = """
.transparent-row {
    background-color: transparent;
    border: none;
    box-shadow: none;
}
"""

def apply_custom_styles():
    provider = Gtk.CssProvider()
    provider.load_from_data(CSS_DATA.encode())
    Gtk.StyleContext.add_provider_for_display(
        Gdk.Display.get_default(),
        provider,
        Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
    )

# Gracefully handle missing NetworkManager namespace
try:
    gi.require_version('NM', '1.0')
    from gi.repository import NM
    HAS_NM = True
except (ValueError, ImportError):
    HAS_NM = False

    class MockNMClient:
        def get_connectivity(self): return 0
        def get_devices(self): return []
    class MockNM:
        class ConnectivityState: UNKNOWN=0; NONE=1; PORTAL=2; LIMITED=3; FULL=4
        class DeviceType: ETHERNET=1; WIFI=2
        class DeviceState: ACTIVATED=100
        class Client:
            @staticmethod
            def new(cancellable): return MockNMClient()
    NM = MockNM()

class NetworkManagerClient:
    def __init__(self):
        self.client = NM.Client.new(None)
    def get_connectivity(self):
        return self.client.get_connectivity()
    def get_devices(self):
        if not HAS_NM: return []
        devices = self.client.get_devices()
        return [d for d in devices if d.get_device_type() in (NM.DeviceType.WIFI, NM.DeviceType.ETHERNET)]

class PasswordDialog(Adw.MessageDialog):
    def __init__(self, ssid, parent=None, callback=None, **kwargs):
        super().__init__(**kwargs)
        self.callback, self.ssid = callback, ssid
        self.set_heading(_("Wi-Fi Network"))
        self.set_body(_(f"Authentication required for {ssid}"))
        if parent: self.set_transient_for(parent)
        group = Adw.PreferencesGroup()
        self.password_entry = Adw.PasswordEntryRow(title=_("Password"))
        group.add(self.password_entry)
        self.set_extra_child(group)
        self.add_response("cancel", _("Cancel"))
        self.add_response("connect", _("Connect"))
        self.set_response_appearance("connect", Adw.ResponseAppearance.SUGGESTED)
        self.connect("response", self.on_response)
    def on_response(self, dialog, response):
        if response == "connect" and self.callback: self.callback(self.ssid, self.password_entry.get_text())
        self.close()

# Split UI files to fix template collision
@Gtk.Template(resource_path='/com/negzero/zenos/setup/views/internet/hidden-network-dialog.ui')
class HiddenNetworkDialog(Adw.MessageDialog):
    __gtype_name__ = 'HiddenNetworkDialog'

    ssid_entry = Gtk.Template.Child()
    password_entry = Gtk.Template.Child()

    def __init__(self, parent=None, callback=None, **kwargs):
        super().__init__(**kwargs)
        self.callback = callback
        if parent: self.set_transient_for(parent)
        self.add_response("cancel", _("Cancel"))
        self.add_response("connect", _("Connect"))
        self.set_response_appearance("connect", Adw.ResponseAppearance.SUGGESTED)
        self.connect("response", self.on_response)

    def on_response(self, dialog, response):
        if response == "connect" and self.callback:
            self.callback(self.ssid_entry.get_text(), self.password_entry.get_text())
        self.close()

@Gtk.Template(resource_path='/com/negzero/zenos/setup/views/internet/proxy-settings-dialog.ui')
class ProxySettingsDialog(Adw.MessageDialog):
    __gtype_name__ = 'ProxySettingsDialog'

    proxy_switch = Gtk.Template.Child()
    proxy_entry = Gtk.Template.Child()
    port_entry = Gtk.Template.Child()

    def __init__(self, parent=None, **kwargs):
        super().__init__(**kwargs)
        if parent: self.set_transient_for(parent)

        self.add_response("cancel", _("Cancel"))
        self.add_response("save", _("Save"))
        self.set_response_appearance("save", Adw.ResponseAppearance.SUGGESTED)

        self.connect("response", self.on_response)
        self.proxy_switch.connect("notify::active", self.on_switch_toggled)

        # load active config from dconf/gsettings
        try:
            proxy_settings = Gio.Settings.new("org.gnome.system.proxy")
            http_settings = Gio.Settings.new("org.gnome.system.proxy.http")

            mode = proxy_settings.get_string("mode")
            self.proxy_switch.set_active(mode == "manual")
            self.proxy_entry.set_text(http_settings.get_string("host"))

            port = http_settings.get_int("port")
            if port > 0:
                self.port_entry.set_text(str(port))
        except Exception as e:
            print(f"Failed to read proxy settings: {e}")

        self.on_switch_toggled()

    def on_switch_toggled(self, *args):
        active = self.proxy_switch.get_active()
        self.proxy_entry.set_sensitive(active)
        self.port_entry.set_sensitive(active)

    def on_response(self, dialog, response):
        if response == "save":
            try:
                proxy_settings = Gio.Settings.new("org.gnome.system.proxy")
                active = self.proxy_switch.get_active()

                proxy_settings.set_string("mode", "manual" if active else "none")

                if active:
                    host = self.proxy_entry.get_text()
                    port_str = self.port_entry.get_text()
                    port = int(port_str) if port_str.isdigit() else 8080

                    # wire up the main protocols
                    for protocol in ['http', 'https', 'ftp', 'socks']:
                        proto_settings = Gio.Settings.new(f"org.gnome.system.proxy.{protocol}")
                        proto_settings.set_string("host", host)
                        proto_settings.set_int("port", port)
            except Exception as e:
                print(f"Failed to write proxy settings: {e}")
        self.close()

class AdvancedSettingsDialog(Adw.MessageDialog):
    def __init__(self, parent=None, **kwargs):
        super().__init__(**kwargs)
        self.set_heading(_("Advanced Settings"))
        if parent: self.set_transient_for(parent)
        group = Adw.PreferencesGroup()
        group.add(Adw.EntryRow(title=_("IP Address")))
        group.add(Adw.EntryRow(title=_("Subnet Mask")))
        group.add(Adw.EntryRow(title=_("Gateway")))
        group.add(Adw.EntryRow(title=_("DNS Server")))
        self.set_extra_child(group)
        self.add_response("cancel", _("Cancel"))
        self.add_response("save", _("Save"))
        self.set_response_appearance("save", Adw.ResponseAppearance.SUGGESTED)
        self.connect("response", lambda d, r: self.close())

@Gtk.Template(resource_path='/com/negzero/zenos/setup/views/internet/wireless-row.ui')
class WirelessRow(Adw.ActionRow):
    __gtype_name__ = 'WirelessRow'
    signal_icon = Gtk.Template.Child()
    secure_icon = Gtk.Template.Child()
    connected_label = Gtk.Template.Child()
    def __init__(self, ssid, strength, secure=False, connected=False, **kwargs):
        super().__init__(**kwargs)
        self.set_title(ssid); self.set_activatable(True)
        self.secure = secure
        icon_name = "network-wireless-signal-none-symbolic"
        if strength > 80: icon_name = "network-wireless-signal-excellent-symbolic"
        elif strength > 55: icon_name = "network-wireless-signal-good-symbolic"
        elif strength > 30: icon_name = "network-wireless-signal-ok-symbolic"
        self.signal_icon.set_from_icon_name(icon_name)
        self.secure_icon.set_visible(secure)
        self.connected_label.set_visible(connected)
        self.add_suffix(Gtk.Image(icon_name="go-next-symbolic"))

@Gtk.Template(resource_path='/com/negzero/zenos/setup/views/internet/layout.ui')
class Page(Adw.Bin):
    __gtype_name__ = 'ZenOSDefaultNetwork'
    MANIFEST = {"gated": True}

    main_stack = Gtk.Template.Child()
    status_page = Gtk.Template.Child()
    loading_spinner = Gtk.Template.Child()
    btn_recheck = Gtk.Template.Child()
    wired_group = Gtk.Template.Child()
    wireless_group = Gtk.Template.Child()
    network_spinner_row = Gtk.Template.Child()
    network_spinner = Gtk.Template.Child()
    hidden_network_row = Gtk.Template.Child()
    proxy_settings_row = Gtk.Template.Child()
    advanced_settings_row = Gtk.Template.Child()

    def __init__(self, router, **kwargs):
        super().__init__(**kwargs)
        self.router = router
        self.nm = NetworkManagerClient()
        self._wifi_rows, self._wired_rows = [], []

        apply_custom_styles()

        self.hidden_network_row.set_activatable(True)
        self.hidden_network_row.add_suffix(Gtk.Image(icon_name="go-next-symbolic"))
        self.proxy_settings_row.set_activatable(True)
        self.proxy_settings_row.add_suffix(Gtk.Image(icon_name="go-next-symbolic"))
        self.advanced_settings_row.set_activatable(True)
        self.advanced_settings_row.add_suffix(Gtk.Image(icon_name="go-next-symbolic"))

        self.hidden_network_row.connect("activated", self.on_open_hidden_network)
        self.proxy_settings_row.connect("activated", self.on_open_proxy)
        self.advanced_settings_row.connect("activated", self.on_open_advanced)
        self.btn_recheck.connect("clicked", self.on_recheck_clicked)
        self._poll_id = 0
        self._network_snapshot = None
        self.start_connectivity_check()

    def on_open_hidden_network(self, *args):
        HiddenNetworkDialog(parent=self.get_root(), callback=lambda ssid, password: self.connect_to_network(ssid, password, hidden=True)).present()

    def on_open_proxy(self, *args):
        ProxySettingsDialog(parent=self.get_root()).present()

    def on_open_advanced(self, *args):
        AdvancedSettingsDialog(parent=self.get_root()).present()

    def on_network_clicked(self, row):
        ssid = row.get_title()
        if isinstance(row, WirelessRow):
            if row.secure:
                PasswordDialog(ssid=ssid, parent=self.get_root(), callback=self.connect_to_network).present()
            else:
                self.connect_to_network(ssid)
        else:
            self.connect_to_network(ssid, wifi=False)
            
    def connect_to_network(self, ssid, password=None, *, wifi=True, hidden=False):
        self.start_connectivity_check()
        
        def do_connect():
            try:
                if wifi:
                    command = ['nmcli', 'device', 'wifi', 'connect', ssid]
                    if password:
                        command += ['password', password]
                    if hidden:
                        command += ['hidden', 'yes']
                else:
                    command = ['nmcli', 'device', 'connect', ssid]
                result = subprocess.run(command, capture_output=True, text=True)
                if result.returncode:
                    print(f"Network connection failure: {result.stderr.strip()}")
                GLib.idle_add(self._check_once_idle)
            except Exception as e:
                print(f"Network connection failure: {e}")

        threading.Thread(target=do_connect, daemon=True).start()

    def on_recheck_clicked(self, *args):
        self.start_connectivity_check()
        
    def start_connectivity_check(self):
        self.main_stack.set_visible_child_name("checking")
        self.loading_spinner.start()
        self.btn_recheck.set_sensitive(False)
        self.network_spinner_row.set_visible(True)
        self.network_spinner.start()
        # NM.Client belongs to GTK's main context; keep all cache reads there.
        GLib.idle_add(self._load_networks, True)
        GLib.idle_add(self._check_once_idle)
        if not self._poll_id:
            self._poll_id = GLib.timeout_add_seconds(3, self.check_once)

    def _load_networks(self, scan=False):
        has_wifi, has_wired = False, False
        wifi_by_ssid, wired_nets = {}, []
        for device in self.nm.get_devices():
            if device.get_device_type() == NM.DeviceType.WIFI:
                has_wifi = True
                if scan:
                    device.request_scan_async(None, self._on_scan_complete, None)
                active_ap = device.get_active_access_point()
                active_ssid = active_ap.get_ssid().get_data() if active_ap and active_ap.get_ssid() else None
                for ap in device.get_access_points():
                    ssid = ap.get_ssid()
                    if not ssid or not ssid.get_data():
                        continue
                    raw_ssid = ssid.get_data()
                    secure = bool(ap.get_flags() & getattr(NM, "80211ApFlags").PRIVACY or ap.get_wpa_flags() or ap.get_rsn_flags())
                    network = {
                        "ssid": raw_ssid.decode("utf-8", errors="replace"),
                        "strength": ap.get_strength(),
                        "secure": secure,
                        "connected": raw_ssid == active_ssid,
                    }
                    key = (raw_ssid, secure)
                    previous = wifi_by_ssid.get(key)
                    if previous is None or network["strength"] > previous["strength"]:
                        if previous:
                            network["connected"] |= previous["connected"]
                        wifi_by_ssid[key] = network
                    elif network["connected"]:
                        previous["connected"] = True
            elif device.get_device_type() == NM.DeviceType.ETHERNET:
                has_wired = True
                wired_nets.append({"name": device.get_iface(), "connected": device.get_state() == NM.DeviceState.ACTIVATED})
        wifi_nets = sorted(wifi_by_ssid.values(), key=lambda net: (not net["connected"], -net["strength"], net["ssid"]))
        snapshot = (has_wifi, wifi_nets, has_wired, wired_nets)
        if snapshot != self._network_snapshot or scan:
            self._update_networks_ui(*snapshot)
            self._network_snapshot = snapshot
        return False

    def _on_scan_complete(self, device, result, *args):
        try:
            device.request_scan_finish(result)
        except GLib.Error as error:
            print(f"Wi-Fi scan failed: {error}")
        self._load_networks()

    def _update_networks_ui(self, has_wifi, wifi_nets, has_wired, wired_nets):
        self.network_spinner.stop()
        self.network_spinner_row.set_visible(False)
        for row in self._wifi_rows:
            self.wireless_group.remove(row)
        self._wifi_rows.clear()
        for row in self._wired_rows:
            self.wired_group.remove(row)
        self._wired_rows.clear()
        self.wired_group.set_visible(has_wired)
        for net in wired_nets:
            row = Adw.ActionRow(title=net["name"], subtitle=_("Connected") if net["connected"] else _("Disconnected"))
            row.set_activatable(True); row.connect("activated", self.on_network_clicked)
            icon = Gtk.Image(icon_name="network-wired-symbolic")
            row.add_prefix(icon); row.add_suffix(Gtk.Image(icon_name="go-next-symbolic"))
            self.wired_group.add(row); self._wired_rows.append(row)
        self.wireless_group.set_visible(has_wifi)
        for net in wifi_nets:
            row = WirelessRow(ssid=net["ssid"], strength=net["strength"], secure=net["secure"], connected=net["connected"])
            row.connect("activated", self.on_network_clicked)
            self.wireless_group.add(row); self._wifi_rows.append(row)

    def _check_once_idle(self):
        self.check_once()
        return False

    def check_once(self):
        state = self.nm.get_connectivity()
        self._update_ui_state(state, state == NM.ConnectivityState.FULL)
        self._load_networks()
        return True

    def _update_ui_state(self, state, is_connected):
        self.router.set_next_enabled(is_connected, caller=self)
        if self.main_stack.get_visible_child_name() == "checking":
            self.main_stack.set_visible_child_name("network")
            self.loading_spinner.stop()
            self.btn_recheck.set_sensitive(True)
        if is_connected:
            self.status_page.set_title(_("Connected"))
            self.status_page.set_icon_name("network-transmit-receive-symbolic")
        else:
            self.status_page.set_title(_("Internet"))
            self.status_page.set_icon_name("network-error-symbolic")

    def get_finals(self):
        return {"network_status": "connected" if self.nm.get_connectivity() == 4 else "disconnected"}
