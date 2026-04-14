import subprocess
from gi.repository import Adw, Gtk, GObject

@Gtk.Template(resource_path='/com/negzero/zenos/setup/views/reboot/layout.ui')
class Page(Adw.Bin):
    __gtype_name__ = 'ZenOSRebootPage'

    MANIFEST = {
        "gated": True,       # hide the router's 'next' button
        "unclosable": True   # prevent alt+f4 during this stage
    }

    def __init__(self, router, **kwargs):
        super().__init__(**kwargs)
        self.router = router

    @Gtk.Template.Callback()
    def on_reboot_clicked(self, button):
        print("[!] rebooting system...")
        try:
            # use pkexec if you need auth, but usually installers run as root
            subprocess.run(["systemctl", "reboot"], check=True)
        except Exception as e:
            print(f"[-] reboot failed: {e}")
