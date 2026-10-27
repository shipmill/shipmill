### Changed

- `shipped.py`, and with it `shipmill status` and the gate's watch tick: the commits' pull requests are read 50 commits per GraphQL query and the closed issues 50 per query, in place of one call each, about 30 s less on a range of 30 commits; the plan, the notices posted, and the note for a number with no issue or pull request are unchanged (#754)
