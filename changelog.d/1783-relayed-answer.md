### Added

- Commands that write the maintainer's answer a session heard, in the form its reader counts, as `shipmill gh` writes, and remove `needs-decision`: `shipmill decision answer <n> <option>|--own`, `shipmill goal-plan answer <n> accept|decline|hold|send-back`, `shipmill project continue|hold|stop <n>`, and `shipmill opportunity accept <n> G-<n>|new`, each with `--by <login>`; each refuses before writing any answer its reader wouldn't count (spec 107, #1783)
