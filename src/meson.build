pkgdatadir = get_option('prefix') / get_option('datadir') / meson.project_name()
moduledir = pkgdatadir / 'zenos_setup'
gnome = import('gnome')
python = import('python')

conf = configuration_data()
conf.set('PYTHON', python.find_installation('python3').full_path())
conf.set('VERSION', meson.project_version())
conf.set('localedir', get_option('prefix') / get_option('localedir'))
conf.set('pkgdatadir', pkgdatadir)

configure_file(
  input: 'zenos-setup.in',
  output: 'zenos-setup',
  configuration: conf,
  install: true,
  install_dir: get_option('bindir'),
  install_mode: 'rwxr-xr-x'
)

# compile UI files
zenos_resources = gnome.compile_resources(
  'zenos-setup',
  'zenos-setup.gresource.xml',
  gresource_bundle: true,
  install: true,
  install_dir: pkgdatadir,
)

zenos_setup_sources = [
  '__init__.py',
  'main.py',
  'oobe.py',
  'state.py',
  'window.py',
]

install_data(zenos_setup_sources, install_dir: moduledir)

# IMPORTANT: tell meson to install your new views python files
install_subdir('views', install_dir: moduledir)