### Fixed

- A gate held because PyPI doesn't serve the plugin version sessions load no longer reads healthy: `shipmill status` reads the gate's last `PYPI_WAIT` tick as a wait on you (`paused: plugin <version> waits for PyPI`), and `doctor` asks PyPI for that version itself, a WARN on 404 or when PyPI doesn't answer; each names the fix, the release's `publish.yml` run, or a new one with `gh workflow run publish.yml --repo shipmill/shipmill -f tag=v<version>` (#569)
