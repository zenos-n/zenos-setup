import subprocess
from gi.repository import Adw, Gtk

@Gtk.Template(resource_path='/com/negzero/zenos/setup/views/recovery_mode/layout.ui')
class Page(Adw.Bin):
    __gtype_name__ = 'ZenOSDefaultRecovery'

    # grab the rows from the xml
    row_terminal = Gtk.Template.Child()
    row_browser = Gtk.Template.Child()
    row_disk = Gtk.Template.Child()

    def __init__(self, router, **kwargs):
        super().__init__(**kwargs)
        self.router = router

        # hook up the click events
        self.row_disk.connect('activated', self.on_disk_clicked)
        self.row_browser.connect('activated', self.on_browser_clicked)
        self.row_terminal.connect('activated', self.on_terminal_clicked)

    def on_browser_clicked(self, *args):
        subprocess.Popen(['firefox'])

    def on_terminal_clicked(self, *args):
        subprocess.Popen(['kgx'])

    def on_disk_clicked(self, *args):
        subprocess.Popen(['gparted'])
