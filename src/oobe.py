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

        self.connect("close-request", self.on_close_request)

        self.overlay = Gtk.Overlay()
        self.set_content(self.overlay)

        self.picture = Gtk.Picture()
        self.picture.set_hexpand(True)
        self.picture.set_vexpand(True)
        self.picture.set_content_fit(Gtk.ContentFit.COVER)

        # Load from GResource
        self.media_file = Gtk.MediaFile.new_for_resource("/com/negzero/zenos/setup/assets/welcome.mp4")
        self.picture.set_paintable(self.media_file)

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

        # Start playback immediately for the OOBE feel
        self.media_file.set_loop(False)
        self.media_file.play()
        self.is_playing = True
        self.fullscreen()

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
        if self.media_file:
            self.media_file.pause()
        self.is_playing = False
        self.can_close = True
        self.emit('intro-skipped')
