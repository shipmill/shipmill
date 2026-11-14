### Changed

- `pr_gate.py` binds the maintainer's answer to the head its question names on its `CI on <sha7>` line, never to a commit's date or a force-push's `beforeCommit`, and asks again when the question names no head; it reads the whole reply, so `1` followed by a request is the person's own words; and an answer on a linked issue counts only for a pull request the App or an OWNER, MEMBER, or COLLABORATOR opened (spec 055, S-055-5, S-055-7, S-055-8 revised) (#1122)
