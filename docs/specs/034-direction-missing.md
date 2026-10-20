# S-034: The watch asks for the direction a repo with [agents] lacks

status: approved
serves: G-5

## Problem

A repo that connected `[agents]` before 0.51.0 has no `docs/product.md`, and nothing in the
loop asks the maintainer to write one after an upgrade (shipmill/shipmill#497):

- `shipmill-setup` asks for the direction only when `[agents]` is first connected (its
  step 2)
- the config upgrades of spec 014 cover config keys only, so no `shipmill-upgrade` issue is
  opened for a missing file
- `setup_state.py`, `watch_state.py`, and `shipmill gate` don't read whether the direction
  exists; only `shipmill doctor` fails (S-024-5), and nobody runs it after an upgrade

Without the file the loop silently runs as before spec 024: `pr_gate.py` skips the plan
check, `specs.py check` asks for no `serves:`, and triage names no goal. D-34 says such a
repo keeps its direction in `docs/product.md` and only the maintainer changes it, so
shipmill can't write one on its own; what is missing is the question, put once, where the
maintainer answers the loop's other questions.

## Behaviour

### Reading the direction at a ref

`shipmill product check` (`src/shipmill/product.py`, `src/shipmill/cli.py`) gains `--ref
REF`: it reads `docs/product.md`, and every `docs/product/<file>.md` a moved section links,
from that git ref of the `--repo` checkout (`git show <ref>:<path>`) instead of the working
tree, and applies the same rules. It exits 0 on a well-formed direction, 1 naming the file,
line, and rule broken, 1 with `no docs/product.md at <ref>` when the file is absent there,
and 2 for a ref git can't resolve. Without `--ref` it reads the working tree as today.

### `DIRECTION_MISSING` and `DIRECTION_PENDING`

`skills/github-ship-watch/scripts/watch_state.py` reads the direction only for a repo whose
`.github/shipmill.toml` has an `[agents]` table (its existing `agents_table`), after the
fetch of the default branch it already makes: `git -C <repo-dir> cat-file -e
origin/<branch>:docs/product.md` tells whether the file exists, and, when it does, `uvx
--from <tool> shipmill --repo <repo-dir> product check --ref origin/<branch>` whether it is
well formed. Any other exit of either than the ones above stops the watch with exit 2, as a
failing `shipmill plan` does. A repo without `[agents]` gets neither row and no direction
read at all, and a well-formed direction gives no row.

Two new states, side by side as `GATE_NO_APP` (a person's) and `UPGRADE_PENDING` (an
agent's) are:

- `DIRECTION_MISSING`, subject `docs/product.md`: in `ACTION` (exit 1), never in `AGENT`,
  since the answer is the maintainer's. Its detail says which case holds and where the
  question stands; its fix (spec 011) is the one line that clears it:
  - the file is absent and the direction issue (below) is open: `answer the direction
    question: https://github.com/<repo>/issues/<n>`
  - the file is absent and a pull request from `shipmill/direction` is open: `review and
    merge https://github.com/<repo>/pull/<n>`
  - the file is absent and no direction issue exists yet: the github-ship-watch skill's fix
    (`skill_fix`), whose session opens the question
  - the file exists and `product check` refuses it: `fix docs/product.md, then run
    shipmill product check`. The maintainer wrote that file, so no question is asked and no
    `DIRECTION_PENDING` row shows: repairing it is changing the direction (D-34)
- `DIRECTION_PENDING`: in `ACTION` and in `AGENT`, so `shipmill gate` starts a session for
  it. Shown only while the file is absent, with a detail saying what the session does:
  - no direction issue open and none closed: subject `docs/product.md`, `open the
    direction question`
  - the direction issue open with no `needs-decision` label (a reopened one, or one whose
    question was never posted): subject `#<n>`, `ask the maintainer`
  - the direction issue labelled `needs-decision` with a reply from an OWNER, MEMBER, or
    COLLABORATOR after its question (`triage_state.py`'s rule, so `triage_state.py` reads it
    DECIDED, D-21): subject `#<n>`, `answered; take up the answer`
  - a pull request from the repo's own `shipmill/direction` branch (state CLOSED, not a
    fork's) closed unmerged while the issue is open: subject `#<n>`, `pull request #<m>
    closed unmerged, a decline: close #<n> as not planned`

While the question waits (the label on, no trusted reply) the issue is in `NEEDS_DECISION`
and no `DIRECTION_PENDING` row shows; while a pull request from `shipmill/direction` is open,
none shows either. So the watch never asks a second time while a question is open, and a
tick never starts a session for a question nobody answered. The fix of every row is built
from the repo, the numbers, and the paths, never from the issue's text (D-16).

### The direction issue

The question lives in one issue per repo, opened by the session that takes up `open the
direction question`, as the gate's App (D-14, `shipmill gh`):

- title `Write the product's direction (docs/product.md)`
- label `shipmill-direction`, created first with `gh label create shipmill-direction
  --description "shipmill's question for the product's direction"` when missing
- first line of the body the marker `<!-- shipmill-direction -->`; the body then says what
  the loop loses without the file (no goal named in triage, no plan check, no `serves:`),
  that only the maintainer changes it, and links shipmill's guide to it,
  `https://github.com/shipmill/shipmill/blob/main/docs/direction.md` (#498), so the
  maintainer reads what each section is for before answering

`skills/github-issue-triage/scripts/triage_state.py` holds the one definition both scripts
use, as it does for upgrade issues: `DIRECTION_LABEL`, `DIRECTION_MARKER`, and
`direction_issue(issue, bot_login)`, true for an issue with the label, the marker as its
body's first line, and an author who is an OWNER, MEMBER, or COLLABORATOR or the
`--bot-login`. An issue missing any of the three is any issue to triage. `watch_state.py`
imports them, as it imports `UPGRADE_LABEL`, and:

- keeps every direction issue out of ISSUES and ISSUES_OPEN, as it does upgrade issues
- reads the open ones and the closed ones (`gh issue list --label shipmill-direction --state
  all`, one call) only for a repo with `[agents]` whose file is absent; with several open,
  the oldest is the question
- reads the pull requests of `shipmill/direction` (`gh pr list --head shipmill/direction
  --state all`) only while a direction issue is open

Since the App or a trusted person authors the issue, `--trusted-only` already reads it as
trusted (D-16), with no extension of D-30, which covers only issues the release workflow
authors as `github-actions[bot]`. A labelled, marked issue by anyone else is no direction
issue, and with `--trusted-only` stays UNTRUSTED.

`skills/github-issue-triage/SKILL.md` adds, next to its rule for upgrade issues: a direction
issue is shipmill's question, so triage posts no verdict on it, and when `triage_state.py`
reads it DECIDED, leaves the reply and the `needs-decision` label to github-ship-watch.

`skills/shipmill-setup/scripts/setup_state.py` wants the `shipmill-direction` label wherever
it wants `needs-decision` (a config with `[agents]`), in its LABELS_MISSING row.

### The question

`skills/github-ship-watch/SKILL.md` gets a Direction section, followed under "watch" only
(under "status" it reports the rows and stops, as for upgrades). For `ask the maintainer`,
and right after it opens the issue, the session asks with github-issue-triage's
needs-decision protocol (`skills/github-issue-triage/references/needs-decision.md`): a gate
session posts it on the issue as the App and adds the `needs-decision` label. The question,
word for word:

```markdown
<!-- shipmill:needs-decision -->
@<login> Decision needed: write this repo's product direction, `docs/product.md`, so the agents work toward it?

1. Write it (recommended): reply with the five sections below in your own words; shipmill turns them into a pull request adding the file, which waits for you to merge it
2. Not now: close this issue; shipmill won't ask again until you reopen it

- Mission: what the product is for
- Users: who it serves, one per line
- Goals: the outcomes it works toward now, one per line
- Non-goals: what it deliberately doesn't do, one per line, or none
- Quality bar: what every change must hold, one per line

What each section is for: https://github.com/shipmill/shipmill/blob/main/docs/direction.md
Reply here with a number or your own answer; shipmill takes this up on the tick after your reply.
```

An interactive gate session (`Gate session:`) also asks in the session, one section at a
time in that order, as shipmill-setup's step 2 does, and on an answer there posts it on the
issue as the protocol's Answered in the session says before it acts. A session the user
started by hand asks only in the session, then posts the answer on the issue the same way,
so the decision lives on GitHub either way.

### Taking up the answer

The answer is the newest reply after the question from an OWNER, MEMBER, or COLLABORATOR,
told by its `author_association`. The session removes the `needs-decision` label, then:

- **2**, or a reply that declines in its own words: closes the issue as not planned, a
  decline
- **the sections**: writes `docs/product.md` in spec 024's fixed structure from the reply's
  words only: the level-one heading is the repo's name unless the reply names the product,
  and each user, goal, non-goal, and quality-bar line becomes one item with its id from 1
  (`- U-1: ...`). It never invents an item and never fills one in from the README or the
  code; splitting the maintainer's sentence into one-line items is all the editing it does
- a reply that leaves Users, Goals, or Quality bar empty, answers none of the options, or
  asks something back: asks again with the protocol, naming only the sections still owed;
  nothing is written meanwhile

With the file written, the session runs `shipmill product check` until it exits 0, and in
a new worktree from `origin/<default>` on the branch `shipmill/direction` commits it (with
the changelog entry the repo's rules ask for), pushes, and opens the pull request as the App
through `--body-file`. The body shows the file, holds `Closes #<issue>` and the line
`Direction from @<login> in #<issue>`, and says the pull request waits for the maintainer to
merge it. The watch never merges it, and github-pr-triage never merges an edit of
`docs/product.md` on its own judgment (S-024-11), with or without the answer on the issue:
unlike an upgrade pull request (S-014-13), the file's words are what the maintainer
approves.

### A decline, and asking again

A direction issue closed for any reason while the default branch still has no
`docs/product.md`, with none open, is a decline: the watch shows neither row for the repo,
and its TRIAGE_MODE row (report only) adds `no direction: declined in #<n>`, so the report
still says it. `shipmill doctor` keeps failing the repo (S-024-5) as the standing reminder.
The question comes back only when the maintainer asks for it: reopening the issue (it reads
`ask the maintainer` again, since the label came off when the decline was taken up), or
asking a session to write the direction, which reopens the newest direction issue rather
than opening a second. A pull request from `shipmill/direction` closed unmerged is a decline
too: the session closes the issue as not planned. Once a well-formed `docs/product.md` is on
the default branch, by this pull request, shipmill-setup, or the maintainer's own, neither
row shows and no issue is read.

## Acceptance criteria

- S-034-1: `shipmill product check --ref REF` reads `docs/product.md` and the files its moved sections link at that git ref, not the working tree, exits 0 on a well-formed direction and 1 naming the file, line, and rule on a broken one, 1 with `no docs/product.md at <ref>` when the file is absent there, and 2 for a ref git can't resolve
- S-034-2: `watch_state.py` reports `DIRECTION_MISSING` (an action row, exit 1, `agent` false) for a repo whose config has an `[agents]` table and whose `origin/<default>` has no `docs/product.md` or one `shipmill product check --ref` refuses; a well-formed direction gives no row, and a repo without `[agents]` gets no direction row and runs no direction read
- S-034-3: the `DIRECTION_MISSING` fix names the question: the open direction issue's URL, the open `shipmill/direction` pull request's URL, or with neither the github-ship-watch skill's fix; for a refused file it names `shipmill product check` and no `DIRECTION_PENDING` row shows
- S-034-4: `watch_state.py` reports `DIRECTION_PENDING` (an action row, `agent` true) with `open the direction question` for a repo with `[agents]`, no `docs/product.md`, and no direction issue, and never while a direction issue is open and waits on a `needs-decision` question with no trusted reply, which is in NEEDS_DECISION instead
- S-034-5: `triage_state.py`'s `direction_issue` is true only for an issue with the `shipmill-direction` label, `<!-- shipmill-direction -->` as its body's first line, and an author who is an OWNER, MEMBER, or COLLABORATOR or the `--bot-login`; `watch_state.py` keeps such an issue out of ISSUES and ISSUES_OPEN, and with `--trusted-only` one the `--bot-login` opened is not UNTRUSTED while one by any other author stays UNTRUSTED and is no direction issue
- S-034-6: an open direction issue reads `DIRECTION_PENDING` with `ask the maintainer` without the `needs-decision` label, with `answered; take up the answer` once an OWNER, MEMBER, or COLLABORATOR replied after its question, and with `close #<n> as not planned` when a pull request from the repo's own `shipmill/direction` branch closed unmerged (never a fork's, never a merged one); an open `shipmill/direction` pull request gives no `DIRECTION_PENDING` row
- S-034-7: a direction issue closed for any reason, with none open and no `docs/product.md` on the default branch, gives neither row (the watch's exit doesn't count it) and adds `no direction: declined in #<n>` to TRIAGE_MODE; the same issue reopened reads `DIRECTION_PENDING` with `ask the maintainer` again
- S-034-8: github-ship-watch's Direction section opens the issue as the App with the title, the `shipmill-direction` label, the marker as its first line, and the `docs/direction.md` link, posts this spec's question word for word through the needs-decision protocol under "watch" only, and has an interactive gate session also ask the five sections one at a time
- S-034-9: github-ship-watch's Direction section closes the issue as not planned on answer 2 or a declining reply, asks again naming only the sections still owed when Users, Goals, or Quality bar is empty, and otherwise writes `docs/product.md` from the reply's words only (never from the README, never an invented item), runs `shipmill product check`, and opens the pull request as the App on `shipmill/direction` with `Closes #<issue>`, the `Direction from @<login> in #<issue>` line, and no merge
- S-034-10: github-issue-triage's SKILL.md says triage posts no verdict on a direction issue and leaves a DECIDED one's reply and `needs-decision` label to github-ship-watch
- S-034-11: `setup_state.py` lists `shipmill-direction` in LABELS_MISSING for a config with `[agents]` when the label is absent, and never for a config without `[agents]`
- S-034-12: github-ship-watch's SKILL.md lists `DIRECTION_MISSING` as an action that is never an agent's and `DIRECTION_PENDING` as an agent's row, in its state table and its `agent` table, matching `watch_state.py`'s `ACTION` and `AGENT` sets

## Out of scope

- Repairing a direction `shipmill product check` refuses: the maintainer wrote it, so the
  fix is theirs; the row names the command that shows what's broken
- `shipmill status`, `shipmill gate`, and `setup_state.py` reading whether the direction
  exists: `DIRECTION_MISSING` in the watch and `shipmill doctor`'s check (S-024-5) carry it
- An `[autonomy]` level for the question: the direction is only ever the maintainer's
  (D-34), so there is no `act`
- Asking for a `REVIEW.md`: it is optional (spec 024), and shipmill-setup offers one
- Writing the guide `docs/direction.md`: #498 adds it; this spec only links it
- Merging the direction pull request on the maintainer's answer, as upgrade pull requests
  are (S-014-13): the maintainer merges it

## Decisions relied on

- D-10: shipmill proposes and the maintainer accepts or declines; a decline is kept
- D-14: the session opens the issue, posts the question, and opens the pull request as the App
- D-16: only a trusted author's direction issue counts, and the fix holds no issue text
- D-19: a person's action in the watch that no agent can take, as `GATE_NO_APP`
- D-21: the question goes through the needs-decision protocol, and the answer reads DECIDED
- D-30: covers only the release workflow's upgrade issues; the direction issue needs no extension of it
- D-34: a repo with `[agents]` keeps its direction in `docs/product.md`, and only the maintainer changes it

## Issues

## Verification
