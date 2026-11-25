### Added

- Gate: a subject a session left unchanged because it waits on another item is handed again once that item changes. The session names the item in a comment on the subject whose first line is `<!-- shipmill:waits-on owner/repo#N -->`, posted as the App; a walk that would mark the subject idle reads its newest such marker by the `--bot-login` and, when the named item's `updatedAt` is later than the hand, hands it again. A marker by anyone else counts for nothing. github-issue-triage's and github-pr-triage's hold comments now start with the marker (#1555)
