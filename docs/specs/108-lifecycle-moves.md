# S-108: One command per lifecycle move a person makes: a project's head, focus, hold, and check issue, and an opportunity's accept and decline

status: approved
serves: G-6

## Problem

The lifecycle's entities (specs 096 to 106) are read by commands (`status --item`, `queue`,
`product show`), and spec 107 gives a session entity-then-verb commands for the moves that
answer an item: `shipmill decision answer` for a needs-decision option, `shipmill plan answer`
for a plan's accept, decline, hold, or send-back, `shipmill project continue|hold|stop` for a
head's answer, and `shipmill opportunity accept` for an accepted opportunity's goal. The other
moves are still hand-written labels, sub-issues, and closes (shipmill/shipmill#1789):

| Entity | Move with no command | Written today as |
| --- | --- | --- |
| Project head | make an issue a head | the `project` label |
| the same | focus it, or take its focus off | the `focus` label on or off |
| the same | put it back in line, or start it now | the `held` label on or off, after `project hold`'s comment |
| the same | file its check issue | a `Check: ` sub-issue with a `## Check` body, linked by hand |
| Opportunity | accept it, with the goal it serves | the `planned` label by hand, then `opportunity accept` |
| the same | decline it, with its reason | a comment, then a close as not planned |

Each is a place to get the form wrong, and two are wrong in a way no one sees: a session that
labels for the maintainer leaves no record of who decided, and a decline whose comment is a
relay reads the relay's header as the reason, since `intake_state.py`'s `decline_reason` takes
the first line of the comment.

## Behaviour

### The surface

Each move is `shipmill <entity> <verb> <n> [flags]`, run from the repo's checkout, on issue
`<n>` of the checkout's origin repo, as spec 107's commands are; `shipmill product` is the model
for the entity first. This spec adds the verbs spec 107 lacks and extends two of its own, so
each move has one command:

| Command | Move | Writes |
| --- | --- | --- |
| `shipmill project add <n> --by <login>` | make issue `<n>` a project head | the relay, then the `project` label |
| `shipmill project focus <n> --by <login>` | put the head in focus | the relay, then the `focus` label |
| `shipmill project unfocus <n> --by <login>` | take its focus off | the relay, then `focus` off |
| `shipmill project hold <n> --by <login>` (spec 107's, extended) | put the head back in line | spec 107's relay, then the `held` label |
| `shipmill project resume <n> --by <login>` | start a held head now | the relay, then `held` off |
| `shipmill project check <n> --title "<what will be true>" --check-file <path> [--cleanup-file <path>]` | file the head's check issue | the check issue, then its link as the head's sub-issue |
| `shipmill opportunity accept <n> G-<n>\|new --by <login>` (spec 107's, extended) | accept an opportunity not yet `planned` | spec 107's relay, then the `planned` label |
| `shipmill opportunity decline <n> --by <login> --reason "<why>"` | decline an opportunity | the relay, then the close as not planned |

The rest stay spec 107's as they are: `project continue` and `project stop`, every
`plan answer`, `decision answer`, and `opportunity accept` on an opportunity labelled `planned`
already. Transitions the gate makes from facts get no command: a head going active once its
check issue exists, a plan reading filed, a project reading closing or idle, a stopped
project's closes (PROJECT_STOP_DUE's session).

The code lives in `src/shipmill/moves.py`, its parsers beside spec 107's in
`src/shipmill/cli.py`, and it reuses spec 107's `src/shipmill/answer.py` for the relay's form,
the maintainer check, and the reads: every GitHub read and write goes through `shipmill gh`'s
path, so the leak check, the agent marker, and the label rules apply unchanged, and the command
exits 2 as `shipmill gh` does when the App's token can't be had or the config sets
`identity = "none"`.

### Who decided

Every move but `project check` is the maintainer's, so it takes `--by <login>`, required, a
login `shipmill roles` resolves for the `maintainer` role (D-68), and writes the relay before
the label or the close, in spec 107's form:

```markdown
Decision by `@<login>`, relayed by <agent>

<the move's line>

Note: <text>
```

The move's line is the verb as the table names it (`project`, `focus`, `unfocus`, `hold`,
`resume`), and for an opportunity spec 107's `accept G-<n>` or `accept new goal`, or
`decline: <why>`. `--relayed-by <agent>` (`Claude Code` by default), `--note <text>`, and
`--dry-run` work as in spec 107. `project check` is the session's own step of a start (spec 106's
PROJECT_START_DUE), so it takes no `--by` and writes no relay.

### Project moves

`project add` makes an open issue a head: it reads held until its check issue exists, as any
head does. `hold` puts a head back in line, so besides spec 107's comment it labels the head
`held`, which spec 107 left to the session that took the answer up: it reads held and starts again in its turn
(PROJECT_START_DUE), as spec 106 holds a head. `resume` starts a held head whose check issue
exists now, ahead of its turn, so it takes a slot under `[agents] projects`; a head with no
check issue needs `project check` first.

`project check` files an issue titled `Check: <title>` whose body is a `## Check` section with
the text of `--check-file`, and a `## Cleanup` section with the text of `--cleanup-file` when
given, through `shipmill gh issue create`, then links it as the head's sub-issue as
`shipmill link <head> --child <check>` does. Once linked, a head with no `held` label reads
active.

It refuses, exiting 2 and writing nothing, with a message naming the reason, a move its reader
would not count or that would read otherwise than meant:

- Any project move on a pull request, a closed issue, or an item with an open needs-decision
  question (answer it with `shipmill decision answer` first); `add` on an issue labelled `goal-plan`,
  on a check issue (a `Check: ` title), or on a head already
- `focus`, `unfocus`, `hold`, `resume`, and `check` on an issue that isn't a head as
  `intake_state.py --projects` reads one (`is_head`), or on a head reading PROJECT_STOP_DUE (a
  stop is pending; a newer relay would lift it)
- `focus` on a head already labelled `focus`, `unfocus` on one without it, `hold` on one
  already labelled `held` (spec 107's refusals of `hold` stand beside these), `resume` on one
  without it
- `resume` on a head with no check issue, or while the product's room under
  `[agents] projects` is 0, naming the slots (`2 of 2 active`), as `intake_state.py
  --projects --json` counts them
- `check` on a head that already has an open check issue, an empty `--title`, a title
  spanning lines, or a `--check-file` that is missing or empty

### Opportunity moves

`opportunity accept` on an open issue labelled `opportunity` and not yet `planned` is the
maintainer's accept itself: it writes spec 107's relay with the line `accept G-<n>` or
`accept new goal`, with spec 107's checks of the goal, then adds `planned`, where spec 107
refuses it. `intake_state.py` reads it ACCEPTED_INTO that goal, or GOAL_PROPOSAL_DUE for a new
goal (spec 106). On an opportunity labelled `planned` already it is spec 107's, unchanged.

`opportunity decline` posts the relay with the line `decline: <why>`, then closes the issue as
not planned. `intake_state.py`'s `decline_reason` reads a relay of the App's by its move's
line: the reason is the text after `decline:`, so the opportunity reads DECLINED with that
reason and its members are never proposed again. A decline the maintainer writes by hand reads
as today.

`credit.py`'s accepters (S-049-6) credit the maintainer a relayed accept names: when the newest
`planned` label on an opportunity was added by the App, its accepter is the login in the
App's newest relay on the issue whose move's line starts `accept`, written before the label.
An accept the maintainer labels by hand is credited as today.

It refuses, exiting 2 and writing nothing:

- Any opportunity move on an issue not labelled `opportunity`, a closed one, or one with an
  open needs-decision question
- `accept` with a goal spec 107 refuses (a measure, a met or dropped goal, an id the
  direction lacks) or with no goal
- `decline` on an opportunity labelled `planned` (an accepted one is stopped through its
  project, `project stop`), or without `--reason`, or with an empty or multi-line one

### Before and after every write

Like spec 107's commands, each one reads the item before any write and, before posting,
reads the composed relay back with the reader that will count it (`intake_state.py`'s relayed
answer for a head and an opportunity, `decline_reason` for a decline), refusing when it reads
otherwise. `--dry-run` prints what each step would write and writes nothing. When a later step
fails (the label after the relay, the link after the check issue), the command exits with
gh's code and says which step failed, with the URL of what it wrote.

On success each command prints the URL of what it wrote and then the item's state as
`shipmill status --item <n>` reads it after the move, one line, so a session sees the move
counted; spec 107's commands print the same line after their comment's URL.

## Acceptance criteria

- S-108-1: `shipmill project add <n> --by <maintainer>` on an open issue posts the relay ``Decision by `@<maintainer>`, relayed by Claude Code`` with the line `project`, then labels it `project`, both through `shipmill gh`, and `intake_state.py --projects` reads it PROJECT_HELD `no check issue`
- S-108-2: `project focus`, `unfocus`, `hold`, and `resume` each post their relay and move their label (`hold` with spec 107's comment), and `intake_state.py --projects` reads the head PROJECT_FOCUS, PROJECT_ACTIVE, PROJECT_HELD `labelled held`, and PROJECT_ACTIVE after them
- S-108-3: a project move on a pull request, a closed issue, or an item with an open needs-decision question, `add` on a `goal-plan` issue, a check issue, or a head, and `focus`, `unfocus`, `hold`, `resume`, or `check` on an issue that isn't a head or on a head reading PROJECT_STOP_DUE exit 2 and write nothing
- S-108-4: `focus` on a head labelled `focus`, `unfocus` on one without it, `hold` on one labelled `held`, `resume` on one without it, `resume` on a head with no check issue, and `resume` with `[agents] projects = 2` and two heads active exit 2, the last naming `2 of 2 active`, and write nothing
- S-108-5: `shipmill project check <head> --title T --check-file F` files an issue titled `Check: T` whose body has a `## Check` section with F's text (and a `## Cleanup` section with `--cleanup-file`'s), links it as the head's sub-issue, writes no relay, and `intake_state.py --projects` reads a head with no `held` label PROJECT_ACTIVE `no part filed`
- S-108-6: `project check` on a head with an open check issue, with an empty or multi-line `--title`, or with a missing or empty `--check-file` exits 2 and writes nothing
- S-108-7: `shipmill opportunity accept <n> G-<k> --by <maintainer>` on an opportunity not labelled `planned` posts the relay with the line `accept G-<k>`, then labels it `planned`, and `intake_state.py` reads it ACCEPTED_INTO `G-<k>`; `new` writes `accept new goal` and reads GOAL_PROPOSAL_DUE; on one labelled `planned` it writes the relay alone, as spec 107's
- S-108-8: `opportunity accept` on an issue not labelled `opportunity`, a closed one, or one with an open needs-decision question, with a goal that is a measure, met, dropped, or absent from the direction, or with no goal exits 2 and writes nothing
- S-108-9: `shipmill opportunity decline <n> --by <maintainer> --reason R` posts the relay with the line `decline: R`, then closes the issue as not planned, and `intake_state.py` reads it DECLINED with the note `R`; a decline on an opportunity labelled `planned`, without `--reason`, or with an empty or multi-line one exits 2 and writes nothing; a decline written by hand reads as before
- S-108-10: `credit.py` credits the maintainer a relayed accept names when the App added `planned`, and a hand-labelled accept as before
- S-108-11: every move but `project check` refuses a `--by` that `shipmill roles` doesn't resolve as the maintainer, and every command exits 2 writing nothing with `[agents] app_id` and no token, and with `identity = "none"`
- S-108-12: `--dry-run` on each command prints every step it would write and writes nothing; a failed second step (the label, the close, or the link) exits with gh's code naming that step and the URL of the first
- S-108-13: each command, and each of spec 107's, prints after the URL the item's state line as `shipmill status --item <n>` reads it after the move
- S-108-14: product intake's PROJECT_START_DUE step (`skills/product-intake/SKILL.md`), its labels table (`skills/product-intake/references/plan.md`), the needs-decision protocol's Answered in the session (`skills/github-issue-triage/references/needs-decision.md`), and `docs/flow.md` name these commands as the way a session makes each move

## Out of scope

- A plan's answers, a needs-decision answer, and a project's continue and stop: spec 107's
  commands
- Transitions the gate makes from facts, and a stopped project's closes and reverts
  (PROJECT_STOP_DUE's session, spec 106)
- Goals and measures: `shipmill product` already writes them
- Moves the maintainer makes on GitHub by hand: they keep their own form, read as today

## Decisions relied on

- D-16: only a trusted author's move, or the App's relay of one, counts
- D-61: the login in a code span, so the record emails nobody
- D-62: the agent marker on every body `shipmill gh` writes
- D-68: the App's relay of a maintainer's answer is that answer
- D-93: the relay grammar every reader shares
- D-115: an opportunity's accept and decline may be the App's on a relay of the maintainer's

## Issues

Filled in once the build issues are filed.

## Verification

Filled in when the spec reaches `built`.
