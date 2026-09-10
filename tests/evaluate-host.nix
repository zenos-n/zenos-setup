{
  nixpkgsSource,
  zenpkgsSource,
  hostModule,
  extensionIds ? [ ],
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
  userSettings = evaluated.config.home-manager.users.zen.dconf.settings;
  hmGvariant = import (zenpkgs.inputs.home-manager + "/modules/lib/gvariant.nix") {
    lib = pkgs.lib;
  };
  unpack = value:
    if pkgs.lib.gvariant.isGVariant value then unpack value.value
    else if builtins.isList value then map unpack value
    else value;
in
{
  drvPath = evaluated.config.system.build.toplevel.drvPath;
  hostname = evaluated.config.networking.hostName;
  gnome = evaluated.config.services.desktopManager.gnome.enable;
  home = evaluated.config.users.users.zen.home;
  shell = evaluated.config.users.users.zen.shell.pname or null;
  zsh = evaluated.config.home-manager.users.zen.programs.zsh.enable;
  zoxide = evaluated.config.home-manager.users.zen.programs.zoxide.enable;
  direnv = evaluated.config.home-manager.users.zen.programs.direnv.enable;
  p10k = toString evaluated.config.home-manager.users.zen.xdg.configFile."zsh/p10k.zsh".source;
  homeManagerService = evaluated.config.systemd.services ? home-manager-zen;
  disk = evaluated.config.disko.devices.disk.main.device or null;
  root = evaluated.config.fileSystems."/".device;
  esp = evaluated.config.fileSystems."/boot".device;
  extensions = unpack (userSettings."org/gnome/shell".enabled-extensions or [ ]);
  expectedExtensions = map (name:
    (pkgs.lib.getAttrFromPath (
      if name == "customize-clock-on-lockscreen" then [ "legacy" "gnomeExtensions" "customize-clock-on-lock-screen" ]
      else if builtins.elem name [ "forge" "dash-stacks" ] then [ "desktops" "gnome" "extensions" name ]
      else [ "apps" "gnome-extensions" name ]
    ) pkgs.zenos).extensionUuid
  ) extensionIds;
  globalUuidDefinition = builtins.any
    (database: (database.settings."org/gnome/shell" or { }) ? enabled-extensions)
    evaluated.config.programs.dconf.profiles.user.databases;
  coreExtensionPackagesEmpty = evaluated.config.zenos.desktops.gnome.extensionPackages == [ ];
  coreExtensionUuidsEmpty = evaluated.config.zenos.desktops.gnome.extensionUuids == [ ];
  zenfs = evaluated.config.zenos.system.zenfs.enable;
  installedExtensions = map (package: package.extensionUuid)
    (builtins.filter (package: package ? extensionUuid) evaluated.config.environment.systemPackages);
  userDconf = pkgs.lib.generators.toDconfINI userSettings;
  userDconfTypes = pkgs.lib.mapAttrs
    (_: settings: pkgs.lib.mapAttrs (_: value: hmGvariant.typeOf value) settings)
    userSettings;
  dconf = map (database: pkgs.lib.generators.toDconfINI database.settings)
    evaluated.config.programs.dconf.profiles.user.databases;
}
