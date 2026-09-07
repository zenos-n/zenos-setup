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

      baseApp = pkgs.callPackage ./package.nix { };

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
