### Added

- `shipmill doctor`'s hooks self-test, and the headless gate's before a session, run the install's Stop hook too: on a final message asking the maintainer with no request on GitHub it must refuse (exit 2), and with `stop_hook_active` true let the session end (exit 0); either failing, or an install with no Stop hook, is a FAIL naming the plugin update, and a headless gate starts no session (#1097)
