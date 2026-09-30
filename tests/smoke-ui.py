"""Exercise installed GTK defaults under Xvfb, without running the installer."""

from pathlib import Path
import sys
from types import SimpleNamespace

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gio, GLib, Gtk

root = Path(sys.argv[1]) / "share/zenos-setup"
sys.path.insert(0, str(root))
Gio.Resource.load(str(root / "zenos-setup.gresource"))._register()
Adw.init()

from zenos_setup import runner
from zenos_setup.builder import build_config_documents
from zenos_setup.state import InstallState
from zenos_setup.views.desktop_picker.logic import Page as Desktop
from zenos_setup.views.extra_software.logic import Page as Software
from zenos_setup.views.installer_welcome.logic import Page as InstallerWelcome
from zenos_setup.views.keyboard.logic import all_keyboards
from zenos_setup.views.oobe_welcome.logic import Page as OOBEWelcome
from zenos_setup.views.path_choice.logic import Page as PathChoice
from zenos_setup.views.recovery_mode.logic import Page as Recovery
from zenos_setup.views.shortcuts.logic import Page as Shortcuts
from zenos_setup.views.theme.logic import Page as Theme

assert runner.DRY_RUN
assert all_keyboards
state = InstallState()
router = SimpleNamespace(
    install_state=state,
    collect_state=lambda: None,
    carousel=Adw.Carousel(),
    carousel_steps=[],
    step_bins={},
)
recovery = Recovery(router)
assert not recovery.switch_ignore_ssl.get_active()
recovery.switch_ignore_ssl.set_active(True)
assert state.debugging == {"ignore_ssl_errors": True}
app_id = "com.negzero.zenos.setup"
desktop_entry = GLib.KeyFile()
desktop_entry.load_from_file(
    str(root.parent / "applications" / f"{app_id}.desktop"), GLib.KeyFileFlags.NONE
)
icons = [("desktop entry", desktop_entry.get_string("Desktop Entry", "Icon"), "zenos")]
for page_type, expected in (
    (InstallerWelcome, "zenos"),
    (OOBEWelcome, "zenos"),
    (PathChoice, "zenos-symbolic"),
):
    page = page_type(router)
    status = page.get_child()
    assert isinstance(status, Adw.StatusPage)
    icons.append((page_type.__gtype_name__, status.get_icon_name(), expected))
icon_theme = Gtk.IconTheme.get_for_display(page.get_display())
for source, icon_name, expected in icons:
    assert icon_name == expected, (source, icon_name)
    assert icon_theme.has_icon(icon_name), (source, icon_name)
    icon = icon_theme.lookup_icon(
        icon_name, None, 128, 1, Gtk.TextDirection.NONE, Gtk.IconLookupFlags(0)
    )
    kind = "symbolic" if icon_name.endswith("-symbolic") else "scalable"
    expected_file = root.parent / "icons/hicolor" / kind / "apps" / f"{icon_name}.svg"
    assert icon.get_file() is not None, (source, icon_name)
    assert icon.get_file().get_path() == str(expected_file), (source, icon.get_file())
    assert expected_file.is_file(), expected_file
print("PASS: installed welcome, OOBE, path-choice, and desktop icons resolve to packaged SVGs")
desktop = Desktop(router)
assert not desktop.radio_ii.get_sensitive()
state.set_page("desktop", desktop.get_finals())
assert state.get_page("desktop")["desktop_environment"] == "gnome"
assert state.get_page("desktop")["gnome_options"]["theme"]
shortcuts = Shortcuts(router)
assert shortcuts.get_finals() == {"directions": "vim", "actions": "zenos"}
state.set_page("shortcuts", shortcuts.get_finals())
theme = Theme(router)
state.set_page("theme", theme.get_finals())
software = Software(router)
software._rebuild_ui()
state.set_page("software", software.get_finals())
documents = build_config_documents(state.to_dict())
assert "dash-stacks" in documents["desktop.zcfg"]
assert "<Super>q" in documents["apps.zcfg"]
assert "adwaita-hacks" in documents["apps.zcfg"]
print("PASS: packaged GTK defaults, GResources, keyboard layouts, and GNOME rendering")

# The network rows must instantiate from their own GResource template and show
# real access points, including results arriving after the page first opens.
from unittest.mock import patch, Mock
from zenos_setup.views.internet import logic as internet

privacy = getattr(internet.NM, "80211ApFlags").PRIVACY

def access_point(ssid, strength, secure=False):
    return SimpleNamespace(
        get_ssid=lambda: GLib.Bytes.new(ssid),
        get_strength=lambda: strength,
        get_flags=lambda: privacy if secure else 0,
        get_wpa_flags=lambda: 0,
        get_rsn_flags=lambda: 0,
    )

connected_ap = access_point(b"Test Wi-Fi", 30, True)
stronger_ap = access_point(b"Test Wi-Fi", 90, True)
open_ap = access_point(b"Guest Wi-Fi", 60)
hidden_ap = access_point(b"", 70, True)
access_points = [connected_ap, stronger_ap, open_ap, hidden_ap]
scan = Mock()
wifi = SimpleNamespace(
    get_device_type=lambda: internet.NM.DeviceType.WIFI,
    get_access_points=lambda: access_points,
    get_active_access_point=lambda: connected_ap,
    request_scan_async=scan,
)
devices = []
network_client = SimpleNamespace(
    get_devices=lambda: devices,
    get_connectivity=lambda: internet.NM.ConnectivityState.NONE,
)
network_router = SimpleNamespace(set_next_enabled=Mock())
with patch.object(internet, "NetworkManagerClient", return_value=network_client):
    network = internet.Page(network_router)
    network._load_networks()
    assert not network._wifi_rows
    devices.append(wifi)
    network._load_networks(scan=True)
    scan.assert_called_once_with(None, network._on_scan_complete, None)
    assert len(network._wifi_rows) == 2
    connected, guest = network._wifi_rows
    assert isinstance(connected, internet.WirelessRow)
    assert connected.get_title() == "Test Wi-Fi"
    assert connected.secure and connected.connected_label.get_visible()
    assert connected.signal_icon.get_icon_name() == "network-wireless-signal-excellent-symbolic"
    assert guest.get_title() == "Guest Wi-Fi" and not guest.secure
    assert not guest.connected_label.get_visible()
    network._load_networks()
    assert network._wifi_rows[0] is connected
    access_points.clear()
    wifi.get_active_access_point = lambda: None
    network._load_networks()
    assert not network._wifi_rows
    network.check_once()
    network_router.set_next_enabled.assert_called_with(False, caller=network)
    GLib.source_remove(network._poll_id)

# Connections use wifi connect for both open and secured SSIDs; Ethernet uses
# the device name. Record commands without touching the sandbox's network.
class InlineThread:
    def __init__(self, target, **kwargs):
        self.target = target
    def start(self):
        self.target()

with patch.object(network, "start_connectivity_check"), \
     patch.object(internet.threading, "Thread", InlineThread), \
     patch.object(internet.subprocess, "run", return_value=SimpleNamespace(returncode=0, stderr="")) as run:
    network.connect_to_network("Guest Wi-Fi")
    assert run.call_args.args[0] == ["nmcli", "device", "wifi", "connect", "Guest Wi-Fi"]
    network.connect_to_network("Test Wi-Fi", "fixture-password", hidden=True)
    assert run.call_args.args[0] == ["nmcli", "device", "wifi", "connect", "Test Wi-Fi", "password", "fixture-password", "hidden", "yes"]
    network.connect_to_network("eth-test", wifi=False)
    assert run.call_args.args[0] == ["nmcli", "device", "connect", "eth-test"]
print("PASS: packaged Wi-Fi templates, delayed access points, deduplication, status, and connection commands")
