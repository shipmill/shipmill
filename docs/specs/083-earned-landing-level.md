# S-083: A pull request lands at the level its evidence and its area's production record earn

status: approved
serves: G-1, G-2

## Problem

`[autonomy] land` and the decision levels are set per repo, per zone (spec 030), or per path
(spec 057), by hand. A one-line fix and a change to a sensitive file land under the same level
when they sit in the same zone, so the maintainer either keeps `ask` for the whole zone (and
approves safe changes) or lowers it for the whole zone (and trusts risky ones on faith).
Nothing lowers the level for one pull request on its evidence, and nothing a release does in
production moves the level afterwards: the decision retro (spec 058, #1046, #1009) proposes a
lower level on the maintainer's agreement rate, not on what the changes did once shipped
(#1305, which the maintainer accepted on 2026-11-18).

It hits maintainers who run `land = "act"` or want to: today they choose between approving
every pull request in a zone and trusting every one. Prior art: the Earned Autonomy entry of
GitLab's Transcend hackathon (2026-11-18) gives each merge request evidence, a risk level, and
a ledger of production outcomes that raises the level of the area a failed release touched
and lowers it after clean releases; its published lesson was that one global threshold let
riskier kinds of change through, so each kind (infrastructure, a new advisory, the system's
own controls) got a ceiling of its own.

This spec keeps every rule of spec 030 and spec 057 that guards a level: the levels are read
from the base branch, never the pull request (D-48); the strictest level among a change's
zones and paths wins; no level goes below its zone's floor; and `[autonomy] land` stays the
stage's ceiling over every zone (D-51). What it adds is a level that moves inside the bounds
the maintainer writes, on evidence code reads from the forge and the checkout (N-2, D-6).

## Behaviour

### The production record of an area

An **area** is the parent directory of a path (`src/app` for `src/app/a.py`, `.` for a file at
the repository's root). A change touches the areas of the paths it changes.

A new module, `src/shipmill/area_record.py`, reads the record from GitHub and the checkout
only, through `src/shipmill/github.py` and `src/shipmill/gitrepo.py`:

1. **A failed release.** An issue labelled `[operate] incident_label` (default `incident`)
   whose body holds the hidden line `shipmill operate` writes,
   `<!-- shipmill:incident env=<env> tag=<tag> to=<to> state=<state> -->`
   (`src/shipmill/operate.py`'s `Incident.read`), opened by a bot or by an OWNER, MEMBER, or
   COLLABORATOR (D-16). An incident by anyone else, or without the line, counts for nothing.
   The release `tag` failed in `env`
2. **The areas it touched.** The parent directories of `git diff --name-only <from> <tag>`,
   where `<from>` is the line's `to` (the tag the rollback returned to), or, when it reads
   `-`, the newest tag before `<tag>` in version order among the tags the checkout holds. A
   tag the checkout lacks is a read that fails
3. **A clean release.** A tag newer than the failed one in version order whose deployment to
   the same environment reached `success` (`GitHub.deployments` and
   `GitHub.deployment_statuses`, as `shipmill operate` reads them), that no counted incident
   names, and whose own diff from the tag before it touches the area
4. **The area's state.** An area is **raised** while, after its newest failed release, fewer
   than `[decisions] clean_releases` (default 3, an integer from 1 to 20) clean releases have
   touched it; once that many have, it is **cleared** and reads like an area with no record

`shipmill decide record [--repo DIR] [--json]` (`src/shipmill/cli.py`, beside `decide levels`)
prints one line per area with a failed release, raised areas first:

```text
RAISED  src/app  v1.4.0 failed in production (#212), 1 of 3 clean releases since (v1.4.1)
CLEARED src/lib  v1.2.0 failed in production (#180), 3 of 3 clean releases since (v1.2.1, v1.3.0, v1.3.2)
```

`--json` prints `{"clean_releases": N, "areas": [{"area", "state", "incident", "env", "tag",
"clean": [<tag>...]}]}`. No incident prints `no failed release on record`. A GitHub read that
fails, or a tag the checkout lacks, exits 2 naming what couldn't be read, never a partial
record (Q-1).

### A new zone: `area-record`

The zone table (`skills/github-issue-triage/scripts/decisions.py`'s `ZONES`, and `Zone` in
`src/shipmill/decide.py`) gains `area-record` after `protected`: a change that touches a
raised area. Its default is `act` and it has no floor, so no repo's pull requests wait on it
until the maintainer sets `[decisions] area-record = "ask"` (or `notify`) (D-63).
`src/shipmill/classify.py` detects it for `--pr` and `--files` alike, with the reason
`<area> is raised: <tag> failed in <env> (#N), K of M clean releases since`. Like every zone
its level comes from the base and the strictest level wins, so at `ask` the next change to a
raised area waits for the maintainer's answer, and after `clean_releases` clean releases it
lands as it did before.

`classify.py` reads the record only when the base sets `area-record` above `act` or has a
`[decisions.earned]` table, and the merge-checks reading below only when it has the table; a
repo that sets neither makes no new read, so a read that fails can't hold its merges.

### The earned level

A new optional table of `[decisions]` in `.github/shipmill.toml` (D-4), parsed in
`src/shipmill/decide.py` beside the parts of spec 057:

```toml
[decisions.earned]
protected = "act"      # the lowest level a pull request may earn in this zone
security = "notify"
max_lines = 200        # the most lines (added plus deleted) a change may hold to earn
```

`earned` becomes a reserved key of `[decisions]`, as `paths` and `veto_hours` are, and so
does `clean_releases`. Only `protected` and `security` take a bound. The parse exits 2,
naming the key and the fix, for any other zone (`scope takes no earned level: only protected
and security do`), a value that is no level, a bound below the zone's floor (`security =
"act" is below its floor notify`), and a `max_lines` that isn't an integer from 1 to 10000
(default 200). `decide levels` shows each zone's bound (`"earned": "act"` in its JSON row,
`null` without one, and `  earned act  config [decisions.earned]` in the text). Without the
table no pull request earns anything, so no repo changes behaviour by upgrading (D-63).

A new module, `src/shipmill/earned.py`, holds the rule as a pure function of the change's
paths and line counts, the policy, the touched areas' states, and the merge-checks reading,
so the seeded set below can run it without GitHub. For `decide classify --pr N` only (a change
given as `--files` has no evidence, and earns nothing), a path that puts `protected` or
`security` in, at a level above its zone's bound, takes the bound instead when every piece of
evidence holds:

| Evidence | Holds when |
|---|---|
| `checks` | the default branch requires at least one status check that proves, by `src/shipmill/merge_checks.py`'s reading (spec 080); a rules read that fails does not hold |
| `size` | the pull request's added plus deleted lines, from its files, are at most `max_lines` |
| `record` | no area the change touches is raised |
| `kind` | no path the change touches is of a ceiling kind (below) |

A path whose level is `never` (the zone's or a part's) never earns, and no path earns below
its zone's floor. `pr_gate.py` needs no change: it reads each zone's `level` and `reason` from
classify as today, so an earned `act` lifts the needs-decision ask, an earned `notify` prints
its `notify:` line, and `[autonomy] land` stays the ceiling of the merge (D-51).

### The ceiling kinds

Some kinds of change never earn, whatever their evidence and however clean the record. A path
is of a ceiling kind when it matches one of these globs (matched as spec 057 matches parts):

| Kind | Paths |
|---|---|
| `controls` (shipmill's own, and every workflow and action, the deploy workflows of spec 063 and the one behind a required check among them) | `.github/shipmill.toml`, `.github/CODEOWNERS`, `CODEOWNERS`, `REVIEW.md`, `CLAUDE.md`, `AGENTS.md`, `docs/decisions.md`, `DECISIONS.md`, `.claude/**`, `.claude-plugin/**`, `.github/workflows/**`, `.github/actions/**` |
| `infrastructure` | `**/*.tf`, `**/*.tfvars`, `**/Dockerfile`, `**/docker-compose*.yml`, `**/migrations/**`, `infra/**`, `deploy/**`, `k8s/**`, `helm/**` |
| `dependencies` (where a new advisory comes in) | `pyproject.toml`, `uv.lock`, `requirements*.txt`, `poetry.lock`, `package.json`, `package-lock.json`, `pnpm-lock.yaml`, `yarn.lock`, `go.mod`, `go.sum`, `Cargo.toml`, `Cargo.lock`, `Gemfile`, `Gemfile.lock`, `.github/dependabot.yml`, each also under any directory |

The table lives in `earned.py`; extending it is a contract tweak, not a change to this spec.

### What classify and the review record show

`decide classify --pr N --json` gains a top-level `landing` object: `{"level", "earned":
bool, "evidence": [{"name", "holds", "detail"}]}`, one entry per row of the evidence table, in
its order (`size`: `42 of at most 200 lines`; `record`: the raised areas, or `no raised
area`; `kind`: the first path of a ceiling kind and its kind, or `no ceiling path`; `checks`:
the proving check's name, or why none). A zone whose level a bound set gains `"earned":
{"from", "to"}` and its reason ends `(earned <to> from <from> by [decisions.earned])`. The
text output prints `landing: <level>` and one line per piece of evidence. Without
`[decisions.earned]`, `landing.earned` is false; `size` and `kind`, read from the pull
request, are still shown, and `checks` (and `record`, unless `area-record` is above `act`)
hold false with the detail `not read: [decisions.earned] is not set`.

`shipmill review record` (`src/shipmill/review_record.py`) appends a `## Landing` section to
the review it posts, holding the landing level and each evidence line of `decide classify --pr
N` at the recorded head, so every agent pull request with a review record shows its level and
the evidence behind it on GitHub. The body's first line stays the verdict's marker that
`pr_gate.py` reads, and a classify that fails writes no review (exits 2), as every other
check of `review record` does.

### The seeded set

Before `earned.py` exists, its first build issue commits `tests/landing/seeded.toml`: cases
`L-1`, `L-2`, and so on, each holding the changed paths with their line counts, the base's
`[decisions]` table, the raised areas, whether a required check proves, and the expected
landing level. `tests/test_landing_seeded.py` runs `earned.py`'s function over every case and
fails on any miss, printing `MISS L-n: expected <level>, got <level>` for each, so a miss is
published in the public CI log of the pull request that causes it. A case's expectation
changes only in a pull request that says why in its body; it is a test of deterministic code,
not an eval of the agents' instructions (D-74).

### Docs

The "Who decides" sections of `docs/flow.md` and
`skills/github-issue-triage/references/needs-decision.md` name the `area-record` zone,
`[decisions.earned]`, the four pieces of evidence, and the ceiling kinds;
`skills/github-pr-triage/references/landing.md` names the `## Landing` section of the review
record.

Touched areas: `src/shipmill/area_record.py`, `src/shipmill/earned.py`,
`src/shipmill/decide.py` (`[decisions.earned]`, `clean_releases`, the `area-record` zone),
`src/shipmill/classify.py`, `src/shipmill/review_record.py`, `src/shipmill/cli.py` (`decide
record`), `src/shipmill/github.py`, `src/shipmill/merge_checks.py` (read),
`src/shipmill/operate.py` (`Incident.read`, read),
`skills/github-issue-triage/scripts/decisions.py` (`ZONES`, `policy()`), `docs/flow.md`,
`skills/github-issue-triage/references/needs-decision.md`,
`skills/github-pr-triage/references/landing.md`, `tests/landing/seeded.toml`, and
`tests/test_landing_seeded.py`.

## Acceptance criteria

- S-083-1: `Policy.parse` keeps `[decisions.earned] protected = "act"`, `security = "notify"`, and `max_lines = 200`, and `shipmill decide levels --json` gives `protected` the row key `"earned": "act"` and every zone without a bound `"earned": null`; the parse exits 2 naming the key for a bound on any zone but `protected` and `security`, a value that is no level, `security = "act"` (below its floor notify), and a `max_lines` or `clean_releases` that isn't an integer in its range
- S-083-2: `decisions.py`'s `policy()` on Python 3.11+ reads a config holding valid `[decisions.earned]` and `clean_releases` with every zone's level unchanged, raises `LogError` for each malformed value S-083-1 names, and on Python 3.10 raises its "use 3.11+" `LogError` for a config holding `[decisions.earned]`
- S-083-3: the zone table lists `area-record` after `protected` with the default `act` and no floor, `[decisions] area-record = "ask"` parses, and a config without the key reads `act`
- S-083-4: `shipmill decide record --json` reads an incident labelled `incident`, opened by a bot, whose body holds `<!-- shipmill:incident env=production tag=v1.4.0 to=v1.3.2 state=rolled-back -->`, as a failed release raising the parent directories of `git diff --name-only v1.3.2 v1.4.0`; with `to=-` it diffs from the newest earlier tag by version; the same issue opened by a user whose association is NONE, or without the line, raises nothing
- S-083-5: after that incident, an area reads `RAISED` with `1 of 3 clean releases since` when one later tag reached `success` in `production`, has no incident, and touched it, and `CLEARED` after three; a later tag that didn't touch the area, didn't reach `success` there, or has its own incident is not counted; `clean_releases = 1` clears it after one
- S-083-6: `decide record` exits 2 naming what couldn't be read, printing no area, when the issues or deployments read fails or a tag an incident names is missing from the checkout; `decide classify` exits 2 the same way, so `pr_gate.py` fails closed, when the base sets `area-record` above `act` or has `[decisions.earned]`, and makes neither read (no issues, deployments, or rules call) when it sets neither
- S-083-7: with `area-record = "ask"` on the base, `decide classify --files src/app/a.py --json` reports `area-record` at `ask` with a reason naming `src/app`, the tag, the incident, and the clean releases counted, while `src/app` is raised; it reports no `area-record` zone for a cleared area or `src/lib/b.py` in an area with no record
- S-083-8: with `[decisions.earned] protected = "act"` on the base, `decide classify --pr N --json` on a pull request whose only zone is `protected` at `ask`, holding 40 changed lines, under a default branch that requires a check that proves, touching no raised area and no ceiling path, reports `protected` at `act` with `"earned": {"from": "ask", "to": "act"}` and a reason ending `(earned act from ask by [decisions.earned])`, and a `landing` object with `level` `act`, `earned` true, and the four evidence entries holding, in the table's order
- S-083-9: the same pull request keeps `protected` at `ask`, `landing.earned` false, and the failing entry's `holds` false with its detail, when only one of these differs: it holds 201 lines with `max_lines = 200`; the default branch requires no check that proves, or its rules read fails; it touches a raised area; it changes a ceiling path (the entry naming the path and its kind)
- S-083-10: no path earns when it is `.github/shipmill.toml`, `REVIEW.md`, `.github/workflows/ci.yml` (a workflow that deploys nothing), a deploy workflow, `.github/actions/setup/action.yml`, `infra/main.tf`, `db/migrations/0001.sql`, `uv.lock`, or `web/package.json`, whatever the evidence; a path a part sets at `never` stays `never`; `decide classify --files` never earns; and a pull request that adds `[decisions.earned]` is judged without it, at the base's levels, with `decision-policy` at `never`
- S-083-11: `shipmill review record` posts a review whose first line is still the verdict's marker and whose body holds a `## Landing` section with the landing level and one line per piece of evidence from `decide classify --pr N` at the recorded head; when that classify exits 2, `review record` exits 2 and posts nothing
- S-083-12: `tests/landing/seeded.toml` holds at least 12 cases with ids `L-n`, among them one per ceiling kind, one per piece of evidence failing alone, a raised and a cleared area, a path a `never` part sets, and a change no zone detects; `tests/test_landing_seeded.py` runs `earned.py`'s function over each and fails naming every miss as `MISS L-n: expected <level>, got <level>`
- S-083-13: the "Who decides" sections of `docs/flow.md` and `skills/github-issue-triage/references/needs-decision.md` name the `area-record` zone, `[decisions.earned]` with its two zones, the four pieces of evidence, and the three ceiling kinds; `skills/github-pr-triage/references/landing.md` names the review record's `## Landing` section

## Out of scope

- A numeric risk score, weighted evidence, or a penalty that halves per clean release: the evidence is four checks that each hold or don't, and the record is raised or cleared, so a test can state each case
- Evidence from replayed traffic, an advisory's reachability, or an infrastructure plan: each needs a source outside GitHub and the checkout (D-6, N-1)
- A test proof (spec 076) or a review's confirmed findings (spec 075) as evidence: a follow-up once this exists; `pr_gate.py` already needs a review record before an agent's code pull request lands
- Earning in any zone but `protected` and `security`: `direction`, `decision-policy`, `scope`, `accepted-spec`, `rule-departure`, `contract-change`, and `deploy-step` keep their level, and so does the `land` stage of `[autonomy]`, which stays the ceiling (D-51)
- A failed release found other than by `shipmill operate`'s incident line: a person's incident issue, a postmortem, a hotfix release, or a revert of a red default branch (spec 079, which is not a production failure); each can be its own request
- Areas set by config (`[decisions.areas]` globs) or by `REVIEW.md` sections: see "Decisions for you" in the spec PR
- Counting earned landings in the decision retro (spec 058) or in `metrics.py`'s change failure rate: the retro still counts per zone, and a measure of earned landings can be its own request
- A label or a separate comment on the pull request naming its level: the review record holds it

## Decisions relied on

- D-4: `[decisions.earned]` and `clean_releases` live in `.github/shipmill.toml`
- D-6: the record reads only GitHub's issues and deployments and the checkout
- D-16: an incident counts only from a bot or a trusted author
- D-48: levels are read from the base branch; the strictest level wins; no level goes below its zone's floor; a change to `[decisions]` is `decision-policy`
- D-51: `[autonomy] land` stays the ceiling over every zone
- D-63: the new zone defaults to `act` and the new table is optional, so no repo changes behaviour by upgrading
- D-74: the seeded set is a test of code, not an eval

## Issues

- shipmill/shipmill#1544: S-083-1, S-083-2, S-083-3
- shipmill/shipmill#1545: S-083-4, S-083-5
- shipmill/shipmill#1546: S-083-6, S-083-7
- shipmill/shipmill#1547: S-083-12
- shipmill/shipmill#1548: S-083-8, S-083-9, S-083-10
- shipmill/shipmill#1549: S-083-11, S-083-13

## Verification

Filled in when the spec reaches `built`: one line per criterion id, saying how it was
checked against the default branch (beyond its tests) and the result.
