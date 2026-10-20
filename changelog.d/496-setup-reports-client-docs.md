### Changed

- shipmill-setup no longer edits a repo's CLAUDE.md, AGENTS.md, or CONTRIBUTING.md when it turns changelog fragments on: `setup_state.py`'s new `CHANGELOG_RULES` warning names each line there that mentions Unreleased as file and line, and leaves the change to the maintainer (D-42) (#496)
