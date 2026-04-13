import os
import subprocess
import threading
import time
import gi

# Mock networks list (you can safely delete this without breaking the app)
class MockDevice:
    def __init__(self, name, type_val, strength=80):
        self.name = name
        self.type_val = type_val
        self.strength = strength

    def get_device_type(self):
        return self.type_val
    
    def get_iface(self):
        return self.name

# Fallback for gettext if not injected by the environment
try:
    _
except NameError:
    def _(text): return text

gi.require_version('Adw', '1')
gi.require_version('Gtk', '4.0')
from gi.repository import Adw, Gtk, GLib, Gio

# Gracefully handle missing NetworkManager namespace
try:
    gi.require_version('NM', '1.0')
    from gi.repository import NM
    HAS_NM = True
except (ValueError, ImportError):
    HAS_NM = False
    print("Warning: NetworkManager (NM) namespace not found. Using mock client.")

    class MockNMClient:
        def get_connectivity(self):
            return 4 # FULL

        def get_devices(self):
            return []

    class MockNM:
        class ConnectivityState:
            UNKNOWN = 0
            NONE = 1
            PORTAL = 2
            LIMITED = 3
            FULL = 4
        
        class DeviceType:
            ETHERNET = 1
            WIFI = 2
            
        class DeviceState:
            UNKNOWN = 0
            UNMANAGED = 10
            UNAVAILABLE = 20
            DISCONNECTED = 30
            PREPARE = 40
            CONFIG = 50
            NEED_AUTH = 60
            IP_CONFIG = 70
            IP_CHECK = 80
            SECONDARIES = 90
            ACTIVATED = 100
            DEACTIVATING = 110
            FAILED = 120
            
        class Client:
            @staticmethod
            def new(cancellable):
                return MockNMClient()
                
    NM = MockNM()

class NetworkManagerClient:
    def __init__(self):
        self.client = NM.Client.new(None)
        
    def get_connectivity(self):
        """returns the connectivity state (none, portal, limited, full)"""
        # Safely check if MOCK_NETWORKS is defined
        mock_nets = globals().get('MOCK_NETWORKS', [])
        if mock_nets:
            return 4 # NM.ConnectivityState.FULL
            
        return self.client.get_connectivity()

    def get_devices(self):
        """returns list of wifi and ethernet devices"""
        # Safely check if MOCK_NETWORKS is defined
        mock_nets = globals().get('MOCK_NETWORKS', [])
        if mock_nets:
            return mock_nets
            
        if not HAS_NM:
            return []
            
        devices = self.client.get_devices()
        return [d for d in devices if d.get_device_type() in (NM.DeviceType.WIFI, NM.DeviceType.ETHERNET)]

# --- Native Python Dialogs (to bypass buggy UI file extra-child mapping) ---

class PasswordDialog(Adw.MessageDialog):
    def __init__(self, ssid, parent=None, callback=None, **kwargs):
        super().__init__(**kwargs)
        self.callback = callback
        self.ssid = ssid
        self.set_heading(_("Wi-Fi Network"))
        self.set_body(_(f"Authentication required for {ssid}"))
        if parent:
            self.set_transient_for(parent)

        group = Adw.PreferencesGroup()
        self.password_entry = Adw.PasswordEntryRow(title=_("Password"))
        group.add(self.password_entry)
        self.set_extra_child(group)

        self.add_response("cancel", _("Cancel"))
        self.add_response("connect", _("Connect"))
        self.set_response_appearance("connect", Adw.ResponseAppearance.SUGGESTED)
        self.connect("response", self.on_response)

    def on_response(self, dialog, response):
        if response == "connect" and self.callback:
            self.callback(self.ssid, self.password_entry.get_text())
        self.close()

class HiddenNetworkDialog(Adw.MessageDialog):
    def __init__(self, parent=None, callback=None, **kwargs):
        super().__init__(**kwargs)
        self.callback = callback
        self.set_heading(_("Hidden Network"))
        self.set_body(_("Enter the details for the hidden Wi-Fi network."))
        if parent:
            self.set_transient_for(parent)

        group = Adw.PreferencesGroup()
        self.ssid_entry = Adw.EntryRow(title=_("Network Name (SSID)"))
        self.password_entry = Adw.PasswordEntryRow(title=_("Password"))
        group.add(self.ssid_entry)
        group.add(self.password_entry)
        self.set_extra_child(group)

        self.add_response("cancel", _("Cancel"))
        self.add_response("connect", _("Connect"))
        self.set_response_appearance("connect", Adw.ResponseAppearance.SUGGESTED)
        self.connect("response", self.on_response)

    def on_response(self, dialog, response):
        if response == "connect" and self.callback:
            self.callback(self.ssid_entry.get_text(), self.password_entry.get_text())
        self.close()

class ProxySettingsDialog(Adw.MessageDialog):
    def __init__(self, parent=None, **kwargs):
        super().__init__(**kwargs)
        self.set_heading(_("Proxy Settings"))
        self.set_body(_("Configure your network proxy settings below."))
        if parent:
            self.set_transient_for(parent)

        group = Adw.PreferencesGroup()
        self.proxy_entry = Adw.EntryRow(title=_("Proxy URL"))
        self.port_entry = Adw.EntryRow(title=_("Port"))
        group.add(self.proxy_entry)
        group.add(self.port_entry)
        self.set_extra_child(group)

        self.add_response("cancel", _("Cancel"))
        self.add_response("save", _("Save"))
        self.set_response_appearance("save", Adw.ResponseAppearance.SUGGESTED)
        self.connect("response", self.on_response)

    def on_response(self, dialog, response):
        if response == "save":
            print(f"Saving proxy settings: {self.proxy_entry.get_text()}:{self.port_entry.get_text()}")
            # Trigger save settings logic here
        self.close()


@Gtk.Template(resource_path='/com/negzero/zenos/setup/views/internet/wireless-row.ui')
class WirelessRow(Adw.ActionRow):
    __gtype_name__ = 'WirelessRow'
    
    signal_icon = Gtk.Template.Child()
    secure_icon = Gtk.Template.Child()
    connected_label = Gtk.Template.Child()
    
    def __init__(self, ssid, strength, secure=False, connected=False, **kwargs):
        super().__init__(**kwargs)
        self.set_title(ssid)
        self.set_activatable(True)
        self.secure = secure
        
        # Set icon dynamically based on signal strength
        icon_name = "network-wireless-signal-none-symbolic"
        if strength > 80:
            icon_name = "network-wireless-signal-excellent-symbolic"
        elif strength > 55:
            icon_name = "network-wireless-signal-good-symbolic"
        elif strength > 30:
            icon_name = "network-wireless-signal-ok-symbolic"
        elif strength > 0:
            icon_name = "network-wireless-signal-weak-symbolic"
            
        self.signal_icon.set_from_icon_name(icon_name)
        self.secure_icon.set_visible(secure)
        self.connected_label.set_visible(connected)
        
        # Add clickable chevron suffix
        self.add_suffix(Gtk.Image(icon_name="go-next-symbolic"))


@Gtk.Template(resource_path='/com/negzero/zenos/setup/views/internet/layout.ui')
class Page(Adw.Bin):
    __gtype_name__ = 'ZenOSDefaultNetwork'

    # next button is locked until we have a confirmed internet connection
    MANIFEST = {
        "gated": True
    }

    # widgets from layout.ui
    main_stack = Gtk.Template.Child()
    status_page = Gtk.Template.Child()
    loading_spinner = Gtk.Template.Child()
    btn_recheck = Gtk.Template.Child()
    btn_next = Gtk.Template.Child()
    
    wired_group = Gtk.Template.Child()
    wireless_group = Gtk.Template.Child()
    network_spinner_row = Gtk.Template.Child()
    network_spinner = Gtk.Template.Child()

    hidden_network_row = Gtk.Template.Child()
    proxy_settings_row = Gtk.Template.Child()

    def __init__(self, router, **kwargs):
        super().__init__(**kwargs)
        self.router = router
        self.nm = NetworkManagerClient()
        self._check_active = False
        
        # Track rows to avoid looping over GTK internal group widgets safely
        self._wifi_rows = []
        self._wired_rows = []

        # Make sure advanced rows are interactive and have chevrons
        self.hidden_network_row.set_activatable(True)
        self.hidden_network_row.add_suffix(Gtk.Image(icon_name="go-next-symbolic"))
        
        self.proxy_settings_row.set_activatable(True)
        self.proxy_settings_row.add_suffix(Gtk.Image(icon_name="go-next-symbolic"))

        # Connect rows and buttons to actions
        self.hidden_network_row.connect("activated", self.on_open_hidden_network)
        self.proxy_settings_row.connect("activated", self.on_open_proxy)
        self.btn_recheck.connect("clicked", self.on_recheck_clicked)
        self.btn_next.connect("clicked", self.on_next_clicked)

        # start the background connectivity loop & wifi scan
        self.start_connectivity_check()

    def on_open_hidden_network(self, *args):
        dialog = HiddenNetworkDialog(parent=self.get_root(), callback=self.connect_to_network)
        dialog.present()

    def on_open_proxy(self, *args):
        dialog = ProxySettingsDialog(parent=self.get_root())
        dialog.present()

    def on_network_clicked(self, row):
        ssid = row.get_title()
        # If it's a Wi-Fi network and it's secure, ask for password first
        if isinstance(row, WirelessRow) and row.secure:
            dialog = PasswordDialog(ssid=ssid, parent=self.get_root(), callback=self.connect_to_network)
            dialog.present()
        else:
            self.connect_to_network(ssid)
            
    def connect_to_network(self, ssid, password=None):
        print(f"Connecting to network: {ssid} | Password provided: {'Yes' if password else 'No'}")
        # Normally you would hook up the NMClient to establish the connection here
        # For now, we simulate attempting a connection by spinning the UI
        self.start_connectivity_check()
        
    def on_recheck_clicked(self, *args):
        self.start_connectivity_check()
        
    def on_next_clicked(self, *args):
        if hasattr(self.router, 'next'):
            self.router.next()

    def start_connectivity_check(self):
        if self._check_active:
            return
        
        self._check_active = True
        self.main_stack.set_visible_child_name("checking")
        self.loading_spinner.set_visible(True)
        self.loading_spinner.start()
        self.btn_recheck.set_sensitive(False)
        
        # Prepare network lists for scanning state
        self.wireless_group.set_visible(True)
        self.network_spinner_row.set_visible(True)
        self.network_spinner.start()
        
        # Safely remove existing rows
        for row in self._wifi_rows:
            self.wireless_group.remove(row)
        self._wifi_rows.clear()
        
        for row in self._wired_rows:
            self.wired_group.remove(row)
        self._wired_rows.clear()

        # Run checks in background to avoid freezing the UI thread
        threading.Thread(target=self._connectivity_loop, daemon=True).start()
        threading.Thread(target=self._load_networks_thread, daemon=True).start()

    def _load_networks_thread(self):
        # Brief sleep for visual realism of scanning
        time.sleep(1.0)
        
        has_wifi_device = False
        has_wired_device = False
        wifi_networks = []
        wired_networks = []
        
        devices = self.nm.get_devices()
        for d in devices:
            is_mock = hasattr(d, 'type_val')
            
            if is_mock:
                is_wifi = (d.get_device_type() == 2)
                is_eth = (d.get_device_type() == 1)
            else:
                is_wifi = (d.get_device_type() == NM.DeviceType.WIFI)
                is_eth = (d.get_device_type() == NM.DeviceType.ETHERNET)

            if is_wifi:
                has_wifi_device = True
                if not is_mock and HAS_NM:
                    try:
                        for ap in d.get_access_points():
                            ssid_bytes = ap.get_ssid()
                            if ssid_bytes:
                                ssid = ssid_bytes.get_data().decode('utf-8', errors='ignore')
                            else:
                                ssid = "Hidden Network"
                                
                            strength = ap.get_strength()
                            # Check encryption capabilities
                            flags = ap.get_flags()
                            wpa_flags = ap.get_wpa_flags()
                            rsn_flags = ap.get_rsn_flags()
                            secure = bool(flags or wpa_flags or rsn_flags)
                            
                            wifi_networks.append({
                                "ssid": ssid,
                                "strength": strength,
                                "secure": secure
                            })
                    except Exception as e:
                        print(f"Failed to fetch real APs for {d.get_iface()}: {e}")
                else:
                    # MOCK fallback mapping
                    wifi_networks.append({
                        "ssid": d.name,
                        "strength": getattr(d, 'strength', 60),
                        "secure": True
                    })
                    
            elif is_eth:
                has_wired_device = True
                if not is_mock and HAS_NM:
                    try:
                        is_connected = d.get_state() == NM.DeviceState.ACTIVATED
                    except Exception:
                        is_connected = False
                    wired_networks.append({
                        "name": d.get_iface(),
                        "connected": is_connected
                    })
                else:
                    # MOCK fallback mapping
                    wired_networks.append({
                        "name": d.name,
                        "connected": True
                    })
                    
        # safely push updates back to main GTK thread
        GLib.idle_add(self._update_networks_ui, has_wifi_device, wifi_networks, has_wired_device, wired_networks)

    def _update_networks_ui(self, has_wifi_device, wifi_networks, has_wired_device, wired_networks):
        self.network_spinner.stop()
        self.network_spinner_row.set_visible(False)
        
        # --- Handle Wired Group ---
        if has_wired_device and wired_networks:
            self.wired_group.set_visible(True)
            for net in wired_networks:
                row = Adw.ActionRow()
                row.set_title(net["name"])
                row.set_activatable(True)
                row.connect("activated", self.on_network_clicked)
                
                if net.get("connected"):
                    row.set_subtitle(_("Connected"))
                else:
                    row.set_subtitle(_("Disconnected"))
                    
                icon = Gtk.Image()
                icon.set_from_icon_name("network-wired-symbolic")
                icon.set_margin_start(5)
                icon.set_margin_end(5)
                row.add_prefix(icon)
                row.add_suffix(Gtk.Image(icon_name="go-next-symbolic"))
                
                self.wired_group.add(row)
                self._wired_rows.append(row)
        else:
            self.wired_group.set_visible(False)
        
        # --- Handle Wireless Group ---
        if not has_wifi_device:
            self.wireless_group.set_visible(False)
        else:
            self.wireless_group.set_visible(True)
            # Deduplicate access points by SSID, retaining the strongest signal version
            unique_nets = {}
            for n in wifi_networks:
                ssid = n["ssid"]
                if not ssid: 
                    continue
                if ssid not in unique_nets or unique_nets[ssid]["strength"] < n["strength"]:
                    unique_nets[ssid] = n
                    
            sorted_nets = sorted(unique_nets.values(), key=lambda x: x["strength"], reverse=True)
            
            # Populate the actual rows
            for net in sorted_nets:
                row = WirelessRow(
                    ssid=net["ssid"],
                    strength=net["strength"],
                    secure=net.get("secure", False),
                    connected=False # Logic to flag active connection can go here
                )
                row.connect("activated", self.on_network_clicked)
                self.wireless_group.add(row)
                self._wifi_rows.append(row)

    def _connectivity_loop(self):
        while self._check_active:
            state = self.nm.get_connectivity()
            
            # states: 4 (FULL), 3 (LIMITED), 2 (PORTAL), 1 (NONE)
            is_connected = state == NM.ConnectivityState.FULL
            
            GLib.idle_add(self._update_ui_state, state, is_connected)
            
            # if we found it, we can stop the aggressive loop and slow down
            if is_connected:
                GLib.idle_add(self._start_slow_polling)
                self._check_active = False
                break
            
            time.sleep(2)

    def _start_slow_polling(self):
        # keep it alive but check less often to see if they pull the plug
        GLib.timeout_add_seconds(5, self.check_once)
        return False # Remove idle source

    def check_once(self):
        state = self.nm.get_connectivity()
        is_connected = state == NM.ConnectivityState.FULL
        self._update_ui_state(state, is_connected)
        return True # keep timeout alive

    def _update_ui_state(self, state, is_connected):
        # sync with the router's button gating system
        if hasattr(self.router, 'set_next_enabled'):
            self.router.set_next_enabled(is_connected)
            
        self.btn_next.set_sensitive(is_connected)
        
        # Switch away from the loading view upon first result
        if self.main_stack.get_visible_child_name() == "checking":
            self.main_stack.set_visible_child_name("network")
            self.loading_spinner.stop()
            self.btn_recheck.set_sensitive(True)
        
        # update the status page text
        if is_connected:
            self.status_page.set_title(_("Connected"))
            self.status_page.set_description(_("You're ready to proceed with the installation."))
            self.status_page.set_icon_name("network-transmit-receive-symbolic")
        elif state == NM.ConnectivityState.PORTAL:
            self.status_page.set_title(_("Action Required"))
            self.status_page.set_description(_("You are connected to a network, but need to log in to the portal."))
            self.status_page.set_icon_name("network-wireless-acquiring-symbolic")
        else:
            self.status_page.set_title(_("Internet"))
            self.status_page.set_description(_("An active internet connection is required to install the system."))
            self.status_page.set_icon_name("network-error-symbolic")

    def get_finals(self):
        # if there are any specific network configs we need to save, we'd do it here
        return {
            "network_status": "connected" if self.nm.get_connectivity() == NM.ConnectivityState.FULL else "disconnected"
        }
