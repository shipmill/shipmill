### Added

- The maintainer's accepting answer lifts `pr_gate.py`'s `files:` lines under spec 055's rules for the head it covers, so CI decides; a head whose own change differs since keeps them, a new verdict on the issue after the pull request opened doesn't widen them, and `shipmill gh pr merge` on a pull request they hold exits 2 before gh runs, now proven by tests (#1525)
