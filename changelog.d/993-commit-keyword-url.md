### Fixed

- `pr_gate.py` reads a commit message's closing keyword followed by an issue's URL, `https://github.com/<owner>/<repo>/issues/N` of the pull request's own repo, as GitHub closes by it, so a commit naming a `Part of` issue or one whose `## Check` hasn't run by its URL is refused like one naming it by `#N`; a `/pull/N` URL and another repo's URL name nothing (#993)
