import re
from gi.repository import Adw, Gtk, GObject

@Gtk.Template(resource_path='/com/negzero/zenos/setup/views/user_setup/layout.ui')
class Page(Adw.Bin):
    __gtype_name__ = 'ZenOSUser'

    fullname_entry = Gtk.Template.Child()
    username_entry = Gtk.Template.Child()
    password_entry = Gtk.Template.Child()
    password_confirmation = Gtk.Template.Child()
    error_label = Gtk.Template.Child("error")
    warning_label = Gtk.Template.Child("warning")

    MANIFEST = {
        "gated": True,
        "unclosable": False
    }

    def __init__(self, router, **kwargs):
        super().__init__(**kwargs)
        self.router = router

        # spacing for the alerts
        for label in [self.error_label, self.warning_label]:
            label.set_margin_top(12)
            label.set_visible(False)

        # connect signals
        self.fullname_entry.connect("changed", self._validate)
        self.username_entry.connect("changed", self._validate)
        self.password_entry.connect("changed", self._validate)
        self.password_confirmation.connect("changed", self._validate)

    def _check_password_strength(self, password):
        if len(password) < 8:
            return "Password is short, potentially insecure"
        if not re.search(r"\d", password) or not re.search(r"[A-Z]", password):
            return "Try adding numbers or capital letters"
        return None

    def _validate(self, *args):
        fullname = self.fullname_entry.get_text().strip()
        username = self.username_entry.get_text().strip()
        pw = self.password_entry.get_text()
        pw_confirm = self.password_confirmation.get_text()

        is_valid = True
        error_msg = ""
        warning_msg = ""

        # hard errors (blocks navigation)
        if not fullname or not username or not pw:
            is_valid = False
        elif pw != pw_confirm:
            is_valid = False
            error_msg = "Passwords don't match"

        # soft warnings (doesn't block navigation)
        if pw and pw == pw_confirm:
            warning_msg = self._check_password_strength(pw)

        self.error_label.set_text(error_msg)
        self.error_label.set_visible(bool(error_msg))

        self.warning_label.set_text(warning_msg if warning_msg else "")
        self.warning_label.set_visible(bool(warning_msg))

        self.router.set_next_enabled(is_valid, caller=self)

    def get_data(self):
        return {
            "fullname": self.fullname_entry.get_text().strip(),
            "username": self.username_entry.get_text().strip(),
            "password": self.password_entry.get_text()
        }
