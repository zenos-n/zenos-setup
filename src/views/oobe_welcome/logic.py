from gi.repository import Adw, Gtk

@Gtk.Template(resource_path='/com/negzero/zenos/setup/views/oobe_welcome/layout.ui')
class Page(Adw.Bin):
    __gtype_name__ = 'ZenOSDefaultOOBEWelcome'

    # grab the rows from the xml
    next_btn = Gtk.Template.Child()

    def __init__(self, router, **kwargs):
        super().__init__(**kwargs)
        self.router = router

        # hook up the click events
        self.next_btn.connect('clicked', self.on_next_clicked)

    def on_next_clicked(self, *args):
        self.router.navigate_next("start")

