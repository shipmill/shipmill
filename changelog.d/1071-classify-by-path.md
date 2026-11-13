### Added

- `shipmill decide classify` sets each changed path's level from the strictest `[decisions.paths.<zone>]` part on the base whose glob matches it, else its zone's level, and takes a zone's level as the strictest among its paths'; its JSON lists them in a new `paths` key per zone (`path`, `level`, `source`, `glob`), and a text reason names the part that set a level, so `pr_gate.py` holds or notifies by the part (spec 057) (#1071)
