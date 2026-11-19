### Added

- `retro.py proposal <body-file> --repo <owner/repo>` checks a rule proposal's body before the retro files it: exit 2 naming the first fault of its format (the marker, the Rule, Raised in, and Place sections, and for a check place the check, its failing run, and the default branch; for prose, Why prose), exit 1 with `DUPLICATE #N (<state>)` when the rule was proposed before in any state, declined included, or `FULL: K proposals wait on an answer` when `--max-open` (3) proposals wait on the maintainer, exit 0 printing the title (#1280)
