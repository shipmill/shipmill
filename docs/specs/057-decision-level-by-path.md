# S-057: A decision level for part of a zone, by path

status: built
serves: G-1

## Problem

`[decisions]` sets one level per zone (spec 030), so `security` or `protected` is a single
switch for every path the zone covers. A repository can't say "a change to CI wiring may be
decided with notice, a change to settings or migrations still asks" (#998).

Across 15 connected repositories over the 30 days to 2026-11-09, 129 pull requests were held
in those two zones. By a rough match on their changed files, 34 touched only `.github/**`
files other than the config, 18 only `.github/shipmill.toml`, and 17 only production-sensitive
paths (settings, migrations, SQL, units, auth, billing). The maintainer's overrides that
caught real problems sat in the production-sensitive group; one-line config entries were
approved as asked. With one level per zone, a maintainer keeps both groups at `ask` or lowers
both (#1044).

This spec lets `[decisions]` set a level for the paths of a zone that code detects by path,
and keeps what D-48 holds: a zone's floor, the strictest level winning, and the levels read
from the base branch, never from the pull request. It extends spec 030, which left per-path
levels for a later spec (its Out of scope).

## Behaviour

### The config

A new optional table in `[decisions]` of `.github/shipmill.toml` (D-4), one subtable per
zone, each key a glob and each value a level:

```toml
[decisions]
security = "ask"                  # the zone's level, as today

[decisions.paths.security]        # a part of security: these paths take their own level
".github/workflows/**" = "notify"
".github/shipmill.toml" = "notify"

[decisions.paths.protected]
"deploy/migrations/**" = "never"
```

`paths` becomes a reserved key of `[decisions]`, like `veto_hours`; no zone id is or will be
`paths`. A glob with its level is a **part** of the zone. `src/shipmill/decide.py` parses the
parts into `DecisionPolicy`, through `src/shipmill/policy.py` as today.

Only the zones code detects from a changed path take parts: `direction`, `security`, and
`protected`. The parse exits 2, naming the key and the fix (Q-1), when:

- `paths` or `paths.<zone>` is not a table
- a zone under `paths` is no zone id (it lists the three zones that take parts), is
  `decision-policy` (fixed at `never`, D-48), a release-side zone (set in `[autonomy]`), or
  a zone code doesn't detect by path, such as `scope` or `contract-change`: `scope takes no
  paths: only direction, security, and protected are detected by path`
- a value is not `act`, `notify`, `ask`, or `never`
- a part's level is below its zone's floor, with the floor's reason as spec 030 gives it:
  `[decisions.paths.security] ".github/workflows/**" = "act" is below its floor notify`
- a glob is empty, absolute, or holds `..`
- a glob lies outside its zone's paths: a `security` glob must start `.github/`, a
  `direction` glob must be `docs/product.md` or start `docs/product/`; a `protected` glob
  may be any relative glob, since `REVIEW.md` sets that zone's paths

A part may set a level above or below its zone's, down to the floor. `decide levels` and
`doctor` show every part.

`skills/github-issue-triage/scripts/decisions.py`'s `policy()`, which `retro.py gather
--decisions` and `decisions.py add --zone` read, accepts the same table with the same
refusals and leaves the zones' levels as they are; on Python 3.10 it refuses
`[decisions.paths]` with its existing "use 3.11+" message, as it refuses any other form its
line reader can't read.

### How a part sets a level

`src/shipmill/classify.py` keeps its detection rules unchanged: a part never adds a zone to
a change, it only sets the level of a zone code already detects on a path. For each changed
path that puts a zone in:

- a part of that zone whose glob matches the path gives the path's level; when several of
  the zone's globs match, the strictest of their levels
- no matching part: the zone's level, from `[decisions]` or its default

A glob matches as a `REVIEW.md` Protected areas glob does in `classify.py` and `pr_gate.py`
today: `fnmatch`, where `*` also matches `/`, or the path sits under the glob's directory.

The zone's level for the change is the strictest among its paths' levels, and the change's
level is the strictest among its zones, as spec 030 says. A zone detected without a path
rule (`decision-policy` from a changed `[decisions]` table, `scope` from a status line,
`contract-change` from a changelog entry) keeps its zone level. The parts are read from the
config at `--ref` (default `origin/HEAD`) like every level, so a pull request that adds or
lowers a part is classified by the parts it would replace, and is `decision-policy`, which
only the maintainer merges.

### Where each level comes from

`shipmill decide levels [--json]` lists each zone's parts after it:

- JSON: each zone gains `"paths": [{"glob", "level", "source"}]`, `source` always `config`,
  in the config's order; `[]` for a zone without parts
- Text: one line per part under its zone, `  part ".github/workflows/**"  notify  config
  [decisions.paths.security]`

`shipmill decide classify [--json]` says, for each detected zone, which path set its level
and from where:

- JSON: each zone gains `"paths": [{"path", "level", "source", "glob"}]`, one entry per
  changed path that put the zone in, `source` one of `default`, `config`, or `part`, and
  `glob` the matching part's glob, or `null` for a zone level; a zone detected without a
  path rule lists none. Its `level` and `reason` keep their meaning, so `pr_gate.py`, which
  reads `zone`, `level`, and `reason`, judges as before
- Text: a path whose level a part set ends its reason with `(notify by
  [decisions.paths.security] ".github/workflows/**")`

`skills/github-pr-triage/scripts/pr_gate.py` needs no change: a part at `never` makes its
zone `never`, so the pull request reads `MAINTAINER_ONLY`; a part at `notify` prints its
`notify:` line; `app_gh.py`'s merge refusal follows the same classification.

### `doctor`

`src/shipmill/doctor.py`'s `decisions` block, for a config with `[agents]`, adds one PASS
line per part (zone, glob, level), and a WARN for each part set below its zone's default,
naming both levels, as it warns for a lowered zone.

### Docs

The "Who decides" sections of `docs/flow.md` and
`skills/github-issue-triage/references/needs-decision.md` say a zone's paths may take their
own level under `[decisions.paths.<zone>]`, and that the strictest level among a change's
paths wins.

### Upgrading

The table is optional, so no config fails and no spec 014 upgrade is needed. A repo without
`[decisions.paths]` is classified exactly as before.

## Acceptance criteria

- S-057-1: `Policy.parse` of a config with `[decisions.paths.security]` setting `".github/workflows/**" = "notify"` keeps the part, and `shipmill decide levels --json` lists it under `security`'s `paths` as `{"glob": ".github/workflows/**", "level": "notify", "source": "config"}`, with `"paths": []` for every zone without parts; the text output prints a `part` line under `security` naming the glob, the level, and `[decisions.paths.security]`
- S-057-2: `Policy.parse` exits 2 naming the key for `paths` that isn't a table, for a zone under `paths` that is `scope`, `contract-change`, `decision-policy`, `release`, or no zone id (listing `direction`, `protected`, and `security`), and for a part's value that isn't one of the four levels
- S-057-3: `Policy.parse` exits 2 naming the floor for a `security` part at `act` and a `direction` part at `act`, and accepts a `security` part at `notify`, a `protected` part at `never`, and a `protected` part at `act`
- S-057-4: `Policy.parse` exits 2 for an empty glob, an absolute one, one holding `..`, a `security` glob not starting `.github/`, and a `direction` glob that is neither `docs/product.md` nor under `docs/product/`
- S-057-5: With the S-057-1 part on the base, `shipmill decide classify --files .github/workflows/ci.yml --json` reports `security` at `notify` with a `paths` entry `{"path": ".github/workflows/ci.yml", "level": "notify", "source": "part", "glob": ".github/workflows/**"}`, and `--files .github/CODEOWNERS` reports `security` at `ask` with `source` `default` and `glob` `null`
- S-057-6: With the same part, `--files .github/workflows/ci.yml .github/CODEOWNERS` reports `security` at `ask`; with two `security` globs matching one path at `notify` and `ask`, the path reads `ask`; with `protected = "notify"` and a `protected` part `"src/settings/**" = "ask"`, a path a `REVIEW.md` Protected areas glob covers under `src/settings/` reads `ask`
- S-057-7: A part never adds a zone: with `[decisions.paths.protected] "src/**" = "ask"` and no `REVIEW.md` Protected area covering it, `--files src/x.py` reports no zone and `"level": null`
- S-057-8: `shipmill decide classify --pr N` on a pull request that adds `[decisions.paths.security] ".github/workflows/**" = "notify"` and edits `.github/workflows/ci.yml`, against a base without parts, reports `security` at `ask` for the workflow and `decision-policy` at `never`
- S-057-9: `pr_gate.py` on a pull request whose only zone comes from a `protected` part at `never`, in a checkout whose base config has `[agents]`, prints `MAINTAINER_ONLY` and exits 7; on one whose only zone comes from a `security` part at `notify` it keeps the CI verdict and prints a `notify:` line
- S-057-10: `decisions.py`'s `policy()` on Python 3.11+ reads a config with valid `[decisions.paths]` parts with every zone's level unchanged, raises `LogError` for each malformed part S-057-2, S-057-3, and S-057-4 name, and on Python 3.10 raises its "use 3.11+" `LogError` for a config holding `[decisions.paths.<zone>]`
- S-057-11: `shipmill doctor` on a config with `[agents]` and parts prints one PASS line per part naming its zone, glob, and level, and WARNs for a part set below its zone's default, naming both levels
- S-057-12: The "Who decides" sections of `docs/flow.md` and `skills/github-issue-triage/references/needs-decision.md` name `[decisions.paths.<zone>]`, the three zones that take parts, and that the strictest level among a change's paths wins

## Out of scope

- Parts of a zone code doesn't detect by path (`scope` by kind of decision, `contract-change`, `interpretation`): a separate opportunity, since nothing but a path places a change in a part today
- Counting asks, decided markers, or vetoes per part in the retro, and a retro proposal for a part: the zone line and the markers still name the zone alone (spec 058 counts per zone)
- A part that adds paths to a zone, such as a `protected` glob without a `REVIEW.md` Protected area: `REVIEW.md` stays the one place that says what is protected
- Most-specific-glob-wins or ordered overrides: the strictest level wins, as D-48 says for zones
- Changing a level by itself: a part changes only by the maintainer's edit of `[decisions]`, which is `decision-policy`

## Decisions relied on

- D-4: the parts live in `.github/shipmill.toml`, under `[decisions]`
- D-34: `direction` keeps its floor `ask`, so no part lowers it further
- D-48: floors hold for parts, the strictest level wins, and levels are read from the base branch, never from the pull request
- D-54: `shipmill gh`'s `never` merge refusal follows the classification, parts included

## Issues

- shipmill/shipmill#1070: S-057-1, S-057-2, S-057-3, S-057-4
- shipmill/shipmill#1071: S-057-5, S-057-6, S-057-7, S-057-8, S-057-9
- shipmill/shipmill#1073: S-057-10
- shipmill/shipmill#1076: S-057-11, S-057-12

## Verification

- S-057-1: read `decide.py`'s `_parts` and `Part.record`/`Part.text`, and ran tests/test_decide_parts.py: the part is kept, `decide levels --json` lists it under `security` with `"paths": []` elsewhere, and the text prints its `part` line, holds
- S-057-2: read `_parts` and `_part_zone`'s refusals and ran tests/test_decide_parts.py: a non-table `paths` or zone table, `scope`, `contract-change`, `decision-policy`, `release`, an unknown zone (listing the three), and a value that is no level each exit 2 naming the key, holds
- S-057-3: read `_part_floor_problem` and ran tests/test_decide_parts.py: `security` and `direction` parts at `act` are refused naming the floor; `security` at `notify` and `protected` at `never` and `act` parse, holds
- S-057-4: read `_glob_problem` and ran tests/test_decide_parts.py: an empty, absolute, or `..` glob, a `security` glob outside `.github/`, and a `direction` glob outside `docs/product.md` and `docs/product/` exit 2, holds
- S-057-5: ran tests/test_decide_cli.py's S-057-5 tests: `classify --files .github/workflows/ci.yml --json` reports `security` at `notify` with the part's `paths` entry, and `.github/CODEOWNERS` reads `ask` with `source` `default` and `glob` `null`, holds
- S-057-6: ran tests/test_decide_cli.py's S-057-6 tests: both paths read `ask`, two matching globs give the stricter `ask`, and a `protected` part at `ask` raises its path above `protected = "notify"`, holds
- S-057-7: ran tests/test_decide_cli.py's S-057-7 test: `--files src/x.py` with only a `protected` part reports no zone and `"level": null`, holds
- S-057-8: ran tests/test_decide_cli.py's S-057-8 test: a pull request adding the part is judged by the base, `security` at `ask` and `decision-policy` at `never`, holds
- S-057-9: ran tests/test_pr_gate.py's S-057-9 tests: a `protected` part at `never` prints `MAINTAINER_ONLY` and exits 7; a `security` part at `notify` keeps the CI verdict and prints a `notify:` line, holds
- S-057-10: ran tests/test_decisions_parts.py: `policy()` reads valid parts with the zone levels unchanged, raises `LogError` for each malformed part, and its 3.10 reader raises "use 3.11+", holds
- S-057-11: ran `shipmill doctor` on this repo's config with two `security` parts (`notify`, `never`) added: one `part [decisions.paths.security] "<glob>" <level>` PASS each, and one WARN for the `notify` part naming `notify` and the default `ask`; tests/test_doctor_decisions.py's S-057-11 tests also cover no part line without parts or without `[agents]`, holds
- S-057-12: read the "Who decides" sections of `docs/flow.md` and `needs-decision.md`, which name `[decisions.paths.<zone>]`, `direction`, `security`, and `protected`, and that the strictest level among a change's paths wins, and ran tests/test_who_decides.py, holds
