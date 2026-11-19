### Added

- In a headless gate session the delivery hook reads the command after a `test_proof.py` call's `--` (run directly, through `python`, or through `uv run`) as a call of its own and refuses the whole call when the uv-run rule (D-82) would refuse that command, so `test_proof.py fix ... -- uv run sh` is refused and `-- uv run pytest tests/test_a.py` passes; an interactive session is unchanged (S-076-11) (#1285)
