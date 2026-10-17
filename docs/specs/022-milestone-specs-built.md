# S-022: A milestone is done when its specs are built

status: draft

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
names an issue of this repository that is in the milestone, open or closed. Issues of
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
- `milestone 1.5.0: S-021's shipmill/shipmill#372 is not in v1.5.0rc3`
- `milestone 1.5.0: S-021's shipmill/shipmill#373 closed with no merged pull request`

When it is due, the reason names its specs: `milestone 1.5.0 built: S-021, S-023`.

### Unfinished goals between releases (waits on a decision)

Build issues of an unfinished spec merge to main one by one, and their changelog
fragments can carry `### Added`, so the next stable release can bump to the milestone's
minor version and ship half of its goal before the milestone is done. Which behaviour
shipmill takes here waits on the maintainer's decision on this spec's pull request, and
the spec is amended with its criteria before it is approved:

1. **Ship the increments.** Each stable release carries what is merged, a goal can span
   several minor versions, and the milestone marks the one that completes it. Nothing
   changes in the bump; the milestone is renamed when an earlier release takes its version
2. **Hold an unfinished goal's entries.** A fragment names its spec (`spec: S-NNN`); a
   stable release leaves out the fragments of a spec that isn't built, and the bump
   ignores them, so the minor version is the one that completes the goal. The code still
   ships in the meantime, undocumented, which a library can't hide
3. **Hold the stable lane.** While a spec in the next milestone has merged build issues
   and isn't built, the stable lane holds; fixes reach users through the hotfix lane

## Acceptance criteria

- S-022-1: With `milestone = true`, a lane whose milestone has open issues is not due by the milestone, as today
- S-022-2: A milestone with no open issues is not due while a spec whose Issues section names one of its issues says `status: draft` or `approved` at main's head, and the reason names the spec and its status
- S-022-3: A milestone with no open issues is not due while a build issue of one of its specs closed as completed with neither a merged pull request whose merge commit is in the candidate's base nor a trusted close-confirmed marker, and the reason names the spec and the issue
- S-022-4: For a stable lane that promotes an rc, a build issue whose merge commit is not an ancestor of the rc's base keeps the milestone from being due, and the reason names the rc
- S-022-5: A build issue closed as not planned holds nothing
- S-022-6: When every spec of the milestone is built and every build issue is in the candidate's base, the lane is due and the reason names the specs
- S-022-7: A milestone none of whose issues a spec names is due exactly when it is today
- S-022-8: `shipmill status` reports MILESTONE_WAITING with the milestone and its reasons while a lane with `milestone = true` has a milestone with no open issues that is not done, and no such row otherwise

## Out of scope

- Planning dates or capacity for a milestone: `[roadmap]` and product-intake already
  propose milestones
- Which issues go into a milestone: the maintainer's, or product-intake's proposal
- Holding fixes or pre-releases for a goal: they never wait on a milestone
- Specs in other repositories: a cross-repo goal is a chain (spec 017), not a milestone

## Decisions relied on

- D-25: a stable promotion stamps its rc's base, which the shipped check follows
- D-28: work that lands after an rc waits for the next rc
- D-29: a trusted close-confirmed marker stands in for a merged pull request

## Issues

## Verification
