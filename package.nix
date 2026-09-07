{
  lib,
  stdenv,
  meson,
  ninja,
  pkg-config,
  gobject-introspection,
  wrapGAppsHook4,
  desktop-file-utils,
  appstream-glib,
  appstream,
  libxml2,
  glib,
  gtk4,
  libgweather,
  libadwaita,
  networkmanager,
  gnome-desktop,
  python3,
  mpv,
  firefox,
  gparted,
  gnome-console,
  openssl,
  xvfb-run,
}:
let
  python = python3.withPackages (
    ps: [
      ps.pygobject3
      ps.requests
      ps.babel
      ps.mpv
      ps.numpy
      ps.pyopengl
    ]
  );
in
stdenv.mkDerivation {
  pname = "zenos-setup";
  version = "0.1.0";
  src = lib.fileset.toSource {
    root = ./.;
    fileset = lib.fileset.unions [
      ./meson.build
      ./data
      ./po
      (lib.fileset.fileFilter (file: !(lib.hasSuffix ".pyc" file.name)) ./src)
    ];
  };

  nativeBuildInputs = [
    meson
    ninja
    pkg-config
    gobject-introspection
    wrapGAppsHook4
    desktop-file-utils
    appstream-glib
    appstream
    libxml2
    glib
    python
    xvfb-run
  ];
  buildInputs = [
    gtk4
    libgweather
    libadwaita
    networkmanager
    gnome-desktop
    python
    mpv
  ];

  postInstall = ''
    PYTHONDONTWRITEBYTECODE=1 \
      PYTHONPATH="$out/share/zenos-setup" \
      ${python}/bin/python3 -c \
        'from zenos_setup.builder import SOFTWARE_APP_IDS, GNOME_EXTENSION_IDS; assert "firefox" in SOFTWARE_APP_IDS; assert "forge" in GNOME_EXTENSION_IDS'
  '';
  preFixup = ''
    gappsWrapperArgs+=(
      --prefix PYTHONPATH : "${python}/${python.sitePackages}"
      --prefix PATH : "${
        lib.makeBinPath [
          gparted
          gnome-console
          firefox
          openssl
        ]
      }"
      --set ZENOS_VIDEO_PATH "${./data/intro.mp4}"
      --set ZENOS_WALLPAPER_PATH "${./data/wallpapers}/"
    )
  '';
  doInstallCheck = true;
  installCheckPhase = ''
        export HOME="$TMPDIR/smoke-home"
        export XDG_CACHE_HOME="$HOME/.cache"
        mkdir -p "$XDG_CACHE_HOME"
        runHook preInstallCheck
        makeWrapper ${python}/bin/python3 "$TMPDIR/check-python" "''${gappsWrapperArgs[@]}"
        "$TMPDIR/check-python" -c '
    import gi
    gi.require_version("Gtk", "4.0")
    gi.require_version("Adw", "1")
    gi.require_version("GWeather", "4.0")
    gi.require_version("NM", "1.0")
    gi.require_version("GnomeDesktop", "4.0")
    from gi.repository import Gtk, Adw, GWeather, NM, GnomeDesktop
    import babel, requests, mpv, numpy
    from OpenGL import GL
    assert GnomeDesktop.XkbInfo().get_all_layouts()
    '
        test -s ${./data/intro.mp4}
        test -d ${./data/wallpapers}
        PYTHONDONTWRITEBYTECODE=1 ZENOS_SETUP_DRY_RUN=1 \
          GSETTINGS_BACKEND=memory GSK_RENDERER=cairo \
          xvfb-run -a "$TMPDIR/check-python" ${./tests/smoke-ui.py} "$out"
        runHook postInstallCheck
  '';

  meta = {
    description = "ZenOS installer and out-of-box setup";
    mainProgram = "zenos-setup";
    platforms = lib.platforms.linux;
  };
}
