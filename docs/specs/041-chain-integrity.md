# S-041: Chain integrity: cycles and strict Depends on lines

status: approved
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

### Docs

- `skills/github-issue-triage/references/triage-rubric.md`, Links between issues: the
  strict shape in one line, and "context goes on its own line, never on a Depends on
  line"; the state table gains CYCLE and MALFORMED_DEPENDS with the session's action
- `skills/github-issue-triage/SKILL.md`, Chains: show's CYCLE and MALFORMED_DEPENDS, and
  link's refusal
- `skills/github-issue-triage/references/comments.md`: the cycle question
- `skills/github-ship-watch/SKILL.md`: CHAIN_CYCLE beside CHAIN_NO_GATE
- The docstrings of `triage_state.py`, `chains.py`, and `watch_state.py`

### Compatibility

Existing issues change state on the first pass after this ships, with no migration:

- An issue whose Depends on line carries prose and a reference reads MALFORMED_DEPENDS, an
  action, where it read BLOCKED or UNBLOCKED; a session rewrites the line
- A strict line whose note names a reference stops holding on that reference, so an
  issue can read UNBLOCKED sooner than before
- A Depends on line inside a code fence stops holding
- Items on a cycle read CYCLE, an action, where they read BLOCKED

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

## Out of scope

- A `chains.py unlink` command: the session removes the chosen link with `gh` (the body
  edit and `removeBlockedBy` or `removeSubIssue`); a command can come later if sessions
  get it wrong
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

The build issues, filled in once they are filed: one `- owner/repo#N: S-041-1, S-041-2` per
line, naming the criteria that issue delivers. Each criterion belongs to exactly one.

## Verification

Filled in when the spec reaches `built`: one line per criterion id, saying how it was
checked against the default branch (beyond its tests) and the result.
