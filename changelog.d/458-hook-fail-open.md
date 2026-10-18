### Fixed

- Hooks: when uv is missing, can't find or install a Python 3.11 or newer, or `hooks/delivery.py` is missing, the hook prints one line naming `shipmill doctor` and exits 1, so the command runs unchecked instead of every shell command being refused (#458)
