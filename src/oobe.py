import ctypes
import os
import resource
import time
import gi

gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Gtk, Gio, GLib, Adw, GObject
from mpv import MPV, MpvGlGetProcAddressFn, MpvRenderContext
from OpenGL import GL

from .oobe_timing import reached_wallpaper_switch


def get_proc_address_wrapper():
    def egl_impl(name):
        from OpenGL import EGL
        return EGL.eglGetProcAddress(name.decode("utf-8"))

    def glx_impl(name):
        from OpenGL import GLX
        return GLX.glXGetProcAddress(name.decode("utf-8"))

    platform_func = egl_impl if os.environ.get("WAYLAND_DISPLAY") else glx_impl

    def wrapper(_context, name):
        address = platform_func(name)
        return ctypes.cast(address, ctypes.c_void_p).value

    return wrapper


class MpvVideo(Gtk.GLArea):
    def __init__(self, path, first_frame_callback, end_callback):
        super().__init__(hexpand=True, vexpand=True)
        self.set_auto_render(False)
        self._path = path
        self._first_frame_callback = first_frame_callback
        self._end_callback = end_callback
        self._first_frame_seen = False
        self.rendered_frames = 0
        self._ctx = None
        self._mpv = MPV(
            vo="libmpv",
            hwdec="auto-safe",
            audio="no",
            panscan=1.0,
            video_sync="display-resample",
            interpolation="yes",
        )
        self._opengl_params = {
            "get_proc_address": MpvGlGetProcAddressFn(get_proc_address_wrapper())
        }
        self.connect("realize", self._on_realize)
        self.connect("unrealize", self._on_unrealize)

        @self._mpv.event_callback("end-file")
        def _on_end(_event):
            GLib.idle_add(self._end_callback)

    def _on_realize(self, *_args):
        self.make_current()
        error = self.get_error()
        if error:
            raise RuntimeError(f"could not initialize GTK OpenGL area: {error}")
        self._ctx = MpvRenderContext(
            self._mpv,
            "opengl",
            opengl_init_params=self._opengl_params,
        )
        self._ctx.update_cb = self._on_mpv_update
        self._mpv.play(self._path)

    def _on_mpv_update(self):
        GLib.idle_add(self._frame_ready, priority=GLib.PRIORITY_HIGH)

    def _frame_ready(self):
        if self._ctx and self._ctx.update():
            self.queue_render()
        return False

    def do_render(self, _context):
        if not self._ctx:
            return False
        factor = self.get_scale_factor()
        width = self.get_width() * factor
        height = self.get_height() * factor
        framebuffer = GL.glGetIntegerv(GL.GL_DRAW_FRAMEBUFFER_BINDING)
        self._ctx.render(
            flip_y=True,
            opengl_fbo={"w": width, "h": height, "fbo": framebuffer},
        )
        self.rendered_frames += 1
        if not self._first_frame_seen:
            self._first_frame_seen = True
            GLib.idle_add(self._first_frame_callback)
        return True

    def _on_unrealize(self, *_args):
        if self._ctx:
            self._ctx.free()
            self._ctx = None

    def property_value(self, name, default=None):
        try:
            return getattr(self._mpv, name.replace("-", "_"))
        except Exception:
            return default

    def stop(self):
        if self._ctx:
            self.make_current()
            self._ctx.free()
            self._ctx = None
        if self._mpv:
            self._mpv.terminate()
            self._mpv = None

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
        self.wallpaper_applied = False
        self.video_debug = os.environ.get("ZENOS_OOBE_VIDEO_DEBUG") == "1"
        self.debug_frames = 0
        self.debug_qos_drops = 0
        self.debug_last_time = time.monotonic()
        usage = resource.getrusage(resource.RUSAGE_SELF)
        self.debug_last_cpu = usage.ru_utime + usage.ru_stime

        self.video_path = os.environ.get("ZENOS_VIDEO_PATH")
        if not self.video_path:
            raise RuntimeError("ZENOS_VIDEO_PATH is required for OOBE playback")

        # fix wallpaper pathing logic for themes
        base_wallpaper = os.environ.get("ZENOS_WALLPAPER_PATH", "/run/current-system/sw/share/zenos/")
        if not base_wallpaper.endswith('/'):
            base_wallpaper += '/'
        self.wallpaper_path = os.environ.get("ZENOS_WALLPAPER_FILE", base_wallpaper + "purple.png")

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
        self.overlay.add_css_class("oobe-preroll")
        self.set_content(self.overlay)

        self.video = MpvVideo(
            self.video_path,
            first_frame_callback=self.reveal_video,
            end_callback=self.trigger_transition,
        )
        self.video.set_can_focus(False)
        self.overlay.set_child(self.video)

        self.debug_label = Gtk.Label(
            visible=self.video_debug,
            selectable=True,
            xalign=0,
            yalign=0,
            margin_top=24,
            margin_start=24,
            width_chars=54,
        )
        self.debug_label.add_css_class("monospace")
        self.debug_label.add_css_class("card")
        self.debug_label.set_label("Video diagnostics: waiting for mpv...")
        self.debug_label.set_halign(Gtk.Align.START)
        self.debug_label.set_valign(Gtk.Align.START)
        self.overlay.add_overlay(self.debug_label)

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
        self.set_cursor_from_name("none")
        self.fullscreen()

        GLib.timeout_add(33, self.check_video_progress)
        if self.video_debug:
            self.debug_timer_id = GLib.timeout_add_seconds(1, self.update_video_debug)

    def update_video_debug(self):
        if self.video is None or self.transition_started:
            return False

        now = time.monotonic()
        elapsed = max(now - self.debug_last_time, 0.001)
        rendered_frames = self.video.rendered_frames
        fps = (rendered_frames - self.debug_frames) / elapsed
        self.debug_frames = rendered_frames
        self.debug_last_time = now

        usage = resource.getrusage(resource.RUSAGE_SELF)
        cpu_now = usage.ru_utime + usage.ru_stime
        cpu_percent = ((cpu_now - self.debug_last_cpu) / elapsed) * 100
        self.debug_last_cpu = cpu_now

        position_seconds = self.video.property_value("time-pos", 0) or 0
        duration_seconds = self.video.property_value("duration", 0) or 0
        source_fps = self.video.property_value("container-fps", 0) or 0
        estimated_fps = self.video.property_value("estimated-vf-fps", 0) or 0
        codec = self.video.property_value("video-codec", "unknown")
        pixel_format = self.video.property_value("video-format", "unknown")
        hwdec = self.video.property_value("hwdec-current", "none") or "none"
        drops = self.video.property_value("vo-drop-frame-count", 0) or 0
        rss_mib = usage.ru_maxrss / 1024

        self.debug_label.set_label(
            "OOBE MPV DEBUG\n"
            f"Rendered:  {fps:5.1f} fps   Source: {source_fps:5.1f}   Filtered: {estimated_fps:5.1f}\n"
            f"Playback:  {position_seconds:5.1f} / {duration_seconds:5.1f} s\n"
            f"Process:   {cpu_percent:5.1f}% CPU   {rss_mib:6.1f} MiB max RSS\n"
            f"Decoder:   {codec}   hwdec={hwdec}   drops={drops}\n"
            f"Format:    {pixel_format}"
        )
        return not self.transition_started

    def reveal_video(self):
        if not self.transition_started:
            self.set_cursor(None)
        return False


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
        GLib.timeout_add(50, self.enable_anims)

    def enable_anims(self):
        self.set_global_anims(True)
        return False

    def apply_wallpaper(self):
        target_uri = f"file://{self.wallpaper_path}"
        self.bg_settings.set_string('picture-options', 'zoom')
        self.bg_settings.set_string('picture-uri', target_uri)
        self.bg_settings.set_string('picture-uri-dark', target_uri)
        Gio.Settings.sync()
        self.wallpaper_applied = True

    def check_video_progress(self):
        if self.transition_started or not self.video:
            return False

        position = self.video.property_value("time-pos", 0) or 0
        duration = self.video.property_value("duration", 0) or 0
        if not self.wallpaper_applied and reached_wallpaper_switch(position, duration):
            self.apply_wallpaper()

        if duration > 0 and position > 0 and (duration - position) < 0.17:
            if not self.anims_killed_for_end:
                self.set_global_anims(False)
                self.anims_killed_for_end = True
            if position >= duration - 0.05:
                self.trigger_transition()
                return False

        return True

    def setup_input_tracking(self):
        key = Gtk.EventControllerKey()
        key.connect("key-pressed", self.on_input_detected)
        self.add_controller(key)

        click = Gtk.GestureClick()
        click.connect("pressed", self.on_input_detected)
        self.add_controller(click)

    def on_input_detected(self, *args):
        self.set_cursor(None)
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
        self.set_cursor(None)

        if self.video:
            self.video.stop()
            self.video = None

        self.can_close = True

        if not self.anims_killed_for_end:
            self.set_global_anims(False)

        self.set_visible(False)

        GLib.timeout_add(50, self._phase2_enable_anims)
        return False

    def _phase2_enable_anims(self):
        self.set_global_anims(True)
        if not self.wallpaper_applied:
            self.apply_wallpaper()
        GLib.timeout_add(150, self._phase3_open_window)
        return False

    def _phase3_open_window(self):
        runtime_dir = os.environ.get("XDG_RUNTIME_DIR")
        if runtime_dir:
            marker = os.path.join(runtime_dir, "zenos-oobe-intro-complete")
            with open(marker, "w", encoding="utf-8"):
                pass
        self.emit('intro-skipped')
        return False
