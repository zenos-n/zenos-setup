
from gi.repository import Adw
from gi.repository import Gtk

@Gtk.Template(resource_path='/com/negzero/zenos/setup/window.ui')
class ZenosSetupWindow(Adw.ApplicationWindow):
    __gtype_name__ = 'ZenosSetupWindow'

    label = Gtk.Template.Child()

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
