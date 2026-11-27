### Added

- `shipmill opportunity decline <n> --by <login> --reason "<why>"` records the maintainer's decline as a relay, then closes the opportunity as not planned, and `shipmill opportunity accept <n> G-<n>|new --by <login>` on an opportunity not yet `planned` adds `planned` after its relay (D-115); product intake reads a relayed decline's reason from its line, and the credit names the maintainer a relayed accept names (spec 108, #1812)
