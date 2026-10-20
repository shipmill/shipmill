# S-021: The requester ring

status: built
serves: G-3

## Problem

The person who asked for a change is the first user who needs it and the best judge of
whether it works, and shipmill treats them like everyone else.

What happens today, with an issue fixed and closed:

- **The first notice reads as final.** `shipped.py` comments "Released in <tag>." on the
  first release whose range holds the fix, which on a repo with an rc lane is a
  pre-release: an issue reads "Released in v1.0.0rc38." and nothing says it is a
  pre-release, that a plain install won't pick it up, or when a stable release will carry
  it. The install line is free text the session passes with `--install`, so most notices
  carry none
- **The stable release says nothing.** A stable promotion stamps an rc's base (D-25), and
  the previous tag is usually a later rc built on top of that base, so the range from it
  to the stable tag holds only the stamp commit: an issue told of `v1.0.0rc38` never hears
  of `v1.0.0`
- **A deploy says nothing.** On a repo with `[environments]`, a fix that reaches staging or
  production is never reported on its issue
- **The requester's answer goes nowhere.** Whether the person who filed the issue tried the
  pre-release and it worked, or it didn't, is not read, so a promotion can't name it and a
  regression they report waits for the next triage pass to be noticed as one

The decision behind this spec: shipmill decides and reports who has a change and where,
and the platform delivers it (D-31). Delivering a change to one person only, through a
feature flag or a per-customer build, stays the platform's.

## Behaviour

### Where a fix is available

For each closed issue a release fixed, shipmill posts one notice per **stage** the fix
reaches, in order, each at most once:

| Stage | When | Notice |
|---|---|---|
| `pre-release` | the first `dev` or `rc` tag holding the fix | `Released in <tag> (pre-release).`, the pin command, and the line "A plain install gets it with the next stable release" |
| `stable` | the first stable tag holding the fix | `Released in <tag>.` and the install command |
| `<environment>` | the first successful deployment of a tag holding the fix to that environment | `Deployed to <environment> in <tag>.` |

A tag **holds** a fix when the fix's commit is an ancestor of the tag's base (the commit
the stamp was made from), so a stable promotion holds every fix its rc held. A repo
without an rc or dev lane posts only `stable` and environment notices, which is today's
behaviour with the stage words added.

Every notice's first line is the marker `<!-- shipmill:available: <stage> <tag> -->`, and
the second line starts with the sentence above, so a notice is found by its marker and
an existing "Released in <tag>" comment still counts as told for that tag (no repo is
re-told after upgrading). Notices post through `shipmill gh` when `[agents] app_id` is
set, as `shipped.py` does today (spec 012).

### Install lines from the policy

A new section in `.github/shipmill.toml` (D-4):

```toml
[notices]
pin = "uv add 'treaty=={version}'"      # the pre-release notice's command
install = "uv add treaty"               # the stable notice's command
```

Both keys are optional and take `{version}`, `{tag}`, and `{name}`. Without them a notice
carries no command; `--install` on `shipped.py` keeps working and is used only when the
policy sets no `install`. Any other key under `[notices]` fails the policy with exit 2,
like every other section.

### The requester's answer

The pre-release notice ends with "If you filed this: react 👍 on this comment once it
works for you, or reply if it doesn't." The issue's author is the **requester**.

`watch_state.py` reads each pre-release notice's reactions and the comments after it:

- **REQUESTER_CONFIRMED**: the requester reacted 👍 to the notice. Reported only, with the
  issue, the tag, and when
- **REQUESTER_REPORT**: the requester commented after the notice, or reacted 👎. The row
  names the issue, the tag, and links the comment; under "watch" the session hands it to
  github-issue-triage as a possible regression. A report never opens a `release-blocker`
  or holds a lane by itself: the requester may be untrusted (D-16), and a hold is the
  triage verdict's to make
- A requester who answers nothing produces no row

Only the issue's author counts. Reactions and comments by anyone else are left to triage,
as today.

### The promotion names its confirmations

When a stable release promotes an rc, its plan reason (`shipmill plan`, the Release run's
summary) adds the count of issues that rc fixed and how many of their requesters
confirmed, such as `promotes v1.5.0rc3, soaked 1 day(s); 2 of 3 requesters confirmed`.
It is reported, never a gate.

### Where it lives

- `skills/github-pr-triage/scripts/shipped.py`: stages, the holding rule, markers, the
  `[notices]` commands
- `skills/github-ship-watch/scripts/watch_state.py`: UNANNOUNCED per stage,
  REQUESTER_CONFIRMED, REQUESTER_REPORT
- `skills/github-ship-watch/SKILL.md`: the rows and what a session does with each
- `src/shipmill/policy.py`: the `[notices]` section
- `src/shipmill/planner.py`: the confirmation count in a promotion's reason
- `docs/release-lanes.md`: the `[notices]` keys and the notices a requester gets

## Acceptance criteria

- S-021-1: `shipped.py` posts `Released in <tag> (pre-release).` with the `[notices] pin` command for a closed issue whose fix the first rc or dev tag holds, and the marker `<!-- shipmill:available: pre-release <tag> -->` is its first line
- S-021-2: For a stable tag that promotes an rc, `shipped.py` finds every closed issue whose fix the rc held and posts its `stable` notice, even when the range from the previous tag to the stable tag holds no fix commit
- S-021-3: A second run posts nothing; an issue with an existing `Released in <tag>` comment counts as told for that tag and stage
- S-021-4: After a successful deployment of a tag to an environment, the watch reports UNANNOUNCED for each closed issue whose fix the tag holds and that has no `<environment>` notice, and posting it writes `Deployed to <environment> in <tag>.`
- S-021-5: `[notices] pin` and `install` substitute `{version}`, `{tag}`, and `{name}`; an unknown key under `[notices]` fails the policy with exit 2; without `install`, `--install` text is used as today
- S-021-6: `watch_state.py` reports REQUESTER_CONFIRMED when the issue's author reacted 👍 to its pre-release notice, and nothing for a 👍 by anyone else
- S-021-7: `watch_state.py` reports REQUESTER_REPORT when the issue's author commented after its pre-release notice or reacted 👎 to it; no label, hold, or reopen follows from the row alone
- S-021-8: A stable promotion's plan reason names how many of the issues its rc fixed have a confirmed requester, and the count never changes whether the lane is due

## Out of scope

- Delivering a change to the requester alone (a feature flag for their account, a
  per-customer build or index): the platform's, per D-31; a later adapter may report a
  flag's state as one more stage
- Preview environments built from a pull request before it merges: the platform's; a
  later spec may post their URL to the issue
- Gating a promotion on requester confirmations: reported only here, since a requester who
  never answers would hold the lane forever
- Telling users other than the issue's author, such as those who reacted to the issue:
  they receive the notices as subscribers already
- Replacing time-based soak with signals (`min_soak_days`): a separate spec

## Decisions relied on

- D-3: prose calls the release automation shipmill
- D-4: the `[notices]` section lives in `.github/shipmill.toml`
- D-16: a requester's report starts no unattended work by itself
- D-25: a stable promotion stamps its rc's base, which the holding rule follows
- D-29: notices are found by a first-line marker
- D-31: shipmill reports where a change is available; delivering it is the platform's
- D-41: an environment's notices count from the release it ran before, and an environment
  can't be named after a notice stage

## Issues

- shipmill/shipmill#392: S-021-1, S-021-2, S-021-3, S-021-5
- shipmill/shipmill#393: S-021-4
- shipmill/shipmill#394: S-021-6, S-021-7
- shipmill/shipmill#395: S-021-8

## Verification

- S-021-1: ran `tests/test_shipped.py::test_s021_1_*` and read `notice` and `command_for` in `shipped.py`: a pre-release tag's notice opens with the `pre-release <tag>` marker line, then `Released in <tag> (pre-release).` and the rendered `pin`, passes
- S-021-2: ran `test_s021_2_*` and read `release_commits` and `own_range`: a stable tag reads its range from the newest stable tag below it (its whole history before the first), so a promotion whose previous rc range holds only the stamp still tells every fix its rc held, passes
- S-021-3: ran `test_s021_3_*` in `test_shipped.py` and `test_metrics.py` and read `told`: a second run prints SKIP notified for each issue, and a `Released in <tag>` comment counts at its tag's stage, passes
- S-021-4: ran `test_s021_4_*` in `test_shipped.py` and `test_ship_watch.py`: a successful deployment reports UNANNOUNCED for fixes counted from the tag the environment ran before (D-41), and posting writes `Deployed to <environment> in <tag>.` once per environment, passes
- S-021-5: ran `test_s021_5_*` in `test_config.py` and `test_shipped.py` and read `render`: `{version}`, `{tag}`, and `{name}` are substituted, an unknown `[notices]` key exits 2, and without `install` the `--install` text is used, passes
- S-021-6: ran `tests/test_ship_watch.py::test_s021_6_*` and read `requester_rows`: the author's 👍 on the newest pre-release notice reports REQUESTER_CONFIRMED and anyone else's gives no row, passes
- S-021-7: ran `test_s021_7_*` and read `requester_rows`: the author's comment after the notice or 👎 reports REQUESTER_REPORT, a report-only row that is no action and no agent's, passes
- S-021-8: ran `tests/test_requester_count.py`: a releasing promotion's reason names `1 of 3 requesters confirmed` from the fixes rc1's base holds past v1.0.0, a count of 1, of 0, and one GitHub fails to give produce the same decision, and the votes are never read when the stable lane isn't due, passes
