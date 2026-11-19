### Added

- github-ship-watch's `fleet.py queue --fleet <file>` lists what waits on the maintainer across the fleet in one list, oldest first: unanswered `needs-decision` questions (`QUESTION`), pull requests labelled `shipmill-ready` to merge (`TO_MERGE`), and "Ready to promote" proposals (`PROMOTION`), each with its repo, `#N`, what is asked, and how long it has waited, with the watch's trust (`--bot-login`), `--json`, a REPO_ERROR line for a repo it can't read, and exit 0 when empty, 1 with a row, 2 on a failed read; it reads only (spec 069) (#1244)
