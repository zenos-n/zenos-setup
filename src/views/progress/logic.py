import threading

from gi.repository import Gtk, Adw, GObject, GLib

from zenos_setup.runner import run_installer

@Gtk.Template(resource_path='/com/negzero/zenos/setup/views/progress/layout.ui')
class Page(Gtk.Box):
    __gtype_name__ = 'ZenOSDefaultProgress'

    carousel_tour    = Gtk.Template.Child()
    tour_box         = Gtk.Template.Child()
    console_box      = Gtk.Template.Child()
    console_button   = Gtk.Template.Child()
    tour_button      = Gtk.Template.Child()
    progressbar      = Gtk.Template.Child()
    progressbar_text = Gtk.Template.Child()

    MANIFEST = {
        "gated": True,
        "unclosable": True,
    }

    def __init__(self, router, **kwargs):
        super().__init__(**kwargs)
        self.router = router

        # --- tour nav ---
        self.carousel_tour.connect("page-changed", self._update_tour_buttons)
        self.console_button.connect("clicked", self._show_console)
        self.tour_button.connect("clicked", self._show_tour)

        # --- build a proper scrolled log view and inject it into console_box ---
        self._log_buffer = Gtk.TextBuffer()
        self._log_view   = Gtk.TextView(
            buffer=self._log_buffer,
            editable=False,
            cursor_visible=False,
            monospace=True,
            wrap_mode=Gtk.WrapMode.WORD_CHAR,
            margin_top=12,
            margin_bottom=12,
            margin_start=12,
            margin_end=12,
        )
        self._log_view.add_css_class("dim-label")

        log_scroll = Gtk.ScrolledWindow(
            vexpand=True,
            hexpand=True,
            hscrollbar_policy=Gtk.PolicyType.NEVER,
            vscrollbar_policy=Gtk.PolicyType.AUTOMATIC,
            min_content_height=200,
        )
        log_scroll.set_child(self._log_view)
        self.console_box.append(log_scroll)

        # --- collect install state and start the real installer ---
        self.install_state = self.router.collect_state()
        self._start_installer()

    # ------------------------------------------------------------------ runner

    def _start_installer(self):
        """Hand off to runner.py in a background thread."""
        self._set_status("Installing…")
        self.progressbar.set_fraction(0.0)

        run_installer(
            self.install_state,
            progress_fn=self._on_progress,
            log_fn=self._on_log,
            done_fn=self._on_done,
        )

    # --- thread-safe callbacks (runner calls these from a worker thread) ---

    def _on_progress(self, value: float):
        GLib.idle_add(self._apply_progress, value)

    def _on_log(self, line: str):
        GLib.idle_add(self._append_log, line)

    def _on_done(self, success: bool, error: str | None):
        GLib.idle_add(self._finish, success, error)

    # --- GTK-thread updates ---

    def _apply_progress(self, value: float):
        self.progressbar.set_fraction(max(0.0, min(1.0, value)))

    def _append_log(self, line: str):
        end = self._log_buffer.get_end_iter()
        self._log_buffer.insert(end, line + "\n")
        # auto-scroll to bottom
        adj = self._log_view.get_parent().get_vadjustment()  # ScrolledWindow adj
        adj.set_value(adj.get_upper() - adj.get_page_size())

    def _set_status(self, text: str):
        self.progressbar_text.set_label(text)

    def _finish(self, success: bool, error: str | None):
        if success:
            self._set_status("Installation complete")
            self.progressbar.set_fraction(1.0)
            self.router.set_next_enabled(True, caller=self)
        else:
            self._set_status("Installation failed")
            self._append_log(f"\n[fatal] {error}")
            # switch to console automatically so the user sees what went wrong
            self._show_console(None)

    # ------------------------------------------------------------------ tour

    def _update_tour_buttons(self, *_):
        pos   = int(self.carousel_tour.get_position())
        total = self.carousel_tour.get_n_pages()
        # could hide/show prev-next here when you add carousel pages

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
