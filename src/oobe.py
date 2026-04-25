import os
import gi

gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
gi.require_version('Gst', '1.0')

from gi.repository import Gtk, Gdk, Gio, GLib, Adw, GObject, Gst

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

        self.can_close = False
        self.timer_id = 0
        self.transition_started = False
        self.anims_killed_for_end = False

        # set gresource path for the intro video
        self.video_uri = "resource:///com/negzero/zenos/setup/assets/intro.webm"

        # fix wallpaper pathing logic for themes
        base_wallpaper = os.environ.get("ZENOS_WALLPAPER_PATH", "/run/current-system/sw/share/zenos/")
        if not base_wallpaper.endswith('/'):
            base_wallpaper += '/'
        self.wallpaper_path = base_wallpaper + "purple.png"

        # setup dconf BEFORE gstreamer touches anything
        self.settings = Gio.Settings.new('org.gnome.desktop.interface')
        self.og_anim_state = self.settings.get_boolean('enable-animations')
        self.bg_settings = Gio.Settings.new('org.gnome.desktop.background')

        try:
            bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
            self.ext_proxy = Gio.DBusProxy.new_sync(
                bus, Gio.DBusProxyFlags.NONE, None,
                "org.gnome.Shell.Extensions", "/org/gnome/Shell/Extensions",
                "org.gnome.Shell.Extensions", None
            )
        except Exception:
            self.ext_proxy = None

        self.bg_settings.set_string('picture-options', 'none')
        self.bg_settings.set_string('primary-color', '#000000')
        self.set_global_anims(False)

        self.connect("close-request", self.on_close_request)
        self.connect("map", self.on_window_mapped)

        self.overlay = Gtk.Overlay()
        self.set_content(self.overlay)

        self.video = Gtk.Picture()
        self.video.set_hexpand(True)
        self.video.set_vexpand(True)
        self.video.set_content_fit(Gtk.ContentFit.FILL)
        self.video.set_can_focus(False)
        self.overlay.set_child(self.video)

        self.pipeline = None

        # initialize gstreamer
        if not Gst.is_initialized():
            Gst.init(None)

        self.setup_video_pipeline()

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

    def setup_video_pipeline(self):
        # build the playback pipeline manually for fine control over scaling/cropping
        self.pipeline = Gst.parse_launch(
            f'urisourcebin uri={self.video_uri} name=src ! '
            'decodebin ! videoconvert ! videoscale ! videocrop name=crop ! '
            'appsink name=sink emit-signals=true caps="video/x-raw, format=RGBA"'
        )

        self.appsink = self.pipeline.get_by_name("sink")
        self.appsink.connect("new-sample", self.on_new_sample)

        self.cropper = self.pipeline.get_by_name("crop")

        bus = self.pipeline.get_bus()
        bus.add_signal_watch()
        bus.connect("message::eos", self.on_eos)
        bus.connect("message::error", self.on_pipeline_error)

        self.pipeline.set_state(Gst.State.PLAYING)
        GLib.timeout_add(33, self.check_video_progress)

    def on_pipeline_error(self, bus, message):
        err, debug = message.parse_error()
        print(f"GStreamer Error: {err.message}")
        self.trigger_transition()

    def on_new_sample(self, sink):
        sample = sink.emit('pull-sample')
        if not sample:
            return Gst.FlowReturn.ERROR

        caps = sample.get_caps()
        struct = caps.get_structure(0)
        video_w = struct.get_value('width')
        video_h = struct.get_value('height')

        # handle scaling/cropping on the first valid frame
        if self.cropper and video_w > 0:
            display_w = self.get_width()
            display_h = self.get_height()

            if display_w > 0 and display_h > 0:
                self.apply_center_crop(video_w, video_h, display_w, display_h)
                self.cropper = None # only do this once

        buffer = sample.get_buffer()
        success, map_info = buffer.map(Gst.MapFlags.READ)
        if success:
            bytes_data = GLib.Bytes.new(map_info.data)
            buffer.unmap(map_info)
            GLib.idle_add(self.update_frame, bytes_data, video_w, video_h)

        return Gst.FlowReturn.OK

    def apply_center_crop(self, vw, vh, dw, dh):
        video_aspect = vw / vh
        display_aspect = dw / dh

        left = right = top = bottom = 0

        if video_aspect > display_aspect:
            # video is wider than display, crop left/right
            target_width = vh * display_aspect
            crop_amount = int((vw - target_width) / 2)
            left = right = crop_amount
        else:
            # display is taller than video, crop top/bottom
            target_height = vw / display_aspect
            crop_amount = int((vh - target_height) / 2)
            top = bottom = crop_amount

        self.cropper.set_property("left", left)
        self.cropper.set_property("right", right)
        self.cropper.set_property("top", top)
        self.cropper.set_property("bottom", bottom)

    def update_frame(self, bytes_data, width, height):
        if self.transition_started:
            return False

        texture = Gdk.MemoryTexture.new(
            width, height,
            Gdk.MemoryFormat.R8G8B8A8,
            bytes_data,
            width * 4
        )
        self.video.set_paintable(texture)
        return False

    def on_eos(self, bus, message):
        GLib.idle_add(self.trigger_transition)

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
        GLib.timeout_add(50, self.step_two_enable_anims_and_bg)

    def step_two_enable_anims_and_bg(self):
        self.set_global_anims(True)
        target_uri = f"file://{self.wallpaper_path}"
        self.bg_settings.set_string('picture-options', 'zoom')
        self.bg_settings.set_string('picture-uri', target_uri)
        self.bg_settings.set_string('picture-uri-dark', target_uri)
        Gio.Settings.sync()
        return False

    def check_video_progress(self):
        if self.transition_started or not self.pipeline:
            return False

        success_pos, pos = self.pipeline.query_position(Gst.Format.TIME)
        success_dur, dur = self.pipeline.query_duration(Gst.Format.TIME)

        if success_pos and success_dur and dur > 0 and pos > 0 and (dur - pos) < 166666000:
            if not self.anims_killed_for_end:
                self.set_global_anims(False)
                self.anims_killed_for_end = True

        return True

    def setup_input_tracking(self):
        key = Gtk.EventControllerKey()
        key.connect("key-pressed", self.on_input_detected)
        self.add_controller(key)

        click = Gtk.GestureClick()
        click.connect("pressed", self.on_input_detected)
        self.add_controller(click)

    def on_input_detected(self, *args):
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
        if self.transition_started: return False
        self.transition_started = True

        if self.pipeline:
            self.pipeline.set_state(Gst.State.NULL)
            self.pipeline = None

        self.can_close = True

        if not self.anims_killed_for_end:
            self.set_global_anims(False)

        self.set_visible(False)

        GLib.timeout_add(50, self._phase2_enable_anims)
        return False

    def _phase2_enable_anims(self):
        self.set_global_anims(True)
        GLib.timeout_add(150, self._phase3_open_window)
        return False

    def _phase3_open_window(self):
        self.emit('intro-skipped')
        return False
