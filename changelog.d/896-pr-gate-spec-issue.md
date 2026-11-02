### Added

- A spec pull request names its feature issue (spec 053): `pr_gate.py` reads a ready pull request that adds `docs/specs/NNN-<slug>.md` as REFUSED, exit 6, with a `spec: names no feature issue` line, when no line of its body starts `Spec for #N` naming an open issue of the repo, whoever opened it and even with `--maintainer-accepted`; a pull request that only edits, renames, or copies a spec isn't checked (#896)
