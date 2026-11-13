### Added

- Doctor: a `landing` row reads the default branch's rulesets and classic protection (and `release/<series>` with a hotfix lane) and reports a rule that refuses land's push, naming the ruleset, its rules, the landing identity, and the App opt-in as the fix; a tag ruleset that would refuse the release tag is a warning (#1080)
