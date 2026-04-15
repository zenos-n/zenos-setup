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
            glib
            python3
          ];

          buildInputs = with pkgs; [
            gtk4
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
          ];

          postInstall = ''
            wrapProgram $out/bin/zenos-setup \
              --prefix PYTHONPATH : "$PYTHONPATH" \
              --prefix GI_TYPELIB_PATH : "$GI_TYPELIB_PATH" \
              --set ZENOS_VIDEO_PATH "/home/doromiert/3D/dest2-ffv1/output.mkv" \
              --set ZENOS_WALLPAPER_PATH "$src/src/assets/wall.png"
          '';
        };

        oobe = pkgs.writeShellScriptBin "oobe" ''
          # for local dev, point it to your local file
          export ZENOS_VIDEO_PATH="/home/doromiert/3D/dest2-ffv1/output.mkv"
          exec ${default}/bin/zenos-setup --oobe "$@"
        '';
      };
    };
}
