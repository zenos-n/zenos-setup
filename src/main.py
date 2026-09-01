import sys
import gi

# THIS MUST BE BEFORE ANY GI IMPORTS
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')

from gi.repository import Gtk, Gio, GLib, Adw
from gettext import gettext as _

from .window import ZenosSetupWindow
from .oobe import ZenWelcomeWindow

class ZenosSetupApplication(Adw.Application):
    """The main application singleton class."""

    def __init__(self, start_in_oobe=False):
        super().__init__(application_id='com.negzero.zenos.setup',
                         flags=Gio.ApplicationFlags.DEFAULT_FLAGS,
                         resource_base_path='/com/negzero/zenos/setup')
        self.start_in_oobe = start_in_oobe
        self.intro_played = False
        self.close_dialog = None

    def on_close(self, window):
        if not window.get_deletable():
            return True

        if self.close_dialog:
            self.close_dialog.present()
            return True

        dialog = Adw.MessageDialog(
            heading="Leave ZenOS Setup?",
            body="You can continue into the live desktop or shut this computer down.",
            transient_for=window,
        )
        dialog.add_response("live", "Try Live Mode")
        dialog.add_response("shutdown", "Shut Down")
        dialog.set_response_appearance("shutdown", Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.set_default_response("live")
        dialog.set_close_response("cancel")
        dialog.connect("response", self.on_close_response, window)
        self.close_dialog = dialog
        dialog.present()
        return True

    def on_close_response(self, dialog, response, window):
        self.close_dialog = None

        if response == "live":
            self.disable_oobe_mode()
            window.destroy()
            self.quit()
        elif response == "shutdown":
            self.trigger_shutdown()

    def disable_oobe_mode(self):
        try:
            bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
            proxy = Gio.DBusProxy.new_sync(
                bus,
                Gio.DBusProxyFlags.NONE,
                None,
                "org.gnome.Shell.Extensions",
                "/org/gnome/Shell/Extensions",
                "org.gnome.Shell.Extensions",
                None,
            )
            for method, uuid in (
                ("DisableExtension", "zenos-oobe-mode@neg-zero.com"),
                ("EnableExtension", "forge@jmmaranan.com"),
                ("EnableExtension", "AlphabeticalAppGrid@stuarthayhurst"),
                ("EnableExtension", "dash-stacks@neg-zero.com"),
                ("EnableExtension", "clipboard-indicator@tudmotu.com"),
            ):
                proxy.call_sync(
                    method,
                    GLib.Variant("(s)", (uuid,)),
                    Gio.DBusCallFlags.NONE,
                    -1,
                    None,
                )
        except Exception as error:
            print(f"failed to disable OOBE mode: {error}")

    def trigger_shutdown(self):
        bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        proxy = Gio.DBusProxy.new_sync(
            bus,
            Gio.DBusProxyFlags.NONE,
            None,
            "org.gnome.SessionManager",
            "/org/gnome/SessionManager",
            "org.gnome.SessionManager",
            None
        )

        try:
            proxy.call_sync("Shutdown", None, Gio.DBusCallFlags.NONE, -1, None)
        except Exception as error:
            print(f"failed to trigger shutdown: {error}")

    def do_activate(self):
        # if oobe flag is set and we haven't played the intro yet, show that first
        if self.start_in_oobe and not self.intro_played:
            win = ZenWelcomeWindow(application=self)
            win.connect("intro-skipped", self.on_intro_skipped)
            win.present()
        else:
            self.show_main_setup()

    def on_intro_skipped(self, window):
        self.intro_played = True
        window.destroy() # kill the video window
        self.show_main_setup() # launch the actual installer

    def show_main_setup(self):
        # find if the installer window is already active
        win = self.props.active_window
        if not isinstance(win, ZenosSetupWindow):
            win = ZenosSetupWindow(application=self, start_in_oobe=self.start_in_oobe)
            win.connect("close-request", self.on_close)

        win.present()

def main(version):
    """The application's entry point."""

    start_in_oobe = False
    if '--oobe' in sys.argv:
        start_in_oobe = True
        sys.argv.remove('--oobe')

    app = ZenosSetupApplication(start_in_oobe=start_in_oobe)
    return app.run(sys.argv)
