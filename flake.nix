{
  description = "ZenOS Setup - Unified Installer and OOBE";

  inputs = {
    nixpkgs.url = "github:nixos/nixpkgs/nixos-unstable";
  };
  outputs =
    { self, nixpkgs }:
    let
      system = "x86_64-linux";
      pkgs = nixpkgs.legacyPackages.${system};

      # move your core build logic here so you don't repeat yourself
      baseApp = pkgs.stdenv.mkDerivation {
        pname = "zenos-setup";
        version = "0.1.0";
        src = ./.;

        nativeBuildInputs = with pkgs; [
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
          python3
        ];

        buildInputs = with pkgs; [
          gtk4
          libgweather
          libadwaita
          networkmanager
          python3
          python3Packages.pygobject3
          python3Packages.requests
          python3Packages.babel
          python3Packages.mpv
          python3Packages.numpy
          python3Packages.pyopengl
          mpv
          firefox
          gparted
          gnome-console
        ];

        postInstall = ''
          PYTHONDONTWRITEBYTECODE=1 \
            PYTHONPATH="$out/share/zenos-setup" \
            ${pkgs.python3}/bin/python -c \
              'from zenos_setup.builder import SOFTWARE_APP_IDS, GNOME_EXTENSION_IDS; assert "firefox" in SOFTWARE_APP_IDS; assert "forge" in GNOME_EXTENSION_IDS'
          wrapProgram $out/bin/zenos-setup \
            --prefix PYTHONPATH : "$PYTHONPATH" \
            --prefix GI_TYPELIB_PATH : "$GI_TYPELIB_PATH" \
            --prefix PATH : ${
              pkgs.lib.makeBinPath [
                pkgs.gparted
                pkgs.gnome-console
                pkgs.firefox
                pkgs.openssl
              ]
            } \
            --set ZENOS_VIDEO_PATH "${introVideo}" \
            --set ZENOS_WALLPAPER_PATH "$src/data/wallpapers/"
        '';
      };

      introVideo = ./data/intro.mp4;
    in
    {
      packages.${system} = {
        # the main installer
        zenos-install = baseApp;

        # the oobe wrapper
        zenos-oobe = pkgs.writeShellScriptBin "zenos-oobe" ''
          if [ -z "$ZENOS_VIDEO_PATH" ]; then
            export ZENOS_VIDEO_PATH="${introVideo}"
          fi
          export ZENOS_OOBE_VIDEO_DEBUG="''${ZENOS_OOBE_VIDEO_DEBUG:-0}"
          export GSK_RENDERER="''${GSK_RENDERER:-gl}"
          exec ${baseApp}/bin/zenos-setup --oobe "$@"
        '';

        # keep a default so 'nix build' still works without arguments
        default = self.packages.${system}.zenos-install;
      };
    };
}
