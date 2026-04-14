from gi.repository import Adw, Gtk

@Gtk.Template(resource_path='/com/negzero/zenos/setup/views/path_choice/layout.ui')
class Page(Adw.Bin):
    __gtype_name__ = 'ZenOSDefaultPath'

    # grab the rows from the xml
    btn_now = Gtk.Template.Child()
    btn_setup = Gtk.Template.Child()

    def __init__(self, router, **kwargs):
        super().__init__(**kwargs)
        self.router = router

        # hook up the click events
        self.btn_now.connect('activated', self.on_now_clicked)
        self.btn_setup.connect('activated', self.on_manual_clicked)

    def on_now_clicked(self, *args):
        # tells the router we picked the 'install' branch
        self.router.navigate_next("run_install_script")

    def on_manual_clicked(self, *args):
        self.router.navigate_next("oobe_config_start")
