import os
from gi.repository import Gtk, Gdk, Gio, GLib, Adw, GObject

class ZenAnimatedButton(Gtk.Button):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._progress = 0.0
        self.set_opacity(0.0)

    @GObject.Property(type=float, default=0.0)
    def progress(self):
        return self._progress

    @progress.setter
    def progress(self, value):
        self._progress = value
        self.set_opacity(value)
        self.set_margin_bottom(60 + (20 * value))

class ZenWelcomeWindow(Adw.ApplicationWindow):
    __gsignals__ = {
        'intro-skipped': (GObject.SignalFlags.RUN_FIRST, None, ()),
    }

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.set_default_size(1920, 1080)
        self.set_title("ZenOS Welcome")

        self.is_playing = False
        self.can_close = False
        self.timer_id = 0
        self.transition_started = False

        self.current_frame = 1
        self.total_frames = 600
        self.frame_timer = 0

        self.frame_dir = os.environ.get("ZENOS_FRAMES_DIR", "/run/current-system/sw/share/zenos/frames")

        self.settings = Gio.Settings.new('org.gnome.desktop.interface')
        self.og_anim_state = self.settings.get_boolean('enable-animations')
        self.bg_settings = Gio.Settings.new('org.gnome.desktop.background')

        # set up dbus proxy for toggling cursed extensions
        try:
            bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
            self.ext_proxy = Gio.DBusProxy.new_sync(
                bus,
                Gio.DBusProxyFlags.NONE,
                None,
                "org.gnome.Shell.Extensions",
                "/org/gnome/Shell/Extensions",
                "org.gnome.Shell.Extensions",
                None
            )
        except Exception:
            self.ext_proxy = None

        # step 1: set wallpaper black, disable animations immediately
        self.set_global_anims(False)
        self.bg_settings.set_string('picture-options', 'none')
        self.bg_settings.set_string('primary-color', '#000000')

        self.connect("close-request", self.on_close_request)
        self.connect("map", self.on_window_mapped)

        self.overlay = Gtk.Overlay()
        self.set_content(self.overlay)

        self.picture = Gtk.Picture()
        self.picture.set_hexpand(True)
        self.picture.set_vexpand(True)
        self.picture.set_content_fit(Gtk.ContentFit.COVER)
        self.overlay.set_child(self.picture)

        self.skip_button = ZenAnimatedButton(label="Skip Intro")
        self.skip_button.add_css_class("pill")
        self.skip_button.add_css_class("suggested-action")
        self.skip_button.set_halign(Gtk.Align.CENTER)
        self.skip_button.set_valign(Gtk.Align.END)
        self.skip_button.set_margin_bottom(60)
        self.skip_button.connect("clicked", self.on_skip_clicked)
        self.overlay.add_overlay(self.skip_button)

        target = Adw.PropertyAnimationTarget.new(self.skip_button, 'progress')
        params = Adw.SpringParams.new(0.50, 1.0, 100.0)
        self.animation = Adw.SpringAnimation.new(self.skip_button, 0.0, 1.0, params, target)

        self.setup_input_tracking()
        self.fullscreen()

        self.start_playback()

    def set_global_anims(self, state):
        self.settings.set_boolean('enable-animations', state)
        Gio.Settings.sync()

        if self.ext_proxy:
            method = "EnableExtension" if state else "DisableExtension"
            try:
                self.ext_proxy.call_sync(
                    method,
                    GLib.Variant('(s)', ('burn-my-windows@schneegans.github.com',)),
                    Gio.DBusCallFlags.NONE,
                    -1,
                    None
                )
            except Exception:
                pass

    def on_window_mapped(self, *args):
        # step 2: wait 50ms after the window physically maps to switch it up
        GLib.timeout_add(50, self.step_two_enable_anims_and_bg)

    def step_two_enable_anims_and_bg(self):
        self.set_global_anims(self.og_anim_state)
        final_frame = os.path.join(self.frame_dir, f"frame_{self.total_frames:04d}.png")
        target_wallpaper = f"file://{final_frame}"

        self.bg_settings.set_string('picture-options', 'zoom')
        self.bg_settings.set_string('picture-uri', target_wallpaper)
        self.bg_settings.set_string('picture-uri-dark', target_wallpaper)
        return False

    def start_playback(self):
        self.is_playing = True
        self.frame_timer = GLib.timeout_add(33, self.next_frame)

    def next_frame(self):
        if not self.is_playing or self.transition_started:
            return False

        # step 3: wait until the last 10 frames -> disable animations again
        if self.current_frame == self.total_frames - 10:
            self.set_global_anims(False)

        if self.current_frame > self.total_frames:
            self.trigger_transition()
            return False

        frame_name = f"frame_{self.current_frame:04d}.png"
        frame_path = os.path.join(self.frame_dir, frame_name)

        file = Gio.File.new_for_path(frame_path)
        self.picture.set_file(file)

        self.current_frame += 1
        return True

    def setup_input_tracking(self):
        key_controller = Gtk.EventControllerKey()
        key_controller.connect("key-pressed", self.on_input_detected)
        self.add_controller(key_controller)
        click_controller = Gtk.GestureClick()
        click_controller.connect("pressed", self.on_input_detected)
        self.add_controller(click_controller)

    def on_input_detected(self, *args):
        if self.is_playing:
            self.animation.set_value_from(self.skip_button.progress)
            self.animation.set_value_to(1.0)
            self.animation.play()
            if self.timer_id > 0:
                GLib.source_remove(self.timer_id)
            self.timer_id = GLib.timeout_add(2000, self.hide_skip_button)
        return False

    def hide_skip_button(self):
        self.animation.set_value_from(self.skip_button.progress)
        self.animation.set_value_to(0.0)
        self.animation.play()
        self.timer_id = 0
        return False

    def on_close_request(self, *args):
        return not self.can_close

    def on_skip_clicked(self, btn):
        self.trigger_transition()

    def trigger_transition(self):
        if self.transition_started:
            return False
        self.transition_started = True
        self.is_playing = False
        self.can_close = True

        # violently kill animations right here so the close anim is definitely dead
        self.set_global_anims(False)

        # kill the video window instantly while anims are dead
        self.set_visible(False)

        # wait 50ms, then re-enable anims
        GLib.timeout_add(50, self._phase2_enable_anims)
        return False

    def _phase2_enable_anims(self):
        self.set_global_anims(self.og_anim_state)

        # wait 150ms for mutter to process the anim state change, then open setup
        GLib.timeout_add(150, self._phase3_open_window)
        return False

    def _phase3_open_window(self):
        self.emit('intro-skipped')
        return False
