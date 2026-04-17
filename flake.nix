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
      lib = nixpkgs.lib;

      # the intro video hosted on your r2 cdn
      # trigger a hash failure to get the correct SRI hash
      introVideo = pkgs.fetchurl {
        url = "https://r2.neg-zero.com/intro.mkv";
        sha256 = "sha256-BciVM83HWmloezUTjrKlvv2CHGEgpNb84zUy9zkGlGM=";
      };
    in
    {
      packages.${system} = rec {

        default = pkgs.stdenv.mkDerivation {
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
            gst_all_1.gstreamer
            gst_all_1.gst-plugins-base
            gst_all_1.gst-plugins-good
            gst_all_1.gst-libav
            firefox
            gparted
            gnome-console
          ];

          postInstall = ''
            wrapProgram $out/bin/zenos-setup \
              --prefix PYTHONPATH : "$PYTHONPATH" \
              --prefix GI_TYPELIB_PATH : "$GI_TYPELIB_PATH" \
              --prefix PATH : ${pkgs.lib.makeBinPath [ pkgs.gparted pkgs.gnome-console pkgs.firefox ]} \
              --set ZENOS_VIDEO_PATH "${introVideo}" \
              --set ZENOS_WALLPAPER_PATH "$src/src/assets/wall.png"
          '';
        };

        oobe = pkgs.writeShellScriptBin "oobe" ''
          # check for local override, otherwise use the cdn version
          if [ -z "$ZENOS_VIDEO_PATH" ]; then
            export ZENOS_VIDEO_PATH="${introVideo}"
          fi
          exec ${default}/bin/zenos-setup --oobe "$@"
        '';
      };
    };
}