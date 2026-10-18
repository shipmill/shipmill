# S-022: A milestone is done when its specs are built

status: built
serves: G-1

## Problem

A version can be planned around a goal: a milestone named after it, such as `1.5.0`, holds
the work that makes the goal, and `milestone = true` makes the lane due when that
milestone is done. Today "done" means the milestone has no open issues
(`src/shipmill/planner.py`), and that is too weak:

- **An empty milestone is not a finished goal.** Issues close for many reasons: a build
  issue closed by hand, a feature issue closed before its spec was verified, the last open
  issue moved to another milestone. In #317 a milestone emptied and the stable lane tried
  to promote a days-old rc twice; only failing CI stopped it
- **The goal is written down already, and nothing reads it.** A feature goes through the
  spec gate: its spec in `docs/specs/` lists numbered criteria, its build issues in the
  Issues section, and says `status: built` once every criterion is verified against the
  default branch. That is the definition of done the milestone should use

Patches and pre-releases are not planned: `dev` and `rc` lanes keep releasing each batch,
and a fix never waits for a goal. Only the lane that sets `milestone = true`, usually
stable, waits.

## Behaviour

### Which specs a milestone holds

A spec belongs to a milestone when its Issues section (`- owner/repo#N: S-NNN-1, …`)
names an issue of this repository that is in the milestone, open or closed, or when an
issue in the milestone links the spec's file in its body (see Build issues join their
feature's milestone, below). Issues of
other repositories in a spec's Issues section are ignored. Specs are read from
`docs/specs/` at main's head, so a spec marked built only on a branch doesn't count.

### When the milestone is done

A lane with `milestone = true` is due by its milestone when all of these hold:

1. The milestone named after the candidate's version exists, has no open issues, and has
   at least one closed issue (as today)
2. Every spec that belongs to it says `status: built`
3. Every build issue those specs name, in this repository, closed as completed by a merged
   pull request whose merge commit is an ancestor of the candidate's base, or carries a
   trusted close-confirmed marker (D-29); one closed as not planned needs neither

For a stable lane that promotes an rc, the candidate's base is the rc's base (D-25), so a
goal counts as shipped only when the rc being promoted holds all of its code. A goal built
after the rc was cut waits for the next rc, as a CI change does (D-28).

A milestone with no spec behaves exactly as today.

### What it says while it waits

`shipmill plan` and the Release run's summary name what holds the milestone, the first
reason found per spec, and `shipmill status` (`src/shipmill/status.py`) reports it as a new
row, MILESTONE_WAITING, whose subject is the milestone and whose detail is those reasons:

- `milestone 1.5.0: S-021 is approved, not built`
- `milestone 1.5.0: S-021's #N is not in v1.5.0rc3`
- `milestone 1.5.0: S-021's #N closed with no merged pull request`

When it is due, the reason names its specs: `milestone 1.5.0 built: S-021, S-023`.

### Unfinished goals between releases: ship the increments

Build issues of an unfinished spec merge to main one by one, and their changelog
fragments can carry `### Added`, so a stable release made by another trigger (quiet time, a
schedule, by hand) can take the milestone's version before its goal is done. The
maintainer decided on this spec's pull request to ship the increments: each stable
release carries what is merged, the bump doesn't change, a goal can span several minor
versions, and the milestone marks the one that completes it.

When a stable tag named like an open milestone exists, the milestone is **overtaken**:
`shipmill status` reports MILESTONE_OVERTAKEN with the milestone and the version the lane
would cut next, and its fix renames the milestone to that version
(`gh api -X PATCH repos/<owner>/<repo>/milestones/<n> -f title=<next>`). Under "watch",
github-ship-watch renames it and says so on the tracking issue the user names, since the
policy already decided the version; the goal and its issues stay as they were.

### Build issues join their feature's milestone

The milestone has to hold a goal's build issues for the rules above to see them, and today
nothing puts them there: the maintainer puts the feature issue in its milestone (D-32), but
github-issue-triage files
build issues when a spec merges, and its spec gate never sets a milestone. Three changes
close the hand-off:

- **Triage sets it when it files them.** `specs.py split NNN --milestone <title>` adds the
  milestone to each build issue it proposes (and to `--json`), and
  `skills/github-issue-triage/references/spec-gate.md` (Split it into build issues) passes
  the feature issue's milestone, when it has one, and files each with
  `gh issue create --milestone`
- **Triage reports one that missed it.** `triage_state.py` reads OFF_MILESTONE for an open
  build issue whose feature issue (its parent through a sub-issue, spec 017) is in a
  milestone it isn't in; the action sets the build issue's milestone to the feature's
- **A milestone also holds the spec its feature issue links.** A spec belongs to a
  milestone too when an issue in the milestone links the spec's file
  (`docs/specs/NNN-<slug>.md`) in its body, as the spec gate's feature issue does once its
  spec merges. A milestone that holds only the feature issue then still waits for the spec

## Acceptance criteria

- S-022-1: With `milestone = true`, a lane whose milestone has open issues is not due by the milestone, as today
- S-022-2: A milestone with no open issues is not due while a spec whose Issues section names one of its issues says `status: draft` or `approved` at main's head, and the reason names the spec and its status
- S-022-3: A milestone with no open issues is not due while a build issue of one of its specs closed as completed with neither a merged pull request whose merge commit is in the candidate's base nor a trusted close-confirmed marker, and the reason names the spec and the issue
- S-022-4: For a stable lane that promotes an rc, a build issue whose merge commit is not an ancestor of the rc's base keeps the milestone from being due, and the reason names the rc
- S-022-5: A build issue closed as not planned holds nothing
- S-022-6: When every spec of the milestone is built and every build issue is in the candidate's base, the lane is due and the reason names the specs
- S-022-7: A milestone none of whose issues a spec names is due exactly when it is today
- S-022-8: `shipmill status` reports MILESTONE_WAITING with the milestone and its reasons while a lane with `milestone = true` has a milestone with no open issues that is not done, and no such row otherwise
- S-022-9: A milestone none of whose issues a spec's Issues section names, holding an issue whose body links `docs/specs/NNN-<slug>.md`, is not due while that spec isn't built
- S-022-10: `shipmill status` reports MILESTONE_OVERTAKEN, naming the milestone and the version the lane would cut next, when a stable tag of the milestone's version exists and the milestone is open; the bump of a stable release is unchanged by any milestone
- S-022-11: `specs.py split NNN --milestone <title>` puts the milestone on every build issue it proposes, in its text and `--json` output, and without the flag proposes none
- S-022-12: `triage_state.py` reports OFF_MILESTONE for an open build issue whose parent feature issue is in a milestone it isn't in, and nothing for one already in it or whose parent has no milestone

## Out of scope

- Planning dates or capacity for a milestone: the maintainer's (D-32)
- Which issues go into a milestone: the maintainer's (D-32)
- Holding fixes or pre-releases for a goal: they never wait on a milestone
- Specs in other repositories: a cross-repo goal is a chain (spec 017), not a milestone
- Holding an unfinished goal's changelog entries or the stable lane: declined on this
  spec's pull request in favour of shipping the increments

## Decisions relied on

- D-25: a stable promotion stamps its rc's base, which the shipped check follows
- D-28: work that lands after an rc waits for the next rc
- D-29: a trusted close-confirmed marker stands in for a merged pull request

## Issues

- shipmill/shipmill#397: S-022-1, S-022-2, S-022-3, S-022-4, S-022-5, S-022-6, S-022-7, S-022-9
- shipmill/shipmill#398: S-022-8, S-022-10
- shipmill/shipmill#399: S-022-11
- shipmill/shipmill#400: S-022-12

## Verification

Checked on main at f8c08ec plus #398's PR: each criterion's code read against its text, and
the tests `specs.py coverage --spec 022` lists for it run there and passing.

- S-022-1: `Planner._due` asks for the goal only when the milestone has no open issues and one closed; test_s022_1 passes, reading no build issue
- S-022-2: `milestones.verdict` reads the specs at main's head and holds a draft or approved one, naming it and its status; the test_s022_2 tests pass, a spec built only on a branch counting as approved
- S-022-3: `_holdup` holds a completed close with neither a fix in the base nor a trusted close-confirmed marker (D-29); the test_s022_3 tests pass, an outsider's, a stale, a second-line, and another App's marker confirming nothing
- S-022-4: `milestone_verdict` looks for fixes in the rc's base and names the rc; test_s022_4 passes with `is not in v1.1.0rc1`
- S-022-5: a close as not planned returns no holdup; test_s022_5 passes
- S-022-6: with every spec built and every fix in the base the lane is due and the reason names the specs; test_s022_6 passes, another repository's issue ignored and the closes read in one batch
- S-022-7: a milestone no spec names, or a repository with no spec, plans as before; the test_s022_7 tests pass, reading nothing more without specs
- S-022-8: `Planner.milestone_findings` reads each milestone lane's milestone with `milestone_verdict`, and `status.read_milestones` turns a goal not done into a MILESTONE_WAITING row with its reasons, shown on the milestone line with no verdict; the test_s022_8 tests pass, with no row while the milestone has open issues, is done, or doesn't exist, and nothing read without a milestone lane
- S-022-9: `belonging` takes a spec whose file an issue in the milestone links; test_s022_9 passes
- S-022-10: `milestone_findings` reports an open milestone whose stable tag exists with the version the first milestone lane cuts next, its candidate's or `target`'s, and the row's fix renames it; the plan never reads open milestones. The test_s022_10 tests pass: 1.1.0 overtaken names 1.1.1 with a fix pending and 1.2.0 with an rc of it to promote, and with an overtaken and a closed higher milestone the rc is 1.1.1rc1 and stable promotes 1.1.1
- S-022-11: `specs.py split --milestone` puts the milestone in each proposal's text and `--json`, and none without it; test_s022_11 passes
- S-022-12: `triage_state.py` reads OFF_MILESTONE for an open build issue outside its parent's milestone and its usual state otherwise; the test_s022_12 tests pass
