from gi.repository import Adw, Gtk

@Gtk.Template(resource_path='/com/negzero/zenos/setup/views/installer_welcome/layout.ui')
class Page(Adw.Bin):
    __gtype_name__ = 'ZenOSDefaultInstallerWelcome'

    # grab the rows from the xml
    row_install = Gtk.Template.Child()
    row_recovery = Gtk.Template.Child()

    def __init__(self, router, **kwargs):
        super().__init__(**kwargs)
        self.router = router

        # hook up the click events
        self.row_install.connect('activated', self.on_install_clicked)
        self.row_recovery.connect('activated', self.on_recovery_clicked)

    def on_install_clicked(self, *args):
        # tells the router we picked the 'install' branch
        self.router.navigate_next("install")

    def on_recovery_clicked(self, *args):
        self.router.navigate_next("recovery")
