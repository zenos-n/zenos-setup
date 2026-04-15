import gi
import re
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk, Adw

@Gtk.Template(resource_path='/com/negzero/zenos/setup/views/computer_name/layout.ui')
class Page(Adw.Bin):
    __gtype_name__ = 'ZenosComputerNamePage'

    MANIFEST = {
        "gated": True
    }

    entry_row = Gtk.Template.Child()
    banner = Gtk.Template.Child()

    def __init__(self, router, **kwargs):
        super().__init__(**kwargs)
        self.router = router

    @Gtk.Template.Callback()
    def on_text_changed(self, entry, *args):
        text = entry.get_text()

        if not text or not text.strip():
            self.banner.set_revealed(False)
            self.router.set_next_enabled(False, caller=self)
            return

        # 1. basic cleaning
        # replaces spaces/underscores, lowers, removes cursed chars
        sanitized = text.lower().replace(" ", "-").replace("_", "-")
        sanitized = re.sub(r'[^a-z0-9-]', '', sanitized)
        sanitized = re.sub(r'-+', '-', sanitized).strip('-')

        # 2. enforce 63 char limit (RFC 1035)
        sanitized = sanitized[:63].rstrip('-')

        # check if it's actually valid or if it was stripped to nothing
        is_valid = len(sanitized) > 0

        if not is_valid:
            self.banner.set_title("invalid computer name")
            self.banner.set_revealed(True)
            self.router.set_next_enabled(False, caller=self)
            return

        # only show the banner if we actually changed something
        # if user typed "my-pc" and result is "my-pc", keep it quiet
        if text != sanitized:
            self.banner.set_title(f"will appear as {sanitized} on the network")
            self.banner.set_revealed(True)
        else:
            self.banner.set_revealed(False)

        self.router.set_next_enabled(True, caller=self)
