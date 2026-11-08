### Changed

- github-pr-triage: `changelog_guard.py check` refuses an entry marked Breaking (`**Breaking**`, `**Breaking:**`, or `Breaking:` at its start) under a `###` heading that `[bump] major` doesn't list, in a fragment or under Unreleased, naming the heading to move it to, so a breaking change no longer releases as a minor (D-78) (#971)
