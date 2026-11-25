# S-041: Chain integrity: cycles and strict Depends on lines

status: built
serves: G-1

## Problem

Spec 017 made chains of work something shipmill follows: a `Depends on` line, a native
`blockedBy` relation, or a sub-issue holds an issue until what it waits on closes. Two
gaps let a chain stall with nothing reporting it, which breaks G-1: the gate waits forever
on work that can never move, and the maintainer never hears there is a decision to make.

- **A cycle reads as waiting (#679).** `chains.py show` walks a cycle until it closes and
  prints every item on it as BLOCKED; `triage_state.py` reads each one as BLOCKED, which
  is no action. A parent with five children, each child's `Depends on` line also naming
  the parent for a decision recorded there, printed eleven BLOCKED rows and no hint. The
  cycle forms the natural way: a sub-issue holds its parent (`(child)`), and the child
  names its parent for context. `chains.py link` checks only a link to itself, so it
  writes the link that closes a cycle too
- **A Depends on line holds on every reference in it (#680).** `DEPENDS` in
  `skills/github-issue-triage/scripts/triage_state.py` takes the whole rest of a line
  starting "Depends on", and `DEPENDENCY` reads every reference on it as a hold, prose
  included. Checked on main at de1d180 with `dependency_refs` (repo `acme/home`):

  | Line | Holds on |
  |---|---|
  | `Depends on: D1 for the type names (decisions D1–D5: acme/home#32)` | `acme/home#32`, only where the decisions live |
  | `Depends on: acme/api#129 deployed; D1 (decisions D1–D5: acme/home#32)` | `acme/api#129` and `acme/home#32` |
  | `Depends on: the classifier deployed and decision D4 on #32` | `acme/home#32`, never the classifier issue the author meant |
  | the same line inside a fenced code block | still holds: fences aren't skipped |

  That is how #679's cycle formed. Agents wrote all three lines, following the documented
  shape loosely

## Behaviour

### A strict Depends on line

`triage_state.py`'s reading of a body (`dependency_refs`, `unfilled_dependencies`, and the
`DEPENDS` and `DEPENDENCY` patterns), which `chains.py` and `upstream_state.py` import,
changes in one place, so every reader holds on the same references.

A **Depends on line** is a body line outside a fenced code block (``` or ~~~, as
`FENCE` reads one) that starts, after indentation and an optional `- ` or `* ` bullet,
with `Depends on` in any case and an optional `:`. Its shape is:

```
Depends on[:] <ref> [<sep> <ref>]... [<note>]
```

- `<ref>` is `owner/repo#N`, a URL `https://github.com/owner/repo/issues/N` or
  `.../pull/N`, a plain `#N` (the issue's own repo), or a placeholder `#{key}` or
  `owner/repo#{key}` from `specs.py split`
- `<sep>` is any mix of `,`, the word `and`, and whitespace: `#1, #2 and acme/api#3`,
  `#1 #2`, and `#1, and #2` all hold on three or two references
- `<note>` starts at ` (`, `;`, or ` — ` right after the last reference and runs to the end
  of the line. It is never read for references: `Depends on acme/api#129 (deployed)` holds
  on `acme/api#129` alone, and `Depends on #5 (decided in #9)` on `#5` alone

A line that matches holds on its references, as today's lines do. A Depends on line that
names at least one reference (or placeholder) anywhere and doesn't match the shape is
**malformed**. It still holds on every reference it names, as today, so nothing it was
holding starts early, and the issue reads MALFORMED_DEPENDS (below) until the line is
fixed. A line starting "Depends on" that names no reference is prose: it holds nothing and
is not malformed, as today.

`chains.py link` already writes `Depends on owner/repo#M`, the strict shape. Its check for
a line already there (`names` in `skills/github-issue-triage/scripts/chains.py`) reads the
same references `dependency_refs` holds on, so a reference only in a note isn't counted
and link appends a line for it.

### MALFORMED_DEPENDS in triage

`triage_state.py` gains MALFORMED_DEPENDS, an action (exit 1): an open issue whose holds
it reads (triaged, or a person's item) with a malformed Depends on line. It is read right
after UNFILLED and before CYCLE, SPEC_REFUSED, BLOCKED, UNBLOCKED, and a person's item's
HANDOFF_DUE, so neither an implementer nor a hand-off starts on an issue whose
dependencies are unclear. Its note names each malformed line as `line <n>: <the line>`
(`n` counted from 1 in the body), then the holds as BLOCKED's note shows them. An
untriaged issue still reads NEW.

The session that takes it up (github-issue-triage's `references/triage-rubric.md`)
rewrites the line in the issue body as the App (D-14): one strict `Depends on` line naming
the references it reads as the author's dependencies, and the rest of the old line on a
line of its own after it. Which references are holds is an `interpretation` decision
(spec 030, D-48): at its default `notify`, the session posts the decided marker naming the
old and the new line, and a veto puts the old line back.

### A cycle

A **cycle** is a loop of open issues each holding the next through an open hold of any
kind (a Depends on line, malformed ones included, a native `blockedBy`, or a sub-issue).
A closed item holds nothing, so a loop through one is no cycle; an UNTRUSTED item's and an
UNREADABLE item's holds are never read, so no cycle runs through one. A loop is printed as
`a -> b -> a`, each item as `owner/repo#N`: for an item on several loops, the shortest
through it, rotated to start at the least reference (owner, repo, number, case ignored),
ties broken by the least sequence.

**`chains.py show`** marks each item on a cycle `CYCLE (acme/a#1 -> acme/b#2 ->
acme/a#1)` in place of `BLOCKED (...)`, with its loop as above; an item that waits on a
cycle without being on it stays BLOCKED. `--json` gives such a row `"state": "CYCLE"` and
`"cycle"`, the loop as a list of references with the first repeated at the end, and every
other row `"cycle": null`. A row whose issue has a malformed Depends on line ends with
`MALFORMED_DEPENDS line <n>: <the line>` (several joined by ` | `), in its last column
beside NO_GATE, and `--json` gives each row `"malformed"`, the list of those lines
(`[]` without one). Show exits 1 when any row is NO_GATE, CYCLE, or MALFORMED_DEPENDS,
else 0; exit 2 is unchanged.

**`chains.py link`** refuses a link that would close a cycle: before any write, it walks
what `<other>` waits on (its open holds, recursively, as show reads them) and, when that
reaches `<target>`, exits 2 with `error: linking <target> to <other> closes a cycle:
<target> -> <other> -> ... -> <target>`. This holds for `--blocked-by` and `--child` (a
parent waits on its child) and with `--product`. A link whose two halves are already in
place on a cycle is refused the same way, so link never exits 0 on a cycle.

**`triage_state.py`** gains CYCLE, an action (exit 1): an open issue on a cycle of the
repo's own open issues whose holds it reads, built from the holds it already reads (no
extra query; with `--trusted-only`, never through an UNTRUSTED issue). Its note is `cycle
<loop>`, then the holds as BLOCKED's note shows them. It is read right after
MALFORMED_DEPENDS and before SPEC_REFUSED and BLOCKED; an issue that reads UNTRUSTED,
UPSTREAM, NEEDS_DECISION, DECIDED, VETOED, OFF_MILESTONE, NO_ASSIGNEE, ASSIGN_DUE, UNFILLED,
or MALFORMED_DEPENDS reads that instead. When another issue on its loop reads
MALFORMED_DEPENDS or is labelled needs-decision, it reads BLOCKED with `cycle <loop> waits
on owner/repo#N` in its note, naming that issue: one question, or one line fix, breaks
the loop, and the other items don't each start a session. A cycle through another repo's
issues is not seen here; ship-watch reports it (below).

The session that takes up CYCLE asks the maintainer through the needs-decision protocol
(D-21) on the loop's first item: which link is wrong, one option per link of the loop (its
form: a Depends on line, a native relation, or a sub-issue), the session's recommendation
first with its reason. Once answered (DECIDED), it removes both forms of the chosen link,
the body line and the native relation (GraphQL `removeBlockedBy` or `removeSubIssue`), as
the App, and removes the label. The question goes in `references/comments.md`.

### ship-watch

`skills/github-ship-watch/scripts/watch_state.py`'s `TRIAGE_ACTION` gains CYCLE and
MALFORMED_DEPENDS, so the gate starts a session for them. Its chain rows gain
CHAIN_CYCLE, read from the same `chains.py show --json --trusted-only` run as
CHAIN_NO_GATE: one row per distinct cycle with an item outside the watched repo, its
subject the loop's first item, its detail the loop, its fix `answer which link is wrong
and remove it: uv run --no-project python <chains.py> show <first item>`; an action for a
person, never an agent's, like CHAIN_NO_GATE. A cycle wholly inside the watched repo gets
no CHAIN_CYCLE row: its triage reads CYCLE and a session asks. A malformed reference in
`"cycle"` reads as CHAIN_UNREADABLE, as a malformed `ref` does. `fleet.py` and
`src/shipmill/status.py` count CHAIN_CYCLE with the chain rows (`CHAIN_ROWS`) and
CYCLE and MALFORMED_DEPENDS with the triage actions.

### One command for every link (#1645)

Amended by shipmill/shipmill#1645. A hold written only as prose went unseen: a session
found that its open pull request waited on an upstream report, wrote "On hold: waits on
<repo>#116" in a comment, and the gate handed the pull request to land fourteen minutes
later, since no `Depends on` is defined for a pull request and nothing reads a pull
request's comment as a hold. `chains.py link` was a skill's script, which a session outside
triage didn't reach for. So a hold is recorded only as a link, by one command, and every
reader reads the same links.

**`shipmill link <ref> --blocked-by <ref>`**, `shipmill link <ref> --child <ref>`, and
**`shipmill unlink`** with the same flags, where `<ref>` is `#N` (the checkout's origin repo)
or `owner/repo#N`. A malformed reference, or `#N` in a checkout with no GitHub origin, exits
2 naming it before anything runs. The command runs github-issue-triage's `chains.py link`
(or `unlink`) from the checkout with both references made whole, passing `--product` and
`--no-text` on, and passes its output and exit code on: chains.py stays the one
implementation of a link's two forms, its cycle refusal, the product's routing (spec 038),
and whom its writes post as (D-14), so a link written either way is the same link.

**A pull request that waits.** GitHub's native blocked-by relation is for issues only, so a
pull request's link is a strict `Depends on` line in its body, the line spec 041 defines for
an issue. `link <pull request> --blocked-by <ref>` writes that line, appended as an issue's
is, through the same REST edit of `repos/<owner>/<repo>/issues/<n>` (which edits a pull
request's body too), and no relation; a line already holding on the ref prints `already
linked` and writes nothing. `--no-text` on a pull request exits 2: its line is its only
form. A pull request is still refused, naming it, as the item a link waits on and on either
side of `--child` (S-017-9).

**`unlink`** removes both forms: the native relation when the forge records it (GraphQL
`removeBlockedBy`, or `removeSubIssue` for `--child`; a refusal prints `text only: <error>`
and the line still goes), and the ref from every strict Depends on line of the body that
holds on it. A line naming it alone is dropped with its line break; one naming others keeps
them, in their own spelling, with its note; the rest of the body is kept byte for byte. A
malformed line naming the ref exits 2 before any write, since which of its references hold
is a decision. When it removed anything it then posts one comment on the item, with the
agent marker and no hold phrase, `Unlinked from <ref>: it no longer holds this item`, so an
older hold comment is no longer the agent's newest word (HOLD_UNLINKED, below). With neither
form there it prints `not linked` and writes nothing. A CYCLE's answer is taken up with
`shipmill unlink`.

**One read.** A pull request's Depends on lines hold it as an issue's do:

- `chains.py show` reads an open pull request's lines as its holds (with `--trusted-only`
  only from an author the origins trust, D-16): its row's `holds` lists the open ones,
  `waits_on` every one, `waiting_for` is `items` while one is open, and the walk follows
  them. Its state stays OPEN, and no cycle runs through a pull request
- `watch_state.py` reads each open pull request's body (`body` joins `PR_FIELDS`, and the
  gate's change check reads it into `--known`). A non-draft pull request whose lines name
  an item still open, or one whose state can't be read, is in PRS_PARKED as `WAITS_ON #N
  (owner/repo#M ...)`, after its WITH_PERSON and TO_MERGE parts, and never in PRS_OPEN or
  the land window's queue: the gate doesn't hand it to land. The items' states are read
  once for every pull request, only when one names an item. An agent's draft so held reads
  AGENT_DRAFT_HELD naming the item, as a hold comment does. Once every item it names
  closes, it is read as before
- `shipmill status --item` gives such a pull request the condition `waits on
  owner/repo#M (open)`, cleared by that item closing or merging, held elsewhere for another
  repo's item; `shipmill queue` counts it with an open item of the repo as a BLOCKED issue
  counts with what it waits on (spec 094), and lists the items in its `waits_on`; the item
  it waits on names it in its `blocks`, in `queue` and in `--item` alike

**HOLD_UNLINKED.** `triage_state.py` reads HOLD_UNLINKED, an action (exit 1), for an open
issue whose holds it reads (triaged, or a person's item) when the agent's newest word on it
(its newest comment with the agent marker, or by the `--bot-login`, that is neither a status
comment nor a needs-decision question) names a hold (the `hold_refs` rule) on an issue still
open that neither a Depends on line of its body nor a native relation records. Only a hold
GitHub's answer for its state gives as an issue counts: an issue can't be linked to a pull
request (S-017-9), so a hold on one, such as the hold `shipmill spec open` posts on a
feature issue until its spec pull request merges, stays its comment. Only the newest word
counts, so a hold a later comment took up, such as the one after `shipmill unlink` or a
cycle's answer, never asks for the link again; in a component only an issue of the repo
itself counts, since link refuses another repo's item there (S-038-11). It still holds on
that issue. Its note is `unlinked <owner/repo#M>` for each, then the holds as
BLOCKED's note shows them. It is read right after MALFORMED_DEPENDS and before CYCLE; the
session that takes it up runs `shipmill link #N --blocked-by <owner/repo#M>` for each.
watch_state.py's `TRIAGE_ACTION`, `shipmill status`, `fleet.py`, and the gate's walk count
it as a triage action.

### Docs

- `skills/github-issue-triage/references/triage-rubric.md`, Links between issues: the
  strict shape in one line, and "context goes on its own line, never on a Depends on
  line"; the state table gains CYCLE and MALFORMED_DEPENDS with the session's action
- `skills/github-issue-triage/SKILL.md`, Chains: show's CYCLE and MALFORMED_DEPENDS, and
  link's refusal
- `skills/github-issue-triage/references/comments.md`: the cycle question
- `skills/github-ship-watch/SKILL.md`: CHAIN_CYCLE beside CHAIN_NO_GATE
- The docstrings of `triage_state.py`, `chains.py`, and `watch_state.py`
- #1645: the skills that record a hold (github-issue-resolve, github-issue-triage,
  github-pr-triage, github-ship-watch) record it with `shipmill link`, and
  `triage-rubric.md`'s state table gains HOLD_UNLINKED

### Compatibility

Existing issues change state on the first pass after this ships, with no migration:

- An issue whose Depends on line carries prose and a reference reads MALFORMED_DEPENDS, an
  action, where it read BLOCKED or UNBLOCKED; a session rewrites the line
- A strict line whose note names a reference stops holding on that reference, so an
  issue can read UNBLOCKED sooner than before
- A Depends on line inside a code fence stops holding
- Items on a cycle read CYCLE, an action, where they read BLOCKED
- #1645: an issue held only by an agent's hold comment reads HOLD_UNLINKED, an action,
  where it read BLOCKED; a session links it. A pull request whose body already carries a
  Depends on line naming an open item leaves PRS_OPEN for PRS_PARKED

## Acceptance criteria

- S-041-1: `dependency_refs` holds on every reference of a line in the strict shape: `Depends on #1, #2 and acme/api#3`, `Depends on: #1 #2`, a `https://github.com/o/r/issues/N` or `/pull/N` URL, and a `#{B1}` placeholder (read by `unfilled_dependencies`)
- S-041-2: A strict line with a note after ` (`, `;`, or ` — ` holds on the references before it only: `Depends on acme/api#129 (deployed)` holds on `acme/api#129`, and `Depends on #5 (decided in #9)` on `#5` alone
- S-041-3: For a triaged issue, each of the three lines of #680 reads MALFORMED_DEPENDS with `line <n>: <the line>` in its note, `triage_state.py` exits 1, and `dependency_refs` still returns every reference on the line; an untriaged issue with the same body reads NEW
- S-041-4: A line starting "Depends on" that names no reference holds nothing and reads no MALFORMED_DEPENDS, and a Depends on line inside a ``` or ~~~ fence neither holds nor reads MALFORMED_DEPENDS
- S-041-5: MALFORMED_DEPENDS is read after UNFILLED and before CYCLE, SPEC_REFUSED, BLOCKED, and UNBLOCKED, and a person's item with a malformed line and no open hold reads MALFORMED_DEPENDS, never HANDOFF_DUE
- S-041-6: `chains.py link A --blocked-by B` appends `Depends on B` when A's only line naming B names it in a note (`Depends on #5 (see B)`), and prints `already linked` when a strict line names B
- S-041-7: `chains.py show` prints `CYCLE (<loop>)` for each item on a cycle of open issues, the loop the shortest through it starting at its least reference, keeps BLOCKED for an item that waits on the cycle without being on it, and exits 1
- S-041-8: `chains.py show --json` gives an item on a cycle `"state": "CYCLE"` and `"cycle"` (the loop, first reference repeated at the end), and every other row `"cycle": null`
- S-041-9: A loop through a closed item, an UNTRUSTED item (with `--trusted-only`), or an UNREADABLE item is no cycle: `chains.py show` prints no CYCLE row for it
- S-041-10: `chains.py show` ends a row whose issue has a malformed Depends on line with `MALFORMED_DEPENDS line <n>: <the line>`, gives each `--json` row a `"malformed"` list, and exits 1 for it
- S-041-11: `chains.py link A --blocked-by B`, and `link P --child C`, exit 2 with `closes a cycle:` and the loop when B (or C) already waits on A (or P) through open holds, with no mutation and no body edit sent
- S-041-12: An open issue whose holds `triage_state.py` reads, on a cycle of the repo's open issues, reads CYCLE with `cycle <loop>` in its note, and `triage_state.py` exits 1; with `--trusted-only`, a loop through an UNTRUSTED issue reads no CYCLE
- S-041-13: An issue on a cycle reads BLOCKED with `cycle <loop> waits on owner/repo#N` in its note when another issue on its loop reads MALFORMED_DEPENDS or is labelled needs-decision, and an issue on a cycle that reads UNTRUSTED, UPSTREAM, NEEDS_DECISION, DECIDED, VETOED, or OFF_MILESTONE reads that state
- S-041-14: `watch_state.py` counts CYCLE and MALFORMED_DEPENDS as triage actions, and `src/shipmill/status.py` and `fleet.py` count them as triage actions too
- S-041-15: `watch_state.py` reports one CHAIN_CYCLE action row per distinct cycle in `chains.py show --json` that has an item outside the watched repo, its subject the loop's first item and its detail the loop, none for a cycle wholly in the repo, and CHAIN_UNREADABLE for a malformed reference in `"cycle"`; `status.py` and `fleet.py` count CHAIN_CYCLE with the chain rows
- S-041-16: `triage-rubric.md`'s Links between issues states the strict shape and that context goes on its own line, never on a Depends on line; its state table has CYCLE and MALFORMED_DEPENDS with the session's action; `comments.md` has the cycle question with one option per link; github-issue-triage's SKILL.md documents CYCLE, MALFORMED_DEPENDS, and link's refusal; github-ship-watch's SKILL.md lists CHAIN_CYCLE
- S-041-17: `shipmill link` and `shipmill unlink` take `#N` (the checkout's origin repo) or `owner/repo#N`, run `chains.py link` or `unlink` from the checkout with both references made whole and `--product` and `--no-text` passed on, and pass its output and exit code on; a malformed reference exits 2 naming it before anything runs
- S-041-18: `chains.py link P --blocked-by R` on a pull request P appends one strict `Depends on R` line to P's body through the REST edit and writes no relation; run again it prints `already linked` and writes nothing; `--no-text` on a pull request exits 2, and a pull request as the item waited on or on either side of `--child` still exits 2 naming it
- S-041-19: `chains.py unlink A --blocked-by B` (or `--child`) removes the native relation the forge records and B from every strict Depends on line of A's body, dropping a line that named B alone and keeping a line's other references and note, the rest byte for byte, then posts its comment with the agent marker and no hold phrase, after which triage reads no HOLD_UNLINKED for an older hold comment naming B; with neither form it prints `not linked` and writes nothing; a malformed line naming B exits 2 before any write; on a pull request it removes the line alone
- S-041-20: `chains.py show` reads an open pull request's Depends on lines as its holds: its row's `holds` lists the open ones, `waits_on` every one, `waiting_for` is `items`, the walk follows them, and its state stays OPEN; with `--trusted-only` an untrusted author's lines hold nothing
- S-041-21: `watch_state.py` lists a non-draft pull request whose body's Depends on lines name an item still open, or unreadable, in PRS_PARKED as `WAITS_ON #N (owner/repo#M ...)` and never in PRS_OPEN or the land window's queue; an agent's draft so held reads AGENT_DRAFT_HELD naming the item; with every item closed it is in PRS_OPEN; the gate's change check reads each pull request's body into `--known`
- S-041-22: `shipmill status --item` gives a pull request in a WAITS_ON part the condition `waits on owner/repo#M (open)`, held elsewhere for another repo's item, and `shipmill queue` lists the items in its `waits_on` and counts it with an open item of the repo it waits on, whose `blocks` (in `queue` and `--item`) names it
- S-041-23: `triage_state.py` reads HOLD_UNLINKED, an action (exit 1), for an open issue whose holds it reads when the agent's newest comment (the marker, or the `--bot-login`; neither a status comment nor a question) names a hold on an open issue that no Depends on line and no native relation records, its note `unlinked <owner/repo#M>` then the holds, read after MALFORMED_DEPENDS and before CYCLE; a hold a line or relation records, one on a pull request, one a later agent comment no longer names, one in a question's options, another repo's item in a component, or one only a person's comment names, reads as before; `watch_state.py`, `shipmill status`, `fleet.py`, and the gate's walk count it as a triage action
- S-041-24: github-issue-resolve's and github-issue-triage's docs record a hold with `shipmill link`, and `triage-rubric.md`'s state table has HOLD_UNLINKED with its session's action

## Out of scope

- A native relation for a pull request: GitHub has none, so its link is its body's line
- HOLD_UNLINKED for a pull request: `triage_state.py` reads issues alone, and a pull
  request's agent hold comment holds an agent's draft as before (AGENT_DRAFT_HELD)
- A cycle through a pull request: `chains.py link` and triage read cycles of open issues
- Reading cycles across repos in `triage_state.py`: it reads the repo's own issues, and a
  cross-repo cycle is ship-watch's CHAIN_CYCLE for a person
- CHAIN_MALFORMED rows for another repo's malformed lines: that repo's triage reads them
- Hold sentences in comments (`HOLD`, `SAME_REPO`): their sentence rule (#309) stays as it
  is; only body Depends on lines change
- A one-time migration or report of the issues whose state changes: the first pass reports
  them as MALFORMED_DEPENDS or CYCLE, which is the report

## Decisions relied on

- D-14: the session rewrites a line and removes a link as the App
- D-16: an UNTRUSTED issue's holds are never read, so no cycle runs through one
- D-21: a cycle goes to the maintainer through the needs-decision protocol
- D-48: which references a malformed line meant is an `interpretation` decision

## Issues

The feature issue is shipmill/shipmill#679. Its build issues landed through pull requests
#727 (#714), #734 (#715), and #739 (#716).

- shipmill/shipmill#714: S-041-1, S-041-2, S-041-3, S-041-4, S-041-5, S-041-6
- shipmill/shipmill#715: S-041-7, S-041-8, S-041-9, S-041-10, S-041-11
- shipmill/shipmill#716: S-041-12, S-041-13, S-041-14, S-041-15, S-041-16
- shipmill/shipmill#1645: S-041-17, S-041-18, S-041-19, S-041-20, S-041-21, S-041-22, S-041-23, S-041-24

## Verification

- S-041-1: `tests/test_chain_integrity.py` (`test_s041_1_a_strict_line_holds_on_every_reference`) reads `Depends on #1, #2 and acme/api#3`, `Depends on: #1 #2`, `- depends on #1, and #2`, issue and pull URLs, and `#{B1}` placeholders as holds on every reference (placeholders through `unfilled_dependencies`), none of them malformed; `test_s041_1_a_run_of_blanks_reads_in_linear_time` reads a line of 200 blanks within the timeout
- S-041-2: `test_s041_2_a_note_after_the_references_holds_nothing` holds `Depends on acme/api#129 (deployed)` on `acme/api#129`, `Depends on #5 (decided in #9)` on `#5` alone, and the `;` and ` — ` notes the same way, with no malformed line and no placeholder read from a note
- S-041-3: `test_s041_3_a_line_of_680_reads_malformed_depends` reads each of #680's three lines as MALFORMED_DEPENDS with `line 3: <the line>` in the note while `dependency_refs` still returns every reference, and NEW untriaged; `test_s041_3_the_script_exits_1_on_malformed_depends` runs the script and gets exit 1
- S-041-4: `test_s041_4_prose_and_fenced_lines_hold_nothing` reads a prose `Depends on` line and lines in ``` and ~~~ fences as no hold and no MALFORMED_DEPENDS (NEEDS_PR), and counts a fenced line in the next line's number
- S-041-5: `test_s041_5_malformed_depends_comes_after_unfilled_and_before_the_holds` reads UNFILLED first, MALFORMED_DEPENDS over SPEC_REFUSED, BLOCKED, and UNBLOCKED, and a person's item with a malformed line and only closed holds as MALFORMED_DEPENDS, HANDOFF_DUE once the line is strict; `tests/test_cycle_states.py` (`test_s041_13_off_milestone_and_the_earlier_states_win_over_cycle`) reads it before CYCLE
- S-041-6: `test_s041_6_link_appends_a_line_for_a_reference_only_in_a_note` appends `Depends on o/r#4` when `#4` is only in a note, and prints `already linked` with no write when a strict line names it
- S-041-7: `tests/test_chain_cycles.py` (`test_s041_7_show_prints_cycle_with_the_shortest_loop_from_its_least_reference`, `test_s041_7_a_tie_goes_to_the_least_sequence_and_any_kind_of_hold_counts`, `test_s041_7_the_loop_search_is_deterministic`) prints `CYCLE (<loop>)` with the shortest loop from the least reference for each item on a cycle, ties to the least sequence, BLOCKED for the item waiting on it, and exit 1; `test_s041_7_the_loop_search_stays_fast_on_a_dense_backlog` finds the least loop through each of 100 issues with 10**10 shortest loops apiece within the timeout
- S-041-8: `test_s041_8_show_json_gives_the_cycle_and_null_for_every_other_row` and `test_s041_8_rows_off_a_cycle_keep_their_output_with_the_two_new_keys` give a cycle's rows `"state": "CYCLE"` and the loop with its first reference repeated, and every other row `"cycle": null`
- S-041-9: `test_s041_9_a_loop_through_a_closed_untrusted_or_unreadable_item_is_no_cycle` prints no CYCLE row for a loop through a closed item, an UNTRUSTED one with `--trusted-only`, or an UNREADABLE one
- S-041-10: `test_s041_10_show_ends_a_row_with_its_malformed_depends_lines_and_exits_1` and `test_s041_10_malformed_depends_sits_beside_no_gate_in_the_last_column` end the row with `MALFORMED_DEPENDS line <n>: <the line>`, give `--json` a `"malformed"` list, and exit 1
- S-041-11: `test_s041_11_link_blocked_by_refuses_a_link_that_closes_a_cycle`, `test_s041_11_link_child_refuses_a_child_that_already_waits_on_its_parent`, `test_s041_11_both_halves_in_place_on_a_cycle_are_refused_too`, and `test_s041_11_product_child_refuses_a_cycle_reading_through_the_product_token` exit 2 with `closes a cycle:` and the loop and send no write; `test_s041_11_a_closed_hold_closes_no_cycle` links through a closed hold
- S-041-12: `tests/test_cycle_states.py` (`test_s041_12_an_issue_on_a_cycle_of_the_repos_open_issues_reads_cycle`) runs `triage_state.py` on two triaged issues holding each other: both read CYCLE with `cycle o/r#3 -> o/r#5 -> o/r#3 | <holds>`, the script exits 1, an issue waiting on the cycle reads BLOCKED, an untriaged one NEW, and a loop through blockedBy and a sub-issue cased `O/R` is a cycle too; `test_s041_12_cycles_reads_only_open_issues_whose_holds_triage_reads` finds no loop through a closed, untrusted, other-repo, or self hold; `test_s041_12_with_trusted_only_no_loop_runs_through_an_untrusted_issue` reads BLOCKED with `--trusted-only` and CYCLE without
- S-041-13: `test_s041_13_a_loop_waits_on_its_malformed_or_needs_decision_issue` reads the others on a loop of three BLOCKED with `cycle o/r#3 -> o/r#5 -> o/r#9 -> o/r#3 waits on o/r#N` while #N reads MALFORMED_DEPENDS, NEEDS_DECISION (exit 0), or DECIDED; `test_s041_13_an_issue_on_a_cycle_reads_its_gated_state` reads UNTRUSTED, UPSTREAM, NEEDS_DECISION, DECIDED, and VETOED on a cycle; `test_s041_13_off_milestone_and_the_earlier_states_win_over_cycle` reads OFF_MILESTONE, UNFILLED, and MALFORMED_DEPENDS over CYCLE, and CYCLE over a person's HANDOFF_DUE
- S-041-14: `test_s041_14_cycle_and_malformed_depends_are_triage_actions_in_the_watch_status_and_fleet` finds both in `TRIAGE_ACTION`, in the watch's ISSUES row (`CYCLE #3; MALFORMED_DEPENDS #4`), which `fleet.py` counts as an action (exit 1), and on `shipmill status`'s `to triage` line; `tests/test_status_picture.py` keeps `ISSUE_LINES` covering triage_state's `ACTION`, and `tests/test_ship_watch.py` keeps `TRIAGE_ACTION` equal to it
- S-041-15: `test_s041_15_ship_watch_reports_one_chain_cycle_per_loop_through_another_repo` runs `chains.py show --json --trusted-only` on a fake forge through `chain_rows`: one `CHAIN_CYCLE o/r#3` row with the detail `o/r#3 -> x/b#2 -> o/r#3` and the fix `answer which link is wrong and remove it: ... show o/r#3`, none for the loop wholly in `o/r`, a person's action; a malformed reference in `"cycle"` reads CHAIN_UNREADABLE naming only its checked part; `test_s041_15_status_and_the_fleet_count_chain_cycle_with_the_chain_rows` shows it on status's `chain` line as WAITS ON YOU with its fix and as a fleet action
- S-041-16: `test_s041_16_the_docs_say_the_strict_shape_cycle_and_chain_cycle` finds the strict shape, "Context goes on its own line, never on a Depends on line", and link's `closes a cycle:` in `triage-rubric.md`'s Links between issues, MALFORMED_DEPENDS and CYCLE rows in its state table, the cycle question with one option per link in `comments.md`, CYCLE, MALFORMED_DEPENDS, and link's refusal in github-issue-triage's SKILL.md, and CHAIN_CYCLE in both of github-ship-watch's SKILL.md tables
- S-041-17: `tests/test_shipmill_link.py` (`test_s041_17_link_and_unlink_run_chains_py_with_whole_references`) runs `shipmill link` and `unlink` from a checkout of `o/r` and finds chains.py run there with `#N` made `o/r#N` and `--product` and `--no-text` passed on; `test_s041_17_its_output_and_exit_code_pass_through` gets chains.py's exit 2 and its message; `test_s041_17_a_malformed_reference_is_refused_before_anything_runs` refuses five malformed references and `#N` with no origin; `test_s041_17_link_runs_the_real_chains_py` runs the bundled script, which refuses a self-link
- S-041-18: `test_s041_18_link_on_a_pull_request_writes_its_line_alone_and_again_nothing` appends `Depends on x/y#116` to a pull request's body with one REST edit and no relation, then prints `already linked` with no write; `test_s041_18_a_pull_request_takes_no_relation` exits 2 for `--no-text` on one, one as the item waited on, and one on either side of `--child`, with no write
- S-041-19: `test_s041_19_unlink_removes_both_forms_and_again_nothing` removes the relation and the line, keeping a CRLF body's other lines byte for byte, then prints `not linked`; `test_s041_19_unlink_keeps_a_lines_other_references_and_its_note` keeps `- Depends on: #3, x/y#9 (all deployed)` and drops a line naming it alone; `test_s041_19_unlink_of_a_child_and_of_a_pull_request` removes a sub-issue and a pull request's line; `test_s041_19_unlinks_comment_takes_the_hold_up_so_triage_asks_no_link_again` posts the comment, names no hold in it, and reads BLOCKED where the older hold line alone read HOLD_UNLINKED; `test_s041_19_a_malformed_line_naming_it_is_refused_before_any_write` exits 2 with no write
- S-041-20: `test_s041_20_show_reads_an_open_pull_requests_depends_on_lines_as_holds` gives an open pull request's row its open holds, every `waits_on`, `waiting_for` `items`, and state OPEN, follows its lines, and with `--trusted-only` reads none from an untrusted author
- S-041-21: `test_s041_21_a_pull_request_whose_line_names_an_open_item_is_parked_not_handed` parks `#115` as `WAITS_ON #115 (o/r#7 x/y#116)` (an unread state holds), keeps `#120`, whose item merged, in PRS_OPEN, and reads the states once; `test_s041_21_after_with_person_and_to_merge_and_an_agents_draft_is_held` holds an agent's draft as AGENT_DRAFT_HELD and reads the part after WITH_PERSON and TO_MERGE, refusing it out of order or malformed; `test_s041_21_the_gates_change_check_reads_each_pull_requests_body` finds `body` in the change check's pull request fields and in `PR_FIELDS`
- S-041-22: `test_s041_22_status_and_queue_hold_a_pull_request_by_what_it_waits_on` explains a WAITS_ON pull request as parked, `waits on x/y#116 (open)` held elsewhere, and `queue` lists its `waits_on`, counts one waiting on an open issue of the repo with it, and lists it in that issue's `blocks`
- S-041-23: `test_s041_23_an_agents_hold_comment_with_no_link_reads_hold_unlinked` reads HOLD_UNLINKED with `unlinked o/r#12 unlinked o/r#13 | <holds>` for an agent's hold comment alone, BLOCKED with a Depends on line or a native relation, for a hold on a pull request, for one a later agent comment took up, for a question's options, for another repo's item in a component, or for a person's comment, nothing for a closed hold, and MALFORMED_DEPENDS first; `test_s041_23_the_script_reads_hold_unlinked_for_an_issue_and_not_a_pull_request` runs `triage_state.py` on a fake GitHub and exits 1 naming `o/r#12`, an issue, and never `o/r#20`, a pull request; `tests/test_spec_open.py` keeps a feature issue held on its spec pull request BLOCKED; `test_s041_23_the_watch_status_and_gate_count_it_as_a_triage_action` finds it in `TRIAGE_ACTION`, status's `to triage` line, and a gate tier; `tests/test_status_comment_readers.py` keeps its held issue BLOCKED by linking the hold
- S-041-24: `test_s041_24_the_skills_record_a_hold_with_shipmill_link` finds `shipmill link` in github-issue-resolve's, github-issue-triage's, and github-pr-triage's docs, HOLD_UNLINKED in triage's SKILL.md and rubric table, and `WAITS_ON` in github-ship-watch's PRS_PARKED row
