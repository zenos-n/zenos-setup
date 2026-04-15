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

  # oobe proxy - builds via nix and drops the runner script in one go
  custom_target('zenos-oobe-proxy',
    output: 'zenos-oobe',
    command: [
      'sh', '-c',
      '''
      cd "$1" && nix build .#oobe -o result-oobe
      echo "#!/bin/sh" > "$2"
      echo 'exec "'"$1"'/result-oobe/bin/oobe" "$@"' >> "$2"
      chmod +x "$2"
      ''',
      'sh', src_root, '@OUTPUT@'
    ],
    build_by_default: true
  )

  # setup proxy - builds via nix and drops the runner script in one go
  custom_target('zenos-setup-proxy',
    output: 'zenos-setup',
    command: [
      'sh', '-c',
      '''
      cd "$1" && nix build .
      echo "#!/bin/sh" > "$2"
      echo 'exec "'"$1"'/result/bin/zenos-setup" "$@"' >> "$2"
      chmod +x "$2"
      ''',
      'sh', src_root, '@OUTPUT@'
    ],
    build_by_default: true,
    install: true,
    install_dir: get_option('bindir')
  )

endif