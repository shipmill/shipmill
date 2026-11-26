# S-101: Limit the outcomes that wait on the maintainer at once

status: built
serves: G-4

## Problem

Nothing bounds how many outcomes shipmill puts in front of the maintainer at once (#1510,
grouping #1456). `[agents] wip` (D-32) limits the issues agents have in progress, but
product intake has no limit of its own: it opens one opportunity issue per outcome whenever
it finds one, and each waits for an accept or a decline (OPPORTUNITY_OPEN in
`skills/product-intake/SKILL.md`). Every accept adds to the same queue, since an accepted
opportunity becomes a spec, build issues, and often a person's steps, so each new proposal
competes for the attention the accepted outcomes still need to finish.

It hits U-2, a founder running several repositories. Across the four owners the maintainer
runs shipmill for, the agents' Apps opened 603 issues from 2026-11-14 to 2026-11-20; on
2026-11-21, 25 opportunities, 42 `role:maintainer` items, and 8 `needs-decision` items were
open. G-4 shows that queue; nothing bounds it. Evidence: #1456, 1 request, +1 0 as of
2026-11-23.

## Behaviour

### The key: `[agents] outcomes`

`.github/shipmill.toml` gains `[agents] outcomes = N`, an integer from 1 up to the same
ceiling as `[agents] wip`: at most N outcomes in flight at once for the product. It sits
beside `wip` because both bound work in the delivery loop, one the issues agents work on,
the other the outcomes the maintainer carries (D-4, D-32). `src/shipmill/agents.py`'s
`AgentsConfig` reads it as `outcomes: int | None`, None without the key, and refuses 0, a
negative number, a number above the ceiling, and a non-integer with the config's usual
error naming the key. A product's limit is set once, in its home: a config with
`[product] home` (a component) that sets `[agents] outcomes` is refused, naming the home
whose config holds the product's limit (`src/shipmill/policy.py`). Without the key nothing
in this spec runs and every output below is as it is today.

### What is counted: every open opportunity

An outcome is in flight from the moment intake opens its opportunity issue until that issue
closes: every open issue labelled `opportunity` (the `--label`) counts, whether it waits for
the maintainer (OPPORTUNITY_OPEN), is accepted and waits for triage (ACCEPTED), or is
accepted and being built (HANDED_OFF). A closed one counts no more, whether done, declined,
or merged into another. Unanswered proposals and accepted outcomes not yet finished both
draw on the maintainer's attention, so the limit counts both. An opportunity labelled
`expedite` or `fixed-date` (spec 070) counts like any other. Goal plans (spec 028) and the
issues agents open for themselves count nothing.

The product is the repo alone when its config has no `[product]` table. In a product's home
(`[product] repos`), it is the home and every listed repo; in a component (`[product] home`),
the home and every repo the home lists. `skills/product-intake/scripts/intake_state.py`
reads the limit from the home's `.github/shipmill.toml` on its default branch (the local
config in the home or a lone repo) and counts the open opportunities of each repo of the
product, reading other repos through `shipmill gh --product <repo> api graphql`, one call
per owner, as `triage_state.py --home` does (S-065-8): the coordinator's token in the home
(D-83), the read token in a component (D-84). A read that fails exits 2 naming the
repo and the step, as a failed `product show` in a component does; it never counts the
repo as empty.

### `intake_state.py` reports the room

With a limit, the text output's second line is
`outcomes in flight: K of N (product <owner/home>)`, and `--json`'s first line gains an
`outcomes` key, `{"autonomy": ..., "outcomes": {"limit": N, "in_flight": K, "room": R}}`,
where R is N minus K, never below 0. Without a limit the first line stays
`{"autonomy": ...}` and the text output has no such line.

### Holding a new outcome

While the room is 0, a pass under `[autonomy] intake = "propose"` keeps grouping: it adds
requests to the Evidence of open, accepted, declined, and done opportunities as today, and
opens no new opportunity issue. Each request that would start a new outcome gets a comment
from intake whose first line is `<!-- shipmill:intake-held -->`, saying the outcome waits
for room under `[agents] outcomes`, how many are in flight, and that the maintainer can ask
for it by name. The template lives in `skills/product-intake/references/opportunity.md`;
its text never holds the word "implement" and starts with no `Triage:` marker, so the
request's triage verdict stays triage's hand-off. Under `observe` the pass writes nothing,
held comment included, and lists what it would hold.

`intake_state.py` reads a request as HELD when its newest held comment is newer than its
newest trusted triage comment, comes from the `--bot-login` or an OWNER, MEMBER, or
COLLABORATOR (D-16), carries the agent marker (D-62), and the room is 0. HELD is a
feedback row that needs no action: it doesn't set exit 1, its note is
`held since <date>`, and the rows print oldest held comment first.

### When room comes back: oldest held first

When an outcome in flight closes and the room is above 0, every HELD request reads
NEW_FEEDBACK again, its note `held since <date>`, and NEW_FEEDBACK rows print held ones
first, oldest held comment first, then the rest in today's order. The pass opens new
opportunities in that order, at most R of them; the requests left over read HELD again on
the next run without a new comment, since the room is 0 once more. Evidence (request count,
thumbs-up) and the goal served decide nothing here: D-32 removed ranking, and first held,
first proposed needs no judgment the maintainer didn't make. A held request triage handed
over keeps its `handed` time, so `skills/github-ship-watch/scripts/watch_state.py` makes it
a FEEDBACK_DUE row once it reads NEW_FEEDBACK again, and the gate starts the pass that
proposes it (spec 074).

### Asked for by name

The maintainer can have a held outcome proposed past the limit:

- in an interactive intake pass, by naming the request in the chat: the pass opens its
  opportunity whatever the room, and says so in its report
- on GitHub, by a reply on the held request whose first line is `propose` (any case, an
  optional final period), from an OWNER, MEMBER, or COLLABORATOR other than the
  `--bot-login` and with no agent marker (D-62), newer than the held comment:
  `intake_state.py` reads that request NEW_FEEDBACK with the note `asked by name`, whatever
  the room, and the pass opens its opportunity

An opportunity opened past the limit counts in flight like any other, so the room stays 0
until enough outcomes close. Accepting or declining stays the maintainer's (D-10).

### Consumers

`watch_state.py` accepts the `outcomes` key on intake's first JSON line (today it refuses a
first line with any key but `autonomy`), reads HELD lines as no row, and reads every other
line as today. `skills/product-intake/SKILL.md` gains the HELD state in its table, the hold
and the order in Workflow step 3, a hard rule that a pass at the limit opens no new
opportunity unless the maintainer asked for it by name, and a report line: the room
(`K of N in flight`) and each held outcome with its requests, oldest first.
`skills/shipmill-setup/SKILL.md` names `[agents] outcomes` beside `[agents] wip` among the
agent keys, and `docs/flow.md` gives a held request its state and what clears it.

## Acceptance criteria

- S-101-1: a config with `[agents] outcomes` set to 0, a negative number, a number above `[agents] wip`'s ceiling, or a non-integer is refused naming the key, and one setting it to 3 loads with `AgentsConfig.outcomes == 3`; without the key it is None
- S-101-2: a config with `[product] home` that sets `[agents] outcomes` is refused with a message naming the home
- S-101-3: with no `[agents] outcomes`, `intake_state.py`'s text and `--json` output and its exit code are the same as before this spec for the same GitHub data, held comments included
- S-101-4: with `[agents] outcomes = 3` and open opportunities reading OPPORTUNITY_OPEN, ACCEPTED, and HANDED_OFF, plus closed ones reading DONE, DECLINED, and MERGED, `intake_state.py --json`'s first line is `{"autonomy": ..., "outcomes": {"limit": 3, "in_flight": 3, "room": 0}}`, and an `expedite` opportunity counts as one
- S-101-5: in a product's home, `intake_state.py` counts the open opportunities of the home and of every repo its `[product] repos` lists, reading other repos through `shipmill gh --product`, one call per owner; in a component it reads the limit from the home's config on its default branch and counts the same set; a read that fails exits 2 naming the repo
- S-101-6: at room 0, a request whose newest held comment (first line `<!-- shipmill:intake-held -->`, agent marker, by the `--bot-login`) is newer than its newest trusted triage comment reads HELD with the note `held since <date>`, and a HELD row never makes the run exit 1
- S-101-7: a held comment by an author who is neither the `--bot-login` nor an OWNER, MEMBER, or COLLABORATOR, or without the agent marker, holds nothing: the request reads NEW_FEEDBACK
- S-101-8: once the room is above 0, every HELD request reads NEW_FEEDBACK with the note `held since <date>`, and the NEW_FEEDBACK rows print held requests first, oldest held comment first, then the others in the order they printed before this spec
- S-101-9: a trusted reply `propose` with no agent marker, newer than the held comment, makes the request read NEW_FEEDBACK with the note `asked by name` at room 0; the same reply by the `--bot-login`, carrying the agent marker, or from an untrusted author changes nothing
- S-101-10: `watch_state.py` accepts intake's first JSON line with the `outcomes` key, makes no FEEDBACK_DUE row for a HELD request, and makes one for a held request triage handed over at least 24 hours before once it reads NEW_FEEDBACK again
- S-101-11: `skills/product-intake/SKILL.md` lists HELD in its state table, says a pass at the limit opens no new opportunity unless the maintainer asked for it by name, and names the room and the held outcomes in its report; `references/opportunity.md` holds the held comment, whose first line is the held marker and which contains neither `Triage:` nor the word "implement"

## Out of scope

- A cap on every issue agents open: most close without a person (344 of 603 within a week in #1456), so a cap there would hold back work that waits on nobody; `[agents] wip` stays the bound on issues in progress
- Goal plans: a plan waits on `[agents] wip` already (PLAN_WAITS, spec 028), and its feature items are filed issues, not opportunities, so neither counts nor waits on this limit
- `role:maintainer` items and `needs-decision` questions: they count toward the queue G-4 shows (spec 069) but not toward this limit; bounding them is another outcome
- A per-repo limit inside a product: the limit is the product's, set in the home
- Ranking held outcomes by evidence or by goal: D-32 removed ranking; the maintainer reorders by asking for one by name
- `shipmill status` and the maintainer's queue (spec 069): a held request waits on room, not on the maintainer, so it is no row there

## Decisions relied on

- D-4
- D-10
- D-16
- D-32
- D-34
- D-62
- D-83
- D-84

## Issues

- shipmill/shipmill#1727: S-101-1, S-101-2
- shipmill/shipmill#1728: S-101-3, S-101-4, S-101-5, S-101-10
- shipmill/shipmill#1733: S-101-6, S-101-7, S-101-8, S-101-9, S-101-11

Built in #1744 (#1727), #1745 (#1728) and the pull request for #1733.

## Verification

Checked on main at 710ab70a with #1733's change on top, by reading the code and running the
tests named below (`tests/test_config.py`, `tests/test_product_config.py`,
`tests/test_intake_outcomes.py`, `tests/test_intake_held.py`,
`tests/test_watch_feedback_outcomes.py`, `tests/test_product_intake_skill_held.py`);
`specs.py coverage --spec 101` exits 0.

- S-101-1: `AgentsConfig.outcomes` reads 1 to wip's ceiling, None without the key, and refuses 0, a negative number, a number above the ceiling, and a non-integer naming the key (`test_s101_1_the_outcomes_limit_reads_1_to_wips_ceiling_and_is_none_when_omitted`, `test_s101_1_a_bad_outcomes_limit_is_refused_naming_the_key`); holds
- S-101-2: a component that sets `[agents] outcomes` is refused naming its home, and a home and a lone repo keep the key (`test_s101_2_a_component_that_sets_the_outcomes_limit_is_refused_naming_the_home`, `test_s101_2_the_home_and_a_lone_repo_keep_their_outcomes_limit`); holds
- S-101-3: without the key `intake_state.py`'s text, `--json`, and exit code are as before, held comments included, and `rows` reads no held comment without a room (`test_s101_3_without_the_key_both_outputs_and_the_exit_are_as_before`, `test_s101_3_a_component_whose_home_sets_no_limit_prints_as_before`, `test_s101_3_a_component_whose_homes_config_cant_be_read_prints_as_before`); holds
- S-101-4: every open opportunity counts once, an `expedite` one included, and the room is the limit less the count, never below 0 (`test_s101_4_every_open_opportunity_counts_once`, `test_s101_4_the_room_is_what_the_limit_leaves`, `test_s101_4_a_bad_limit_is_refused_naming_the_key`); holds
- S-101-5: the home counts its listed repos through `shipmill gh --product`, one call per owner, a component reads its home's limit and counts the same set, and a failed read exits 2 naming the repo (`test_s101_5_the_home_counts_its_listed_repos_one_call_per_owner`, `test_s101_5_a_component_reads_the_homes_limit_and_counts_the_same_set`, `test_s101_5_a_read_that_fails_exits_2_naming_the_repo`, `test_s101_5_a_component_never_sets_the_limit_itself`); holds
- S-101-6: `held_comment` reads the newest comment whose first line is the held marker, with the agent marker, by the `--bot-login` or a trusted author, newer than the newest trusted triage comment, and `feedback_state` reads it HELD `held since <date>` at room 0; HELD is not in `ACTION`, so a run with only it exits 0 (`test_s101_6_a_held_request_reads_held_at_room_0`, `test_s101_6_the_held_comment_must_be_newer_than_the_newest_trusted_triage_comment`, `test_s101_6_the_newest_held_comment_dates_the_hold`, `test_s101_6_a_held_row_never_makes_the_run_exit_1`); holds
- S-101-7: a held comment by an untrusted author or another bot, without the agent marker, or with the marker not first, holds nothing (`test_s101_7_an_untrusted_or_unmarked_held_comment_holds_nothing`; `test_s101_7_a_trusted_persons_session_holds_too` shows the Behaviour's OWNER, MEMBER, or COLLABORATOR with the agent marker holding); holds
- S-101-8: above room 0 a held request reads NEW_FEEDBACK `held since <date>`, and `row_order` prints held requests first, oldest held comment first, then the rest newest number first as before; a hand-off keeps its `handed` (`test_s101_8_room_back_reads_held_requests_new_feedback_oldest_held_first`, `test_s101_8_a_held_request_keeps_its_hand_off_time`); holds
- S-101-9: `asked_by_name` reads a reply newer than the held comment whose first line is `propose` (any case, an optional period) from an OWNER, MEMBER, or COLLABORATOR other than the `--bot-login` with no agent marker, and the request reads NEW_FEEDBACK `asked by name` at room 0; the `--bot-login`'s, an agent's, an untrusted author's, an older reply, and an unreadable author change nothing (`test_s101_9_a_trusted_propose_reply_asks_for_it_by_name`, `test_s101_9_any_other_reply_changes_nothing`, `test_s101_9_a_reply_whose_author_cant_be_read_is_an_agents`); holds
- S-101-10: `watch_state.py` accepts the `outcomes` key on intake's first line, makes no FEEDBACK_DUE row for a HELD request, and makes one once a handed-over request reads NEW_FEEDBACK again (`test_s101_10_the_autonomy_line_may_carry_the_outcomes`, `test_s101_10_a_held_request_makes_no_feedback_due_until_it_reads_new_feedback_again`); holds
- S-101-11: product-intake's SKILL.md lists HELD, rule 10 opens no new opportunity at the limit unless asked for by name, Workflow step 3 holds and orders, the report names the room and the held outcomes, and opportunity.md's held comment starts with the held marker and holds neither `Triage:` nor "implement" (`test_s101_11_the_skill_lists_held_in_its_state_table`, `test_s101_11_a_pass_at_the_limit_opens_no_new_opportunity_unless_asked_by_name`, `test_s101_11_the_report_names_the_room_and_the_held_outcomes`, `test_s101_11_opportunity_md_holds_the_held_comment`); holds

A discussion is never held: `intake_state.py` reads no discussion's comments, so at room 0 a
pass opens nothing for a discussion that would start a new outcome and lists it as waiting.
