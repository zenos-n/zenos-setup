# Setup template contract

Setup reads `/iso-config-template/flake.nix` once, before disk work. The image
owns this template and supplies pinned compiler, runtime, Nixpkgs, Disko, and
offline dependencies. Setup does not import the live ISO host configuration.

The template must expose only `zenpkgs` as a root input. Setup reads its pinned
upstream Nixpkgs through `inputs.zenpkgs.inputs.nixpkgs`.
There is no `setup-hardware` input or hardware placeholder. Each generated
`hosts/<name>/host.zcfg` imports its hardware through canonical DSL syntax:

```text
_import "./hardware.zcfg";
```

Setup captures upstream `nixos-generate-config --show-hardware-config` output
in memory, evaluates the detected options and imported hardware profiles with
the template's pinned Nixpkgs, and serializes data into `hardware.zcfg` under
the existing `legacy` namespace. It does not write hardware Nix or hardware
JSON, either in the editable tree or in a separate hardware input. Only options
authored by the detector/profiles are projected; unrelated NixOS defaults are
not copied into the host. Detected defaults become concrete hardware values.
Non-data values (functions, packages, or paths) and unsupported list shapes
fail before disk operations rather than being silently dropped. The image
must provide the scanner and the pinned dependencies for this evaluation.

Enumerate `hosts/<name>/host.zcfg`, compile it with the image's pinned canonical
compiler into a store output, and import that output with the current ZenPkgs
runtime. The template supplies installed-system composition, stateVersion,
bootloader, ZenFS layout, and user home/config directory integration. Setup
emits existing public ZSTR paths only. In particular, accounts use
`users.<name>.legacy`, homes use `/Users/<name>`, and packages use full-path
boolean selectors. The template must not force a desktop or override Setup's
user selections.

Before unmounting or running automatic Disko, Setup stages the complete config,
locks offline, generates provisional hardware, checks/compiles ZCFG outside the
editable tree, and evaluates the selected host's `system.build.toplevel.drvPath`.
Manual preflight uses the selected root and EFI devices without mounting them.
After mounting, Setup regenerates actual hardware/filesystems in `hardware.zcfg`,
recompiles, relocks and evaluates again, then calls nixos-install.
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

For Install Now, Setup creates `oobe-<suffix>` with
`system.oobe.enable = true` in its generated `system.zcfg`. Final hosts omit
that setting entirely. The template must compile all `_import` dependencies
and expose the runtime's evaluated boolean at
`nixosConfigurations.<name>.config.zenos.system.oobe.enable`. Its default is
false. Setup queries this value through `nix eval --json --offline
--no-write-lock-file` against a materialized snapshot; it never searches source
text, comments, filenames, or JSON markers to determine OOBE state. Evaluation
errors and non-booleans are fatal. Before installing, Setup checks that the
evaluated state matches the selected temporary/final mode.

The template must let this evaluated option own the temporary account,
autologin/session, and `zenos-setup --oobe` launch. It must not force OOBE on or
infer it from the host name or bookkeeping records. Live and OOBE environments must
set `ZENOS_SETUP_DRY_RUN=0`; the package keeps dry-run as its default.

OOBE requires exactly one evaluated enabled host matching the running hostname.
It stages the final host with hardware, graphics and drive ZCFG from that
snapshot, evaluates it with OOBE disabled, and requests
`nixos-rebuild boot`. The final host omits the OOBE setting and must not inherit
temporary accounts, autologin, or the OOBE session. Only after a successful
rebuild does Setup remove the temporary host.
On an initial evaluation/rebuild failure it removes the staged final host and
retains the pending source. Successful `nixos-rebuild boot` commits the final
sources immediately: later progress or cleanup errors never roll them back.
Retries derive source and destination hosts from evaluated zcfg and existing host
directories without republishing users. Setup does not write OOBE bookkeeping
records before or after rebuilding.
The rebuild's return is the commit boundary. rEFInd synchronization runs after
the rebuild and is retried along with cleanup; its failure never rolls back the
already bootable final sources.
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
