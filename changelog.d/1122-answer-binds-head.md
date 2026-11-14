### Changed

- `pr_gate.py` binds the maintainer's answer to the full head SHA its question names on a hidden `<!-- shipmill:head <sha> -->` line under `CI on <sha7>`, never to a commit's date, a force-push's `beforeCommit`, or a 7-character prefix, and asks again when the question has no such line; it reads the whole reply, so `1` followed by a request is the person's own words; and an answer on a linked issue counts only for a pull request the App or an OWNER, MEMBER, or COLLABORATOR opened (spec 055, S-055-5, S-055-7, S-055-8 revised) (#1122)
