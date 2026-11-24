### Fixed

- `shipmill gh`: three posts the gate would discard exit 2 before anything reaches GitHub, each naming the fix: adding `needs-decision` to a pull request whose newest question doesn't name its current head on its `<!-- shipmill:head <sha> -->` line, a needs-decision question on a pull request without that line, and a relay out of the relay grammar (D-93), read by `pr_gate.py`'s and `retro.py`'s own readers, so the maintainer no longer answers a question twice (#1484)
