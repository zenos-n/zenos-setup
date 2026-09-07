# Setup template contract

Setup reads `/iso-config-template/flake.nix` once, before disk work. The image
owns this template and supplies pinned compiler, runtime, Nixpkgs, Disko, and
offline dependencies. Setup does not import the live ISO host configuration.

The template must contain this input, with the placeholder exactly once:

```nix
inputs.setup-hardware = {
  url = "path:@ZENOS_SETUP_HARDWARE@";
  flake = false;
};
```

Setup replaces the placeholder with an immutable store directory created by
`nix store add-path`. That directory contains `hardware-configuration.nix` and
`detection.json`. Import `inputs.setup-hardware + "/hardware-configuration.nix"`
as an upstream NixOS module for each generated host. Retain this input in the
installed closure, for example with `system.extraDependencies`, along with the
pinned compiler/runtime sources and offline build dependencies. Do not read a
generated `host.nix` or hardware Nix from the editable tree.

Enumerate `hosts/<name>/host.zcfg`, compile it with the image's pinned canonical
compiler into a store output, and import that output with the current ZenPkgs
runtime. The template supplies installed-system composition, stateVersion,
bootloader, ZenFS layout, and user home/config directory integration. Setup
emits existing public ZSTR paths only. In particular, accounts use
`users.<name>.legacy`, homes use `/Users/<name>`, and packages use full-path
boolean selectors. The template must not force a desktop or override Setup's
user selections.

Before unmounting or running automatic Disko, Setup stages the complete config,
checks/compiles ZCFG outside the editable tree, binds provisional hardware,
locks offline, and evaluates the selected host's `system.build.toplevel.drvPath`.
Manual preflight uses the selected root and EFI devices without mounting them.
After mounting, Setup regenerates actual hardware/filesystems, replaces the
hardware input, relocks and evaluates again, then calls nixos-install.
Evaluation may realize compiler outputs; it must not activate or partition.
Preflight is not a guarantee that every target closure is available offline.

The target is `/mnt/etc/ZenOS`, visible as `/Config/ZenOS` after boot. It contains
`flake.nix`, `flake.lock`, and `hosts/<name>/` with split ZCFG and Setup JSON
metadata only. No other `.nix` files are allowed in that tree. Compiler output
and transient Disko Nix stay in the private per-run temporary directory.

Accounts are emitted separately as `hosts/<host>/users/<user>/main.zcfg`.
After mounting (or during OOBE), Setup exclusively creates the canonical source
at `/Users/<user>/.private/Config/main.zcfg` with mode 0600, owned by the first
user (UID 1000, group 100). Existing canonical sources are never overwritten.
The host entry becomes an absolute symlink to that source. Other host symlinks,
redirected canonical paths, and generated user Nix are rejected.

Setup materializes these links from the mounted target into a private snapshot
before offline locking, evaluation, install, or rebuild. Only the snapshot is
passed to Nix; the installed editable tree retains its canonical links. Failure
before successful install/rebuild removes only unchanged newly published canonical
files. Rollback checks descriptor-relative parent identities, file identity and
content; edits, replacements, missing files and redirected parents are preserved.
The image must retain the compiled host's source snapshot in the installed
closure. Later rebuild tooling must perform the same snapshot handoff: directly
evaluating the editable flake with external home symlinks is not supported by
pure Nix. This contract does not add a public option or change D19 ownership.

For Install Now, Setup creates `oobe-<suffix>` and a version 3 `oobe.json` with
`status = "pending"`, `temporaryHost`, and checksums of `graphics.zcfg`,
`hardware.json`, and (for automatic disks) `drives.zcfg`. `hardware.json` points
to the immutable hardware source and records its checksum. The template must
enable its temporary first-boot session only for the host with this pending
marker, launching `zenos-setup --oobe`. Live and OOBE launch environments must
set `ZENOS_SETUP_DRY_RUN=0`; the package keeps dry-run as its default.

OOBE verifies the pending host and artifacts, stages the final host with the
same hardware input and drive configuration, evaluates it, and requests
`nixos-rebuild boot`. The final host has no pending marker and must not inherit
temporary accounts, autologin, or the OOBE session. Only after a successful
rebuild does Setup write `oobe-complete.json` and remove the temporary host.
On an initial evaluation/rebuild failure it removes the staged final host and
retains the pending source. Successful `nixos-rebuild boot` commits the final
sources immediately: later marker, progress or cleanup errors never roll them
back. Setup records `oobe-finalize.json` before rebuilding so finalization can be
retried without republishing users. A completion record permits cleanup-only
retries, even after the temporary host was removed. An intent without a completion
record conservatively retains the final sources and repeats evaluation/rebuild
before cleanup. These are runner bookkeeping records, not new template inputs.
Reboot remains owned by the existing reboot page.

The default GNOME choices are supported. Branding and both shortcut families
are lowered from the previous `zenos-next` a813a8e profile into existing GNOME
and legacy dconf options. Dash Stacks and the patched Forge use the current
`pkgs.desktops.gnome.extensions` compatibility package paths. Explicit extension
lists, tiling, branding off, dark/accent preferences, and Firefox GNOME theming
are preserved. Typed dconf values use data-only upstream GVariant records;
generated ZCFG contains no function calls or new public option roots.

Illogical Impulse is visibly disabled because its current module has no actions.
Unsupported payloads still fail before disk operations: unknown desktops or
packages, and unimplemented app extras.
Other desktop choices use upstream legacy options and are checked against the
image's pinned runtime before disk work. Custom online configs are rejected
until they implement this template and hardware contract.
