### Added

- `shipmill autonomy [--ref REF] [--json]` prints every stage's `[autonomy]` level (triage, fix, land, release, each deploy environment, rollback, intake, upgrade), configured and under the `shipmill-hold` stop switch, with its source (`default`, `config`, or `hold`) and the open hold issues, from the config at `origin/HEAD` by default; `shipmill decide levels` lists `triage`, `fix`, and `land` with source `autonomy`; `doctor` names the three agent stages in its autonomy line and warns when one is set in a config without `[agents]` (#660)
