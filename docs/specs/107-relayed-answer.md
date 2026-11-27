# S-107: One command writes the maintainer's relayed answer in the form its reader counts

status: built
serves: G-6

## Problem

A session that hears the maintainer's answer in chat records it on the item by hand
(shipmill/shipmill#1783): a needs-decision relay in the relay grammar (D-93), a plan's
accept, decline, send-back, or hold with its wake condition (specs 096, 098), a project's
continue, hold, or stop with its reason (spec 106), an `accept G-<n>` on an accepted
opportunity (spec 106). Then it removes the `needs-decision` label in a second command. Each
step is a place to get the format wrong, and the readers differ in small ways: the plan,
project, and opportunity readers (`intake_state.py`'s `relayed_answer`) read the line right
after the header as the answer and do not strip `Answered in the session:` or a `Basis:` line,
while `retro.py`'s `parse_relay` refuses any paragraph before `Note:`. A relay out of its
reader's form is not counted (`relay not counted: format`), so the item is asked again, as on
shipmill/shipmill#1598. The direction already has commands that write its grammar
(`shipmill product goal`, `met`, `drop`); answers on issues have none.

## Behaviour

### The commands

One command per entity, its verb after it, the first part of the command surface of
shipmill/shipmill#1789 (the maintainer chose these names on 2026-11-27, after this spec first
merged as one `shipmill answer` command, so #1789 adds its moves beside them and renames none):

- `shipmill decision answer <n> [<option>] [--own "<words>"]`: a needs-decision question
- `shipmill goal-plan answer <n> accept|decline|hold|send-back`: a goal's plan; `goal-plan`,
  the plan's label, since `shipmill plan` is the release command
- `shipmill project continue|hold|stop <n>`: a project head
- `shipmill opportunity accept <n> G-<n>|new`: an accepted opportunity's goal

Each, run from the repo's checkout with `--by <login>`, writes one
comment on issue or pull request `<n>` of the checkout's origin repo as `shipmill gh` writes
(the App with `[agents] app_id`, the host's login with `identity = "host"`), removes
`needs-decision` when the item carries it, and prints the comment's URL. Its code lives in
`src/shipmill/answer.py`, its parser in `src/shipmill/cli.py`, and every GitHub read and write
goes through `shipmill gh`'s path, as `shipmill spec open` does (spec 053), so the leak check,
the agent marker, and the label rules of #1312 apply unchanged.

- `--by <login>`, on each: who answered. Required; it must be a login `shipmill roles` resolves for the
  `maintainer` role, since no reader counts a relay naming anyone else (D-68)
- `--relayed-by <agent>`: the header's agent, `Claude Code` by default
- `--note <text>`: a `Note:` line after the answer, one line, which no reader reads (D-93)
- `--dry-run`: print the comment and the label step, read GitHub, write nothing

The comment is always:

```markdown
Decision by `@<login>`, relayed by <agent>

<the answer line>

Note: <text>
```

with the `Note:` line only when given. It never writes `Answered in the session:` or a
`Basis:` line: the answer line right after the header is read the same by `parse_relay`,
`pr_gate.py`, `triage_state.py`, and `intake_state.py`.

### What each answers

The command names the entity; the item's labels and comments, read before any write, must
show it, and give the answer line:

| Command | Item | Answer line written |
|---|---|---|
| `decision answer <n> <k>` | A needs-decision question (the newest comment whose first line is `<!-- shipmill:needs-decision -->`, by the App or an OWNER, MEMBER, or COLLABORATOR, with no newer answer) | `<k>. <the option's name as listed>` |
| `decision answer <n> --own "<words>"` | the same | `own: <words>` |
| `goal-plan answer <n> accept`, with `--only W-1,W-3` or `--except W-2` | A plan (label `goal-plan`) | `accept`, `accept W-1, W-3`, or `accept except W-2` |
| `goal-plan answer <n> decline --reason "<why>"` | the same | `decline: <why>` |
| `goal-plan answer <n> hold --until <YYYY-MM-DD, #N, owner/repo#N, or release>` | the same | `hold until <condition>` |
| `goal-plan answer <n> send-back --reason "<the change>"` | the same | `<the change>` (an edit) |
| `project continue <n>`, `project hold <n>` | A project head (label `project`) | `continue`, `hold` |
| `project stop <n> --reason "<why>"` | the same | `stop: <why>` |
| `opportunity accept <n> G-<n>` or `opportunity accept <n> new` | An accepted opportunity (labels `opportunity` and `planned`) | `accept G-<n>` or `accept new goal` |

- A plan, project, or opportunity answer on an item that also carries a needs-decision
  question answers both: the line is one `parse_relay` counts (no number, no paragraph), so the
  label comes off as for an option

### What it refuses

It exits 2, writing nothing, with a message naming the reason, for an answer its reader would
not count:

- An option number the question does not list, an option or `--own` on an item with no open
  question, an empty or multi-line `--own`, `--reason`, or `--note`
- On a plan: `--only` or `--except` naming an id the plan's Work section lacks, naming one
  twice, or dropping every item (`intake_state.py`'s `read_accept` gives the rule); a hold
  without `--until` or whose condition `read_hold` doesn't read as one condition; a decline or
  send-back without `--reason`; a send-back whose text starts with `accept`, `decline`,
  `hold until`, or `answer by`, which the reader would take for another answer; a closed plan
- On a project head: a `stop` without `--reason`, a closed head
- On an opportunity: one not labelled `planned` (the maintainer's label is the accept, which
  no agent adds), a goal the direction (`docs/product.md` of the checkout) doesn't list as
  a goal of kind goal still open (not met or dropped)
- An item that isn't the entity the command names (its label missing), a verb that entity
  doesn't take, a `--by` that isn't the maintainer, flags that don't go with the answer
  (`--until` on an accept, `--own` outside `decision answer`)
- Before posting, the composed comment is read back by the reader that will count it
  (`parse_relay` and `relay_refusal` for a question; `intake_state.py`'s answer readers for a
  plan, a project, and an opportunity) and refused when it reads otherwise, so a form drift
  between this command and a reader fails here, not on the item

Like `shipmill gh`, each exits 2 when the App's token can't be had, and with
`identity = "none"`; a failed write exits with gh's code after saying which step failed
(the comment posted and the label left on is reported with the comment's URL).

## Acceptance criteria

- S-107-1: `shipmill decision answer <n> 2 --by <maintainer>` on an item whose open question lists option 2 posts a comment whose first line is ``Decision by `@<maintainer>`, relayed by Claude Code``, whose answer line is `2. <option 2's name>`, through `shipmill gh issue comment --body-file`, then removes `needs-decision`, and prints the comment's URL
- S-107-2: a relay the command writes on a needs-decision question, an option or `--own`, with or without `--note`, reads as answered by `retro.py`'s `parse_relay` and `relay_refusal`, by `pr_gate.py`, and by `triage_state.py` (DECIDED, never `relay not counted: format`), and `shipmill gh`'s label rule lets `needs-decision` come off after it
- S-107-3: an option the question does not list, an option or `--own` with no open question, and an empty or multi-line `--own`, `--reason`, or `--note` exit 2 and write nothing
- S-107-4: `goal-plan answer` on a `goal-plan` issue, `accept`, `accept --only W-1,W-3`, `accept --except W-2`, `decline --reason`, `hold --until`, and `send-back --reason` write the lines in the table, and `intake_state.py --plans` reads them as PLAN_ACCEPTED with the kept items, PLAN_ANSWERED decline, PLAN_HELD `until <condition>`, and PLAN_ANSWERED edit; `shipmill status --item` on the held plan names it held with its wake condition
- S-107-5: on a plan, an id the Work section lacks, an id named twice, an accept dropping every item, a hold without `--until` or with a condition `read_hold` doesn't read, a decline or send-back without `--reason`, a send-back starting with another answer's word, and a closed plan exit 2 and write nothing
- S-107-6: on a `project` head, `project continue`, `project hold`, and `project stop --reason` write `continue`, `hold`, and `stop: <reason>`; `intake_state.py --projects` reads the stop as PROJECT_STOP_DUE `stop: <reason>`; a stop without `--reason` and a closed head exit 2
- S-107-7: on an `opportunity` labelled `planned`, `opportunity accept <n> G-<n>` and `opportunity accept <n> new` write `accept G-<n>` and `accept new goal`, which `intake_state.py` reads as ACCEPTED_INTO `G-<n>` and GOAL_PROPOSAL_DUE; an opportunity without `planned`, and a goal the direction lacks, a measure, a goal of no kind, or a met or dropped goal exit 2
- S-107-8: a `--by` that `shipmill roles` doesn't resolve as the maintainer, an item without the label of the entity the command names, a verb that entity doesn't take, and a flag that doesn't go with the answer exit 2 naming the reason and write nothing
- S-107-9: each command writes only through `shipmill gh`'s path: with `[agents] app_id` set and no token it exits 2 and writes nothing, and with `identity = "none"` it exits 2 with the owner's choice
- S-107-10: `--dry-run` prints the comment and whether the label comes off, and writes nothing
- S-107-11: the needs-decision protocol (`skills/github-issue-triage/references/needs-decision.md`, Answered in the session), product intake's plan and project steps (`skills/product-intake/references/plan.md`, `skills/product-intake/SKILL.md`), and `docs/flow.md` name `shipmill decision answer` or `shipmill goal-plan answer` as the way a session records an answer it heard

## Out of scope

- Answers the maintainer writes on GitHub themselves: they keep their own words, and readers
  read them as today
- Moving the item beyond the label: adding `held` to a project, filing a plan's items, or
  adding `planned` to an opportunity stays with the session that takes the answer up, or with
  the maintainer (`planned` is a person's label)
- A plan's `answer by YYYY-MM-DD` reply and a veto relay (`own: veto ...` covers the latter
  through `--own`); either can come later
- Asking: the needs-decision question keeps its own protocol

## Decisions relied on

- D-16: only a trusted author's reply, or the App's relay of one, is an answer
- D-61: the login in a code span, so the record emails nobody
- D-62: the agent marker on every body `shipmill gh` writes
- D-68: the App's relay of a maintainer's answer is that answer
- D-93: the relay grammar every reader shares
- D-14: as the App, any failure to get the token exits 2

## Issues

- shipmill/shipmill#1783: S-107-1, S-107-2, S-107-3, S-107-4, S-107-5, S-107-6, S-107-7, S-107-8, S-107-9, S-107-10, S-107-11

## Verification

Checked on the build branch for shipmill/shipmill#1783, on main at 2a48a0cc, by running
`tests/test_answer.py` (every test named for its criterion, all passed), `specs.py coverage
--spec 107` (exit 0), and each command's `--dry-run` against open items of this repository: a
plan (#990), a needs-decision question (#1674), and a project head (#1771).

- S-107-1: an option posts the header, `2. <name>`, removes the label, and prints the URL (`test_s107_1_an_option_posts_the_relay_takes_the_label_off_and_prints_the_url`); holds
- S-107-2: an option and `--own`, with and without a note, read as counted by `parse_relay`, `relay_refusal`, `pr_gate.py`'s `whole_reply`, `triage_state.py`'s `relayed` and `relay_refused`, and the label rule's `removing_refusal` (`test_s107_2_the_relay_is_counted_by_every_reader`); holds
- S-107-3: an unlisted option, no open question, and an empty or multi-line flag are refused with nothing written (`test_s107_3_an_answer_no_question_counts_is_refused`); holds
- S-107-4: each plan answer writes its line and `intake_state.py` reads it as the accept with its kept items, the decline, the hold, or the edit; a hold reads PLAN_HELD `until <condition>` by `held_row`, the row `status --item` names (`test_s107_4_a_plans_answers_read_as_intake_reads_them`, `test_s107_4_a_held_plan_reads_held_with_its_wake_condition_in_status_item`); holds
- S-107-5: each plan answer its reader wouldn't count is refused with nothing written (`test_s107_5_a_plan_answer_its_reader_wouldnt_count_is_refused`); holds
- S-107-6: a project's answers write their lines, `stop_reason` reads the stop, the idle question's label comes off, and a stop without a reason and a closed head are refused (`test_s107_6_a_projects_answers_and_its_stop`, `test_s107_6_a_project_answer_on_its_idle_question_takes_the_label_off`, `test_s107_6_a_stop_without_a_reason_and_a_closed_head_are_refused`); holds
- S-107-7: an accepted opportunity's goal is read by `accept_goal`, and one without `planned`, an id no open goal has, and no goal are refused (`test_s107_7_an_accepted_opportunitys_goal`, `test_s107_7_an_opportunity_its_reader_wouldnt_count_is_refused`); holds
- S-107-8: a non-maintainer `--by`, an item without the entity's label, a verb the entity doesn't take, and a stray flag are refused (`test_s107_8_a_wrong_maintainer_kind_or_flag_is_refused`); holds
- S-107-9: through the CLI, no App key exits 2 with no gh call, and `identity = "none"` exits 2 with the owner's choice and no write (`test_s107_9_without_the_apps_key_it_exits_2_and_writes_nothing`, `test_s107_9_with_identity_none_it_exits_2_with_the_owners_choice`); holds
- S-107-10: `--dry-run` prints the comment and the label step and writes nothing (`test_s107_10_dry_run_prints_the_comment_and_the_label_step_and_writes_nothing`); holds
- S-107-11: the four documents name `decision answer` or `goal-plan answer` (`test_s107_11_the_protocols_name_the_command`); holds
