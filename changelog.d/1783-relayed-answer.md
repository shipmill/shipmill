### Added

- `shipmill answer <n> <answer> --by <login>` writes the maintainer's answer a session heard in the form its reader counts, as `shipmill gh` writes, and removes `needs-decision`: an option or `--own` on a needs-decision question, `accept`, `decline`, `hold --until`, or `send-back` on a plan, `continue`, `hold`, or `stop --reason` on a project head, and `accept --goal` on an accepted opportunity; it refuses before writing any answer its reader wouldn't count (spec 107, #1783)
