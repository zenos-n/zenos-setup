from gi.repository import Gtk, Adw, GObject

@Gtk.Template(resource_path='/com/negzero/zenos/setup/views/progress/layout.ui')
class Page(Gtk.Box):
    __gtype_name__ = 'ZenOSDefaultProgress'

    # mapping the ui definitions to the class
    carousel_tour = Gtk.Template.Child()
    tour_btn_back = Gtk.Template.Child()
    tour_btn_next = Gtk.Template.Child()
    tour_box = Gtk.Template.Child()
    console_box = Gtk.Template.Child()
    console_button = Gtk.Template.Child()
    tour_button = Gtk.Template.Child()
    progressbar = Gtk.Template.Child()

    MANIFEST = {
        "gated": True,
        "unclosable": True
    }

    def __init__(self, router, **kwargs):
        super().__init__(**kwargs)
        self.router = router
        self.install_state = None

        # hook up the slideshow nav
        self.tour_btn_back.connect("clicked", self._on_tour_prev)
        self.tour_btn_next.connect("clicked", self._on_tour_next)
        self.carousel_tour.connect("page-changed", self._update_tour_buttons)

        # toggle between console and tour
        self.console_button.connect("clicked", self._show_console)
        self.tour_button.connect("clicked", self._show_tour)

        # collect all page state before doing anything else
        self.install_state = self.router.collect_state()
        print("[+] install state collected:")
        print(self.install_state.to_json(indent=2))

        # TODO: hand self.install_state to your util here
        # e.g. threading.Thread(target=run_my_util, args=(self.install_state,), daemon=True).start()

        # fake progress for testing
        GObject.timeout_add(100, self._fake_progress)

    def _on_tour_next(self, _):
        current = self.carousel_tour.get_nth_page(self.carousel_tour.get_position())
        # adw.carousel doesn't have a simple "next", so we grab the next widget
        # this is assuming you've appended pages to carousel_tour elsewhere
        pass

    def _on_tour_prev(self, _):
        pass

    def _update_tour_buttons(self, *args):
        # logic to hide/show buttons based on carousel position
        pos = self.carousel_tour.get_position()
        self.tour_btn_back.set_visible(pos > 0)
        # add logic for the end of the carousel here

    def _show_console(self, _):
        self.tour_box.set_visible(False)
        self.console_box.set_visible(True)
        self.console_button.set_visible(False)
        self.tour_button.set_visible(True)

    def _show_tour(self, _):
        self.console_box.set_visible(False)
        self.tour_box.set_visible(True)
        self.tour_button.set_visible(False)
        self.console_button.set_visible(True)

    def _fake_progress(self):
        val = self.progressbar.get_fraction()
        if val < 1.0:
            self.progressbar.set_fraction(val + 0.01)
            return True
        self.router.set_next_enabled(True, caller=self)
        return False
