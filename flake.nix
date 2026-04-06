{
  description = "ZenOS Setup - Unified Installer and OOBE";

  inputs = {
    nixpkgs.url = "github:nixos/nixpkgs/nixos-unstable";
  };

  outputs = { self, nixpkgs }:
    let
      system = "x86_64-linux";
      pkgs = nixpkgs.legacyPackages.${system};
    in {
      packages.${system}.default = pkgs.stdenv.mkDerivation {
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
    glib # for glib-compile-schemas
    python3 # needed for the build scripts
  ];

  buildInputs = with pkgs; [
    gtk4
    libadwaita
    python3
    python3Packages.pygobject3
    python3Packages.babel
  ];

  # This ensures the final binary in /bin finds its python deps
  postInstall = ''
    wrapProgram $out/bin/zenos-setup \
      --prefix PYTHONPATH : "$PYTHONPATH" \
      --prefix GI_TYPELIB_PATH : "$GI_TYPELIB_PATH"
  '';
};
};}
