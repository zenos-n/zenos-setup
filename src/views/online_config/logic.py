import gi
import subprocess
import json
import threading
import re

gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Gtk, Adw, GLib, GObject

@Gtk.Template(resource_path='/com/negzero/zenos/setup/views/online_config/layout.ui')
class Page(Adw.Bin):
    __gtype_name__ = 'ZenOSDefaultCustom'

    MANIFEST = {
        "gated": True
    }

    image_url_entry = Gtk.Template.Child()
    host_dropdown = Gtk.Template.Child()
    url_spinner = Gtk.Template.Child()
    error_group = Gtk.Template.Child()
    error_label = Gtk.Template.Child()

    def __init__(self, **kwargs):
        self.router = kwargs.pop('router', None)
        super().__init__(**kwargs)

        # local state for the state collector
        self.state = {
            "flake_url": "",
            "selected_host": ""
        }

        # hide the spinner by default so it doesn't take up space
        self.url_spinner.set_visible(False)
        self.image_url_entry.connect('changed', self.on_url_changed)
        self.image_url_entry.connect('apply', self.on_apply)

        # track dropdown changes to keep state in sync
        self.host_dropdown.connect('notify::selected', self.on_host_selected)

    def get_finals(self):
        """ called by window.py to grab the data for the final install manifest """
        # refresh from ui just in case notify didn't fire for some reason
        url = self.image_url_entry.get_text().strip()
        selected_item = self.host_dropdown.get_selected_item()
        host = selected_item.get_string() if selected_item else ""

        return {
            "flake": self._normalize_url(url),
            "host": host,
            "method": "online"
        }

    def on_host_selected(self, dropdown, pspec):
        selected_item = dropdown.get_selected_item()
        if selected_item:
            self.state["selected_host"] = selected_item.get_string()

    def on_url_changed(self, entry):
        text = entry.get_text().strip()
        # nix flake urls are a bit of a wild west, but this covers the basics
        is_valid = bool(re.match(r'^(github:|git\+|https?://|gitlab:|flake:|/|\./)', text))

        if not is_valid and text:
            entry.add_css_class('error')
        else:
            entry.remove_css_class('error')

    def on_apply(self, entry):
        url = entry.get_text().strip()
        if not url:
            return

        # show and start spinner
        self.url_spinner.set_visible(True)
        self.url_spinner.start()

        self.image_url_entry.set_sensitive(False)
        self.error_group.set_visible(False)

        # update state early
        self.state["flake_url"] = url

        threading.Thread(target=self._fetch_flake_info, args=(url,), daemon=True).start()

    def _normalize_url(self, url):
        if url.startswith('https://github.com/') or url.startswith('https://gitlab.com/'):
            if not url.endswith('.tar.gz') and not url.endswith('.zip'):
                return f"git+{url}"
        return url

    def _fetch_flake_info(self, url):
        hosts = []
        error_msg = None
        url = self._normalize_url(url)

        try:
            # --no-write-lock-file is critical or it'll explode in a read-only environment
            result = subprocess.run(
                ['nix', 'flake', 'show', url, '--json', '--no-write-lock-file'],
                capture_output=True,
                text=True,
                check=True
            )
            data = json.loads(result.stdout)

            if 'nixosConfigurations' in data:
                hosts = list(data['nixosConfigurations'].keys())
            else:
                error_msg = "no nixosConfigurations found in this flake."

        except subprocess.CalledProcessError as e:
            error_msg = e.stderr.strip() or "failed to evaluate flake."
        except json.JSONDecodeError:
            error_msg = "nix output wasn't valid json."
        except Exception as e:
            error_msg = f"crashed parsing flake: {e}"

        GLib.idle_add(self._update_dropdown, hosts, error_msg)

    def _update_dropdown(self, hosts, error_msg):
        self.url_spinner.stop()
        self.url_spinner.set_visible(False)
        self.image_url_entry.set_sensitive(True)

        if error_msg:
            self.error_label.set_text(error_msg)
            self.error_group.set_visible(True)
            if self.router:
                self.router.set_next_enabled(False, caller=self)

        if hosts:
            model = Gtk.StringList.new(hosts)
            self.host_dropdown.set_model(model)
            self.host_dropdown.set_sensitive(True)
            self.host_dropdown.remove_css_class('dimmed')
            self.host_dropdown.set_selected(0)

            # update local state with first host
            self.state["selected_host"] = hosts[0]

            if self.router:
                self.router.set_next_enabled(True, caller=self)
        else:
            self.host_dropdown.set_sensitive(False)
            self.host_dropdown.add_css_class('dimmed')
            self.host_dropdown.set_model(Gtk.StringList.new([]))
            self.state["selected_host"] = ""
            if self.router:
                self.router.set_next_enabled(False, caller=self)
