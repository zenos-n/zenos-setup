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
      
      zenos-frames = pkgs.stdenv.mkDerivation {
        pname = "zenos-frames";
        version = "0.1.0";
        src = /home/doromiert/3D/dest2;

        installPhase = ''
          mkdir -p $out/share/zenos/frames
          cp frame_*.png $out/share/zenos/frames/
        '';
      };
      
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
          libadwaita
          python3
          python3Packages.pygobject3
          python3Packages.babel
        ];

        postInstall = ''
          wrapProgram $out/bin/zenos-setup \
            --prefix PYTHONPATH : "$PYTHONPATH" \
            --prefix GI_TYPELIB_PATH : "$GI_TYPELIB_PATH"
        '';
      };

      # this just wraps the `default` package, so nix doesn't rebuild the whole thing twice
      oobe = pkgs.writeShellScriptBin "oobe" ''
	  # point directly to your home dir, completely skipping the store copy
	  export ZENOS_FRAMES_DIR="/home/doromiert/3D/dest2"
	  exec ${default}/bin/zenos-setup --oobe "$@"
      '';
    };
    
    };
}