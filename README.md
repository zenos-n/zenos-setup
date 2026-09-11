# ZenOS Setup

Installer and first-boot setup for ZenOS. The existing manual installer,
Install Now, and OOBE pages share the backend in `src/builder.py` and
`src/runner.py`.

## Packaging

External consumers use `pkgs.callPackage (source + "/package.nix") { }`.
The result has `meta.mainProgram = "zenos-setup"`. The flake keeps the existing
`zenos-install`, `zenos-oobe`, and `default` outputs. The package includes the
Python dependencies, GnomeDesktop 4 keyboard typelib, intro video, and wallpapers.
The image supplies the pinned compiler and installation commands.
The package checks GI imports and keyboard layouts, then exercises the installed
GNOME controls and default rendering under Xvfb with an isolated settings backend.

## Image integration

See [TEMPLATE-CONTRACT.md](TEMPLATE-CONTRACT.md) for the template interface,
pre-erase checks, imported `hardware.zcfg`, and declarative OOBE handoff.
No generated Nix belongs below `/Config/ZenOS`, except its `flake.nix` entry.
Per-user host entries link to `/Users/<user>/.private/Config/main.zcfg`.
Setup passes private materialized snapshots of those sources to the install or
rebuild command. Later rebuild
tools must implement the same handoff instead of passing external home symlinks
directly to pure Nix.

The backend defaults to dry-run. Image composition must set
`ZENOS_SETUP_DRY_RUN=0` for live installation and OOBE. Do not set it while
running the test suite.

## Validation

Run runtime checks only in a ZenOS VM, from a private source snapshot:

```sh
PYTHONDONTWRITEBYTECODE=1 ZENOS_SETUP_DRY_RUN=1 \
  ZENOS_SETUP_COMPILER_SOURCE=/tmp/private-snapshot/zen-dsl \
  python3 -m unittest discover -s tests -v
```

Copy `zenpkgs/lib/zen-dsl` into that snapshot to exercise the current compiler.
Set `ZENOS_SETUP_RUNTIME_SOURCE` to a private current ZenPkgs snapshot and
`ZENOS_SETUP_NIXPKGS_SOURCE` to the image's pinned Nixpkgs source to also evaluate
the default host and its dconf output through the current runtime. Tests never
partition disks, mount filesystems, install a system, or activate a generation.
Installer and OOBE command ordering uses dry-run or mocks.
Dry-run OOBE tests inject evaluated boolean states; dry-run mode does not guess
those states from source text. Source-level compiler and Nix evaluation tests
are separate from full runtime, privileged handoff, and VM acceptance tests.

Default GNOME branding, recommended extensions including Dash Stacks, Forge
tiling, Vim directions, and ZenOS actions are supported. Stock branding and both
shortcut families remain independent choices. Illogical Impulse is disabled
because its current module has no implementation; unavailable packages and
unimplemented nondefault app extras are still rejected before disk work.
