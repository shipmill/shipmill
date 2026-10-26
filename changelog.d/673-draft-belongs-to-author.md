### Changed

- A draft pull request belongs to whoever opened it (D-52): github-pr-triage leaves drafts out of its review and landing and reports each as "draft, left to its author", `pr_gate.py` reads a draft as DRAFT with exit 8 whatever its checks, and github-issue-triage hands over only pull requests marked ready (#673)
