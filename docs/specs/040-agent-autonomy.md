# S-040: Agent stages in [autonomy]: triage, fix, and land at observe, propose, or act

status: approved
serves: G-1

## Problem

`[autonomy]` sets observe, propose, or act for the stages that run in CI: release, deploy,
rollback, intake, and upgrade (`src/shipmill/autonomy.py`). The stages agents run (triage,
fix, land) have no level. How far a gate session goes is set by the words of `[agents]
prompt` ("do not merge", "merge when green") and by `[agents] prs`:

- **The words are not checked.** "merge if CI passes" or a typo in "merge when green"
  changes what a session does, and nothing tells the maintainer. `doctor` prints the
  release side's levels but can't print the agents', since they live in free text
- **Two models for one question.** "How far does shipmill go by itself?" has a checked
  enum for half the pipeline and a sentence for the other half. `prs = true` must agree
  with the sentence by hand (shipmill-setup's Scope step says so)
- **The site promises dials that don't exist.** `site/index.html` shows observe, propose,
  and act for Triage, Fix, Land, Release, and Deploy; a maintainer who looks for `triage =
  "propose"` in the config finds no such key
- **The stop switch reaches agents only through the gate.** `shipmill-hold` stops the
  gate's launches (D-15), but github-issue-triage and github-issue-resolve never read it,
  so a session started by `/loop`, a routine, or a person keeps writing
- **Setup doesn't ask.** shipmill-setup asks whether the gate may merge, and never asks
  about release, deploy, or rollback, which act by default; `shipmill init` leaves
  `[autonomy]` as a comment

Spec 030 answers who decides inside a stage (`[decisions]`, zones, act, notify, ask,
never). This spec answers the question one level up: does a stage run on its own at all.
The two layer: a stage's `[autonomy]` level bounds the session, and inside a stage that
acts, `[decisions]` decides each decision as it does today.

The maintainer asked for this in chat on 2026-10-26. The defaults, the profiles, and the
legacy reading below are proposals the maintainer settles when approving this spec; the
build pull request records the result as a new `D-n`.

## Behaviour

### The keys

`[autonomy]` in `.github/shipmill.toml` (D-4) gains three keys, parsed in
`src/shipmill/autonomy.py` into `AutonomyPolicy`, with the same three levels and the same
error shape as `release`:

```toml
[autonomy]
triage = "act"        # observe | propose | act: verdicts, comments, labels
fix = "act"           # observe | propose | act: a branch and a pull request per implement
land = "propose"      # observe | propose | act: review, fixes, and the merge
release = "act"
deploy.production = "propose"
rollback = "act"
```

What each level lets an agent session do:

| Stage | `observe` | `propose` | `act` |
|---|---|---|---|
| `triage` | reads and reports the verdicts in the session's output and the gate log; writes nothing to GitHub | posts each verdict as a comment headed `Proposed verdict`, with no label, close, or dispatch; the maintainer applies it by hand or by a trusted reply `apply` | posts the verdict, labels, closes, and dispatches as today |
| `fix` | writes no plan and no code | posts the implementation plan on the issue (design gate included), opens no branch | opens a branch and a pull request per implement, as today |
| `land` | reviews in the session only: no push, no comment | reviews, pushes small fixes with regression tests, posts the review, and labels a pull request that passes every check `shipmill-ready`; a person merges | merges on green CI, as today |

Each stage's level is a ceiling: inside a stage at `act`, every decision still follows its
zone in `[decisions]` (spec 030), so a `never` zone is not merged under `land = "act"`.
Under `propose`, `[decisions]` applies to what the session still writes (a `notify`
verdict under `triage = "propose"` is posted as proposed, never as decided).

Intake keeps `observe` or `propose` only (D-10), and upgrade keeps its key; neither
changes.

### Defaults

An absent key takes its default:

| Key | Default | Why |
|---|---|---|
| `triage` | `act` | a verdict is a comment and labels, all of it reversible |
| `fix` | `act` | a pull request is itself a proposal; `land` decides whether it merges |
| `land` | `propose` | shipmill-setup recommends "do not merge" for the first week today |

The release side keeps its defaults (`act`, D-7).

### The stop switch reaches every agent stage

`AutonomyPolicy.effective` already turns `act` into `propose` under an open `shipmill-hold`
issue; it now does so for `triage`, `fix`, and `land` too. Every skill that writes to
GitHub reads its stage's effective level before its first write (below), so a hold stops
a session however it was started. The gate keeps starting nothing under a hold (D-15).

### A person in the session

As for a release started by hand, a person acting is not the bot acting. In a session where
a person is present (not a gate session in `headless` mode, not a routine), a step above the
stage's level is taken when that person asks for it in their own words in this session,
and only for the items they name ("merge #42"). A gate, a `/loop`, or a routine never goes
above the level, whatever its prompt says. Under an open hold nobody's words raise a stage
(the hotfix exception stays release-only).

### The prompt keeps the task, not the scope

`[agents] prompt` says what the session works on. Its scope words can lower a stage
("triage the new issues; do not merge" under `land = "act"` lands nothing) but never raise
it: under `land = "propose"`, "merge when green" in the prompt merges nothing, and the
session says so once in the gate log as `SCOPE_CAPPED: land is propose`.

`[agents] prs` goes. Open pull requests count as work when `land` is `propose` or `act`,
and not under `observe`. Following D-32's path: for one minor release `prs` is accepted,
ignored, and `doctor` warns naming `[autonomy] land`; the next minor refuses it with exit
2.

### Reading the levels: `shipmill autonomy`

A new command in `src/shipmill/cli.py`:

`shipmill autonomy [--repo DIR] [--ref REF] [--json]` prints every stage (triage, fix,
land, release, each configured `deploy.<env>`, rollback, intake, upgrade) with its
configured level, its effective level under the hold, and its source: `default`, `config`,
`prompt` (the legacy reading below), or `hold`. It reads the config at `REF` when given,
default `origin/HEAD`, as `shipmill decide classify` does (S-030-9), so a pull request that
raises a level is judged by the level it would replace. JSON:

```json
{"hold": ["#88 deploy broke login"], "stages": [{"stage": "land", "configured": "propose", "effective": "propose", "source": "default"}]}
```

Exit codes: 0 printed; 2 a malformed config or a ref the checkout lacks.

The skills read it through `uvx shipmill==<version>`, as the hooks run the CLI (D-50):
github-issue-triage reads `triage` and `fix`, github-issue-resolve reads `fix`,
github-pr-triage reads `land`. The gate adds one line to every launch prompt, beside the
roles line (S-036-5): `Autonomy: triage act, fix act, land propose`, or with `(held by
shipmill-hold #88)` under a hold.

`shipmill decide levels` (spec 030) lists `triage`, `fix`, and `land` beside the
release-side zones with source `autonomy`, mapped as `release` is.

### Legacy reading for one minor release

A config that sets none of `triage`, `fix`, and `land` reads them from the prompt for one
minor release, so no repo changes behaviour on upgrade:

- "merge when green" or "land" in the prompt: `land = "act"`, source `prompt`
- otherwise every stage takes its default

`doctor` warns for each stage whose source is `prompt`, naming the line to add. A spec 014
upgrade, `agent-autonomy` in `src/shipmill/upgrades.py`, proposes the three keys with the
values the legacy reading gives, so the maintainer accepts the current behaviour in one
merge. The next minor drops the legacy reading: an absent key is its default.

### Setup asks the levels

`skills/shipmill-setup/SKILL.md` replaces its Scope step with an Autonomy step, asked once
with AskUserQuestion before the agent side is reported connected. It offers profiles, each
writing every stage key explicitly, so no level hides in a default:

| Profile | triage | fix | land | release | deploy (production) | rollback |
|---|---|---|---|---|---|---|
| Watch first | propose | observe | observe | propose | propose | propose |
| Recommended for the first weeks | act | act | propose | act | propose | act |
| Ship by itself | act | act | act | act | act | act |
| Custom | asked one stage at a time | | | | | |

Under the question the step shows what each level means for each stage (the table above,
one line per stage) and that one `shipmill-hold` issue turns every `act` into `propose`.
The answer goes to `.github/shipmill.toml` in the setup's pull request. The prompt it
writes holds the task only: `/shipmill:github-issue-triage {repo} triage the new issues`.

`skills/shipmill-setup/scripts/setup_state.py` gains `AUTONOMY_IMPLICIT`: a config with
`[agents]` that sets none of `triage`, `fix`, and `land`; its fix is the Autonomy step.
It replaces `LANDING_OFF`, which read `prs`.

`shipmill init` writes `[autonomy]` uncommented, with every key it knows the repo needs
(`release`, plus `rollback` and each `deploy.<env>` under `--operate`) at its default and
one comment line per key naming the three levels.

### `shipmill status` shows the levels

`src/shipmill/status.py` adds one `autonomy` line after the repo line, always shown:

```
autonomy   triage act · fix act · land propose · release act · deploy.production propose · rollback act
```

- Under a hold, each stage that the hold lowers reads `propose (held)`, and the existing
  hold line keeps its fix
- A stage whose source is `prompt` reads `act (from the prompt)`, with the fix `shipmill
  upgrade --apply agent-autonomy`
- `--json` gains `"autonomy"`, the `stages` list `shipmill autonomy --json` prints

The "to land" reason (S-009-26, S-011-13) reads `land` instead of `prs`: under `observe`
the open pull requests wait on you with the fix `set land = "propose" or "act" in
[autonomy], or land them by hand`; under `propose` the ones labelled `shipmill-ready` wait
on you to merge, each a link; under `act` they are the gate's work.

### `doctor`

`src/shipmill/doctor.py`'s autonomy check adds the three stages to its PASS line, warns
for each stage read from the prompt, warns for `prs` during its deprecation release, and
warns when `[agents]` is absent while `triage`, `fix`, or `land` is set, since nothing
reads them.

### Docs and the site

- `docs/release-lanes.md`, "Autonomy and the stop switch", lists the three stages with the
  table above; `docs/flow.md` says the prompt's words lower a stage and never raise it
- `README.md` names `shipmill autonomy` where it describes what the maintainer keeps
- `site/index.html`'s dials name the real keys: Triage, Fix, Land, Release, Deploy
- The ship-watch `TRIAGE_MODE` row reports the levels from `shipmill autonomy --json`,
  not the prompt's words

## Acceptance criteria

- S-040-1: `AutonomyPolicy.parse` of a config without `triage`, `fix`, or `land` gives `act`, `act`, and `propose`, and of a config setting each to each of the three levels gives that level
- S-040-2: `AutonomyPolicy.parse` exits 2 for `triage`, `fix`, or `land` set to a value outside the three levels, naming the key and the levels
- S-040-3: `AutonomyPolicy.effective` under an open `shipmill-hold` issue gives `propose` for `triage`, `fix`, and `land` configured `act`, and leaves `observe` and `propose` as they are
- S-040-4: `shipmill autonomy --json` lists every stage with `configured`, `effective`, and `source`, where a set key reads `config`, an absent one `default`, a stage the hold lowers `hold`, and lists the open hold issues under `hold`
- S-040-5: `shipmill autonomy --ref REF` reads the config at `REF`, defaulting to `origin/HEAD`, and exits 2 for a ref the checkout lacks
- S-040-6: For one minor release, a config that sets none of `triage`, `fix`, and `land` and whose `[agents] prompt` holds "merge when green" or "land" reads `land` as `act` with source `prompt`; one that sets any of the three keys reads no stage from the prompt
- S-040-7: `shipmill upgrade` lists `agent-autonomy` for a config without the three keys, and `--apply agent-autonomy` writes them with the values the legacy reading gives, leaving the rest of the file byte for byte
- S-040-8: A gate launch prompt carries an `Autonomy:` line with each agent stage's effective level, naming the hold issue when one is open
- S-040-9: The gate counts open pull requests as work when `land` is `propose` or `act` and not under `observe`, whatever `[agents] prs` says; `prs` in the config makes `doctor` warn naming `[autonomy] land`
- S-040-10: `shipmill status` prints an `autonomy` line with every stage's effective level, `(held)` beside each stage the hold lowers and `(from the prompt)` beside each stage read from the prompt, and `--json` carries the same stages
- S-040-11: `shipmill status` reports open pull requests as waiting on you under `land = "observe"` with the `[autonomy] land` fix, lists those labelled `shipmill-ready` as waiting to merge under `propose`, and as the gate's work under `act`
- S-040-12: `shipmill decide levels --json` lists `triage`, `fix`, and `land` with source `autonomy`, mapped as `release` is
- S-040-13: `setup_state.py` reports `AUTONOMY_IMPLICIT` for a config with `[agents]` that sets none of the three keys, and not once any is set
- S-040-14: `skills/shipmill-setup/SKILL.md` has an Autonomy step offering the four profiles with the levels of the table, the meaning of each level per stage, and the stop switch; `skills/github-issue-triage/SKILL.md`, `skills/github-issue-resolve/SKILL.md`, and `skills/github-pr-triage/SKILL.md` each read their stage's effective level with `shipmill autonomy --json` before their first write and follow the stage table
- S-040-15: The eval suite (spec 025) holds cases where a gate session under `land = "propose"` with "merge when green" in its prompt merges nothing and labels the green pull request `shipmill-ready`, and a triage session under an open hold posts its verdicts as proposed
- S-040-16: `shipmill init` writes an uncommented `[autonomy]` with `release`, and with `rollback` and each `deploy.<env>` under `--operate`, each at its default
- S-040-17: `doctor` warns when `triage`, `fix`, or `land` is set in a config without `[agents]`, and lists the three stages in its autonomy PASS line

## Out of scope

- Per-label or per-path stage levels (`land = "act"` for docs only): `[decisions]` zones
  already scope decisions, and a later spec can add it once a repo needs it
- Merging `[autonomy]` and `[decisions]` into one section: spec 030 keeps them apart
  because the release side runs without agents; this spec keeps that split
- A `watch` stage: github-ship-watch only finishes decisions already made, so it has
  nothing to raise or lower
- Enforcing `land` on the forge (branch protection, rulesets): the maintainer's settings
- Changing the hotfix exception to the hold or D-39's breaking-release hand start

## Decisions relied on

- D-4: the levels live in `.github/shipmill.toml`
- D-7: the release side keeps its `act` defaults
- D-10: intake stays `observe` or `propose`
- D-15: the gate starts nothing under a hold; this spec extends the hold to the skills
- D-21: a `propose` step that needs an answer uses the needs-decision protocol
- D-32: `[agents] prs` is deprecated for one minor release, then refused
- D-48: `[decisions]` keeps deciding inside a stage; `[autonomy]` stays the stage-level switch
- D-50: the skills run the CLI as `uvx shipmill==<version>`

## Issues

- shipmill/shipmill#659: S-040-1, S-040-2, S-040-3
- shipmill/shipmill#660: S-040-4, S-040-5, S-040-12, S-040-17
- shipmill/shipmill#661: S-040-6, S-040-7
- shipmill/shipmill#662: S-040-8, S-040-9
- shipmill/shipmill#663: S-040-10, S-040-11
- shipmill/shipmill#664: S-040-13, S-040-16
- shipmill/shipmill#665: S-040-14, S-040-15

## Verification

Filled in when the spec reaches `built`.
