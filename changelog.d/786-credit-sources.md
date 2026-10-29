### Added

- `[agents] credit = "decider"` also credits, after the approvers: the trusted answerer of a needs-decision question on the pull request, an issue it closes, or that issue's parent (a reply after the question's marker, or the login an App comment's `Decision by @<login>` line names), the trusted author of an issue it closes or of that issue's parent, and whoever with write, maintain, or admin permission added `planned` to an `opportunity` issue it closes or to that issue's parent; each person once, the first record naming them giving the stderr line's reason (spec 049) (#786)
