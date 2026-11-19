# S-078: Agent quality measures, and a drift report for CI and review

status: built
serves: G-2

## Problem

The watch reports what the agents did, not how well, and states, not trends.
`skills/github-ship-watch/scripts/metrics.py` gives DORA, issue to release and its stages
(spec 066), human touch, and agent share; none of them says whether an agent's pull request
landed as first written or came back for fixes (#384). And `watch_state.py` reads the line as
it stands now: a flaky test that starts failing more often, or CI that goes red more often,
shows only once something is stuck (#385). Both requests were grouped into #1229, which the
maintainer accepted on 2026-11-18.

It hits the maintainer who trusts agents without reading every diff (G-2): a slide in review
quality or CI health costs a broken release or a stuck line before anything reports it.

This spec builds on spec 066 (the same script, the same window, the same registry of spec
027) and adds two things: four measures of agent pull requests in `metrics.py`, and a
detector, `trends.py`, that compares a series' newest bucket with its own recent past. No
model reads or judges anything in either.

## Behaviour

### Agent quality measures

`skills/github-ship-watch/scripts/metrics.py` adds four measures after Agent share, over the
agent pull requests merged in the window: the pull requests Agent share counts as an
agent's (`agent_made`), so their count is Agent share's numerator.

Three readings they share:

- **A verdict** is a review of the pull request that is either a review record (spec 055:
  its body's first line is `<!-- shipmill:review merge -->` or `<!-- shipmill:review refuse
  -->`, and its author is a Bot, a login ending `[bot]`, or a `--bot` login), or a review in
  state APPROVED or CHANGES_REQUESTED by an OWNER, MEMBER, or COLLABORATOR who is a person
  as Human touch reads one. Any other review (a COMMENTED review, an outsider's, D-16) is
  no verdict
- **A review round** is one distinct commit the pull request's verdicts were given at (the
  review's commit), so two verdicts on one head are one round
- **A fix commit** is a commit of the pull request with one parent (a merge of the base
  isn't one) whose author date is later than the pull request's creation. A rebase keeps
  author dates, so rebased commits written before the pull request opened aren't fix
  commits

The measures:

| Measure | Value |
|---|---|
| Rework cycles | per agent pull request, its review rounds beyond the first plus its fix commits; the value is the mean, and the detail gives the mean review rounds and the mean fix commits |
| First-pass merge rate | agent pull requests with 0 rework cycles / agent pull requests |
| Review time | the pull request's creation to its first verdict: median and p90 in hours, a duration measure like Lead time; a pull request with no verdict (a docs-only one needs no record) is left out, and the detail says how many |
| Plan match | of the agent pull requests whose body has one `## Plan` section with a `Files:` line naming at least one path in backticks, those whose every changed file matches one of those paths / those pull requests; the detail says how many had no such plan |

- **A changed file matches a `Files:` path** when it equals it, when the path ends in `/`
  and the file is under it, or when the path is a glob it matches, read as a `Revisit on:`
  path is (`**` any run, `*` any run without `/`, `?` one character other than `/`; spec
  061). A renamed file counts under its new path. The plan is the body's as merged
- Rework cycles has unit `count`; First-pass merge rate and Plan match are ratios shown as a
  percent with `n of m` in the detail, like Human touch
- Each reads "no data" with a null value when there is nothing to measure (no agent pull
  request merged in the window, none with a verdict, none with a plan), never 0
- The measures follow Agent share in the table, the markdown, and the JSON's `measures`
  list; no other measure changes. What the script reads beyond today, through gh only: each
  merged pull request's reviews (state, author, author association, commit, submission time,
  and body's first line), its commits' author dates and parent counts, and its changed files

**The registry.** Four metrics join the spec 027 registry in `src/shipmill/product.py`:
`first_pass_merge_rate` and `plan_match` (target `<n>%`), and `review_time_median` and
`review_time_p90` (target `<n>h` or `<n>d`). `retro.py`'s `METRIC_MEASURES` maps each to its
measure, and `skills/shipmill-setup/SKILL.md` lists them with the registry it offers. Rework
cycles joins no registry: the registry has no unit for a count per pull request.

### The drift report

A new script, `skills/github-ship-watch/scripts/trends.py <owner/repo> --repo-dir <dir>
[--until TIME] [--json]`, compares each configured series' newest bucket with the buckets
before it. Python 3.10, standard library only, read-only; it reads GitHub through gh and
the checkout's config, and nothing else.

**The config.** One new top-level section of `.github/shipmill.toml` (D-4), read from the
default branch; without it nothing is read and nothing is reported (off by default):

```toml
[trends]
series = ["ci_pass_rate", "flaky_reruns", "review_time", "lead_time"]
bucket_days = 7     # default
baseline = 8        # default: the buckets before the newest one
log_sigma = 1.0     # default
report_sigma = 2.0  # default
```

`series` is required and names at least one of the four; `bucket_days` is at least 1,
`baseline` at least 4, `log_sigma` above 0, and `report_sigma` at least `log_sigma`.
`src/shipmill/config.py` reads the section strictly: an unknown key, an unknown series, or a
value out of range fails the load naming the key (Q-1). `shipmill doctor` prints one line
for the section, the series and the bands.

**The series.** The newest bucket is the `bucket_days` days ending at `--until` (default
now), and the baseline the `baseline` buckets before it. Each bucket's value:

| Series | Value of a bucket | Worse when |
|---|---|---|
| `ci_pass_rate` | workflow runs on the default branch created in the bucket that concluded `success` / those that concluded `success`, `failure`, or `timed_out`; a cancelled, skipped, or unfinished run isn't counted | lower |
| `flaky_reruns` | workflow runs created in the bucket, on any branch, whose attempt number is above 1 and that concluded `success`: a run that went green only on a rerun | higher |
| `review_time` | the median Review time, as above, of the agent pull requests merged in the bucket | higher |
| `lead_time` | the median Lead time for changes, as `metrics.py` reads it, of the pull requests first shipped by a stable release published in the bucket | higher |

`review_time` and `lead_time` are computed by `metrics.py`'s own functions, from one read
over the whole span and split by bucket. Runs are read per bucket with the API's `created`
filter; a bucket with more runs than the API lists (1,000) is read day by day, and a day
that still has more exits 2 naming it, never a truncated count.

**The band.** For each series, over the baseline buckets that have a value: the mean and
the sample standard deviation σ. The deviation is how far the newest bucket is from the mean
in the series' worse direction, in σ; a bucket better than the mean has deviation 0. Its
tier:

- `no data`: the newest bucket has no value, or fewer than 4 baseline buckets have one
- `ok`: the deviation is below `log_sigma`
- `log`: at least `log_sigma` and below `report_sigma`: a line in `trends.py`'s own output,
  nowhere else
- `report`: at least `report_sigma`: the watch reports it, below
- A flat baseline (σ is 0): `ok` when the newest bucket equals the mean or is better, and
  `report` with the deviation printed as `flat baseline` when it is worse

`trends.py` prints one line per series: its tier, the newest value, the mean, σ, and the
deviation; `--json` prints one object per series with those and its buckets' values. A
`report` or `log` line carries a diagnosis, read from the same data and nothing more:

- `ci_pass_rate`: the up to 3 workflows with the most failed runs in the newest bucket, each
  with its count and its newest failed run's URL
- `flaky_reruns`: the up to 3 workflows with the most such runs, each with its count and its
  newest one's URL
- `review_time`, `lead_time`: the up to 3 pull requests with the longest time in the newest
  bucket, each with its number and hours

A workflow is named by its file's path when that file is on the default branch, and as
`(other workflow)` otherwise; no title, body, branch name, or other text an outsider wrote
is printed (D-16). Exit 0 with or without a drift, 2 on bad input, a config without
`[trends]`, or a gh failure.

**The watch reports it.** `skills/github-ship-watch/scripts/watch_state.py`'s full report
(the run with no `--tier`, `--sweep`, or `--host`), for a config with `[trends]`, runs the
detector and adds one row per series at the `report` tier:

`DRIFT <series> <newest value> against mean <mean>, <deviation>σ over <N> buckets of <D>d: <diagnosis>`

with the `trends.py` command that prints the whole report as its fix (spec 011). DRIFT is
reported, never an action: it doesn't change the watch's exit code, and it is in no tier
and not in the sweep, so no gate tick reads it and none starts a session on it (D-58
unchanged). `fleet.py` shows it with a repo's other reported rows. `--no-trends` leaves the
read out. A `trends.py` failure stops the watch (exit 2) like any other read.

`skills/github-ship-watch/SKILL.md` documents the four measures under Metrics, and the
section, the series, the tiers, and the DRIFT row under a new Trends heading and in its
report: a drift is told to the maintainer with its diagnosis, and the watch changes nothing
on it.

Touched areas: `skills/github-ship-watch/scripts/metrics.py`,
`skills/github-ship-watch/scripts/trends.py`, `skills/github-ship-watch/scripts/watch_state.py`,
`skills/github-ship-watch/scripts/retro.py` (`METRIC_MEASURES`),
`skills/github-ship-watch/scripts/fleet.py` (its reported states),
`skills/github-ship-watch/SKILL.md`, `skills/shipmill-setup/SKILL.md`,
`src/shipmill/product.py` (the registry), `src/shipmill/config.py` and
`src/shipmill/doctor.py` (`[trends]`), `.github/shipmill.toml` (the `[trends]` section),
`tests/test_metrics.py`, and `tests/test_trends.py`.

## Acceptance criteria

- S-078-1: `metrics.py --json` lists Rework cycles, First-pass merge rate, Review time, and Plan match right after Agent share, over the agent pull requests merged in the window (the ones Agent share counts), each "no data" with a null value when it has nothing to measure; Review time carries `p90` and `count` in `hours`
- S-078-2: a verdict is a review whose body's first line is a `shipmill:review` marker by a Bot, a `[bot]` login, or a `--bot` login, or an APPROVED or CHANGES_REQUESTED review by an OWNER, MEMBER, or COLLABORATOR person; a COMMENTED review, an outsider's review, and a marker review by a person are none, and two verdicts at one commit are one review round
- S-078-3: a fix commit is a one-parent commit of the pull request whose author date is later than the pull request's creation; a merge of the base, and a commit authored before the creation and rebased after it, are not
- S-078-4: over a scripted forge, a pull request's rework cycles are its review rounds beyond the first plus its fix commits, Rework cycles is their mean with the mean rounds and mean fix commits in its detail, and First-pass merge rate is the share with 0 rework cycles, with `n of m` in its detail
- S-078-5: Review time runs from the pull request's creation to its first verdict; an agent pull request with no verdict is left out, and the detail gives how many were
- S-078-6: Plan match counts an agent pull request as matching when every changed file equals a backticked `Files:` path of its one `## Plan`, is under one ending in `/`, or matches one as a glob (`**`, `*`, `?` as spec 061 reads them), a renamed file by its new path; a pull request with no plan, or a `Files:` line with no backticked path, is left out of both counts and counted in the detail
- S-078-7: `shipmill product check` accepts a goal measure naming `first_pass_merge_rate` or `plan_match` with a `%` target and `review_time_median` or `review_time_p90` with an `h` or `d` target, and refuses each with another unit; `retro.py`'s `METRIC_MEASURES` maps each to its measure, and shipmill-setup's SKILL.md lists them
- S-078-8: a config with no `[trends]` section loads, and `watch_state.py` then makes no trends read and prints no DRIFT row; `[trends]` without `series`, with an empty `series`, an unknown series or key, `bucket_days` below 1, `baseline` below 4, `log_sigma` at or below 0, or `report_sigma` below `log_sigma` fails the load naming the key
- S-078-9: over scripted runs, a bucket's `ci_pass_rate` is the default branch's `success` runs over its `success`, `failure`, and `timed_out` runs created in the bucket, cancelled and unfinished runs left out, and its `flaky_reruns` is the count of runs on any branch with an attempt number above 1 that concluded `success`
- S-078-10: a bucket's `review_time` is the median Review time of the agent pull requests merged in it and its `lead_time` the median Lead time for changes of the pull requests a stable release published in it first shipped, each equal to what `metrics.py` gives for that bucket as its window
- S-078-11: a series' tier is `ok`, `log`, or `report` by its newest bucket's distance from the baseline mean in the worse direction, in sample standard deviations, against `log_sigma` and `report_sigma`; a newest bucket better than the mean is `ok` however far it is
- S-078-12: a series whose newest bucket has no value, or with fewer than 4 baseline buckets that have one, reads `no data`; with a flat baseline, a worse newest bucket reads `report` with `flat baseline` and an equal or better one `ok`
- S-078-13: `trends.py` prints one line per configured series with its tier, newest value, mean, σ, and deviation, and `--json` one object per series with its buckets' values; a `log` or `report` line names up to 3 workflows with their counts and newest run URLs, or up to 3 pull requests with their numbers and hours
- S-078-14: a workflow whose file isn't on the default branch is printed as `(other workflow)`, and no title, body, or branch name appears in `trends.py`'s output or a DRIFT row
- S-078-15: `trends.py` exits 0 whether or not a series drifts, and 2 with a message naming the fix for a config without `[trends]`, a failed gh read, or a day with more than 1,000 runs, printing no partial report
- S-078-16: with `[trends]`, `watch_state.py`'s full report adds one `DRIFT <series>` row per series at the `report` tier, with the `trends.py` command as its fix, and none for a series at `log`, `ok`, or `no data`; the row leaves the watch's exit code as it was, and `--no-trends` makes no trends read
- S-078-17: `watch_state.py --tier N`, for every tier, and `--sweep` print no DRIFT row and make no trends read, so a gate tick never starts a session on a drift
- S-078-18: github-ship-watch's SKILL.md describes the four measures under Metrics and has a Trends section with the `[trends]` keys, the four series, the tiers, and the DRIFT row as reported and never acted on

## Out of scope

- **The watch opening a pull request on a drift** (#385's top tier, past 3σ). A revert of the change that turned the default branch red belongs to the opportunity for a red `main` (#1230), which gets its own spec. Quarantining a flaky test needs per-test results, which the forge doesn't hold: a later spec, once a repo's CI publishes them. Here the watch reports and changes nothing
- Flaky reruns per test: the series counts runs per workflow, from what the Actions API gives
- A model reading the drift, or a diagnosis beyond the counts above
- Production monitoring, health signals, and SLOs: the platform's (D-31, N-4)
- Agent cost (spec 023, postponed) and the evals of the agents' instructions (D-74)
- Refused agent pull requests (closed without a merge): the weekly retro already lists them
- A registry metric for Rework cycles, and a trend series as a goal's measure
- A measure for any goal of this repo, and a `[trends]` section in this repo's own config: the maintainer adds either if they want it (D-34)
- Starting a gate session on a DRIFT row, or a retro proposal for one

## Decisions relied on

- D-4
- D-16
- D-31
- D-34
- D-58
- D-62

## Issues

- shipmill/shipmill#1289: S-078-1, S-078-2, S-078-3, S-078-4, S-078-5, S-078-6
- shipmill/shipmill#1291: S-078-7
- shipmill/shipmill#1293: S-078-8, S-078-9, S-078-10, S-078-11, S-078-12, S-078-13, S-078-14, S-078-15
- shipmill/shipmill#1295: S-078-16, S-078-17, S-078-18

## Verification

Checked on the default branch plus #1295's pull request: `trends.py` run on this checkout and on one without a config, `watch_state.py` and the real `trends.py` run as subprocesses over a fake gh that scripts the runs per bucket, the skill's text read, and the tests `specs.py coverage --spec 078` lists, all passing.

- S-078-1: `test_s078_1_*` reads the JSON `measures` list with Rework cycles, First-pass merge rate, Review time, and Plan match right after Agent share, counted over Agent share's `agent_made` pull requests, each `no data` with a null value with no agent pull request merged, and Review time's `p90` and `count` in `hours`
- S-078-2: `test_s078_2_*` counts a Bot's, a `[bot]` login's, and a `--bot` login's review record and an OWNER's, MEMBER's, or COLLABORATOR's decision as verdicts, a COMMENTED review, an outsider's, and a person's marker review as none, and a record and an approval at one commit as one round
- S-078-3: `test_s078_3_*` counts a one-parent commit authored after the creation, and neither a merge of the base nor an older commit rebased after it
- S-078-4: over a scripted forge `test_s078_4_*` reads the mean rework cycles with the mean rounds and fix commits in the detail, and First-pass merge rate with `n of m`
- S-078-5: `test_s078_5_*` reads Review time to the first verdict and names the pull requests with none in the detail
- S-078-6: `test_s078_6_*` matches exact, `dir/`, and glob `Files:` paths and a renamed file's new path, and counts a pull request with no plan or no backticked path in the detail only
- S-078-7: `shipmill product check` takes each ratio metric at `80%` and each hours metric at `12h` and `1.5d`, and refuses `12h`, `2d`, or `5/week` for a ratio and `20%` or `5/week` for hours, naming the unit (`test_s078_7_*`); `METRIC_MEASURES` maps the four and shipmill-setup's SKILL.md lists them
- S-078-8: `trends.py` on this checkout, whose config has no `[trends]`, exits 2 naming the section to add; over the fake gh a config without `[trends]` makes the full report run no trends read and print no DRIFT row; each bad key fails `config.py`'s load naming it (`test_s078_8_*`)
- S-078-9: `test_s078_9_*` counts the default branch's success over success, failure, and timed-out runs with cancelled and unfinished ones out, and the rerun-green runs on any branch, a bucket over 1,000 runs read day by day
- S-078-10: `test_s078_10_*` gives each bucket the review and lead time `metrics.py` gives with that bucket as its window, from one read over the span
- S-078-11: `test_s078_11_*` reads `ok`, `log`, and `report` by the worse-way distance in sample σ against the configured bands, and a better bucket `ok` however far
- S-078-12: `test_s078_12_*` reads `no data` for a missing newest value or a baseline with 3 values, and on a flat baseline `report` with `flat baseline` when worse and `ok` when equal or better
- S-078-13: `test_s078_13_*` prints one line per series with tier, newest, mean, σ, and deviation, `--json` each series' buckets, and a diagnosis of up to 3 workflows or pull requests
- S-078-14: runs named and titled `SECRET-...` leave neither in `trends.py`'s output nor in the watch's DRIFT row; a workflow file not on the default branch prints as `(other workflow)`
- S-078-15: `trends.py` exits 0 with and without a drift, and 2 with a message naming the fix and no report for a config without `[trends]` (run on this checkout and on `docs/`), a failed gh read, and a day over 1,000 runs (`test_s078_15_*`)
- S-078-16: over the fake gh the full report, with and without `--no-host`, prints `DRIFT ci_pass_rate 50.0% against mean 95.0%, 7.8σ over 4 buckets of 1d: .github/workflows/ci.yml 5 failed, newest <run URL>` with the `trends.py` command as its fix and `agent` false, a steady series prints none, `--no-trends` makes no trends read and gives the same exit code, and a failing runs read exits 2; `fleet.py` lists the row among the report-only rows, with exit 0
- S-078-17: `--tier 1` to `--tier 7` and `--sweep` over the same config print no DRIFT row and make neither of `trends.py`'s reads; `--no-trends` with either exits 2
- S-078-18: github-ship-watch's SKILL.md names the four measures under Metrics and has a Trends section with the `[trends]` keys, the four series, the tiers, and the DRIFT row as reported, never acted on, read by `test_s078_18_*`
