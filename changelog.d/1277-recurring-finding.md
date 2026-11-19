### Added

- `retro.py findings <owner/repo>` lists what reviews raised on the pull requests closed in the last `--days` (28 by default): the App's review records, trusted people's change requests and inline comments, and the comment that closed an unmerged pull request, each with an `F-n` id, its head, and the rule ids it cites, then every `rule-proposal` issue as open, accepted, or declined; outsiders' and agent-marked text is left out (#1277)
