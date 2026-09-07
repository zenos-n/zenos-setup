{
  nixpkgsSource,
  zenpkgsSource,
  hostModule,
}:
let
  zenpkgs = builtins.getFlake ("path:" + zenpkgsSource);
  pkgs = import nixpkgsSource {
    system = "x86_64-linux";
    config.allowUnfree = true;
    overlays = [ zenpkgs.overlays.default ];
  };
  evaluated = import (nixpkgsSource + "/nixos/lib/eval-config.nix") {
    system = "x86_64-linux";
    modules = [
      zenpkgs.nixosModules.default
      (import hostModule)
      {
        nixpkgs.overlays = [ zenpkgs.overlays.default ];
        system.stateVersion = "26.05";
        home-manager.sharedModules = [ { home.stateVersion = "26.05"; } ];
        boot.loader.grub.enable = false;
      }
    ];
  };
in
{
  drvPath = evaluated.config.system.build.toplevel.drvPath;
  hostname = evaluated.config.networking.hostName;
  gnome = evaluated.config.services.desktopManager.gnome.enable;
  home = evaluated.config.users.users.zen.home;
  disk = evaluated.config.disko.devices.disk.main.device or null;
  root = evaluated.config.fileSystems."/".device;
  esp = evaluated.config.fileSystems."/boot".device;
  extensions = evaluated.config.zenos.desktops.gnome.extensionUuids;
  dconf = map (database: pkgs.lib.generators.toDconfINI database.settings)
    evaluated.config.programs.dconf.profiles.user.databases;
}
