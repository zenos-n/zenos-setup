project('zenos-setup',
          version: '0.1.0',
    meson_version: '>= 1.0.0',
  default_options: [ 'warning_level=2', 'werror=false', ],
)

# nix sets this environment variable when it's actively building a derivation
is_nix_sandbox = run_command('sh', '-c', 'test -n "$NIX_BUILD_TOP"', check: false).returncode() == 0

if is_nix_sandbox
  # ---------------------------------------------------------
  # THE ACTUAL BUILD (runs only when 'nix build' is doing the work)
  # ---------------------------------------------------------
  message('nix sandbox detected: running the real build.')

  i18n = import('i18n')
  gnome = import('gnome')

  subdir('data')
  subdir('src')
  subdir('po')

  gnome.post_install(
       glib_compile_schemas: true,
      gtk_update_icon_cache: true,
    update_desktop_database: true,
  )

else
  # ---------------------------------------------------------
  # THE IDE HIJACK (runs when gnome builder indexes the project)
  # ---------------------------------------------------------
  message('gnome builder detected: proxying buttons to nix.')

  nix = find_program('nix', required: true)
  src_root = meson.project_source_root()
  build_root = meson.project_build_root()

  # hammer button → nix build
  nix_build = custom_target('nix-build-proxy',
    output: 'nix-build.done',
    command: [
      'sh', '-c',
      'cd "$1" && nix build . && touch "$2"',
      'sh', src_root, '@OUTPUT@'
    ],
    build_by_default: true
  )

  # drop a real executable wrapper into the build root so Builder
  # can find it by name (it scans for a file matching the project binary
  # when meson introspection has no executable() target)
  custom_target('zenos-setup-runner',
  output: 'zenos-setup',
  command: [
    'sh', '-c',
    '''
    rm -f "$1"
    echo "#!/bin/sh" > "$1"
    echo 'exec "'"$2"'/result/bin/zenos-setup" "$@"' >> "$1"
    chmod +x "$1"
    ''',
    'sh', '@OUTPUT@', src_root
  ],
  depends: nix_build,
  build_by_default: true,
  install: true,
  install_dir: get_option('bindir')
)

endif