### Added

- Leak check: `shipmill leaks check [--repo DIR] [--to owner/name] [--field NAME] [FILE]` runs the detectors over a file or stdin and exits 2 with the findings, 0 with any warnings otherwise; `shipmill spec open` and `shipmill review record` check their `--body-file` before their first write, and `spec open` checks the commit it pushes, which no hook sees (#1318)
