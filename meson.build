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

endif