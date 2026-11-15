# S-055: Landing rules are held by code: the merge runs the gate, reads the answer, and needs a review and a plan

status: approved
serves: G-2

## Problem

The landing rules hold because each session reads its instructions and follows them, not
because anything refuses a merge that breaks them (#1048). Three requests name the gaps:

- **The gate's verdict and the maintainer's acceptance** (#959). Nothing makes a session run
  `pr_gate.py` before it merges or read what it said: in about 297 gate merges of this repo, two
  had no gate verdict or an open question (#316, #922), and in 14 connected repos 9 merges had
  no `pr_gate.py` in the session and one merged 13 seconds after a FAILED verdict.
  `--maintainer-accepted` is a flag the session sets; it was used on more than 100 pull
  requests, each with a real answer, some only on the linked issue, but nothing checks for
  one, and on #901 the head that merged was two commits past the head that was answered
- **A review of the merging head** (#964). github-pr-triage asks for a reviewer agent on every
  code pull request, and nothing checks that one ran: about 168 of 275 gate-merged code pull
  requests in 14 repos had one dispatched, and a 626-line pull request merged without one broke
  production workers on every deploy for a day
- **The plan** (#1016). `pr_gate.py` refuses an agent's pull request without a valid
  `## Plan` only at landing, so the landing session writes one in a minute on an unchanged
  head: 16 pull requests in three repos in a week

Branch protection can't carry these everywhere: 10 of those 14 repos are private on GitHub's
free plan, where rulesets aren't available, and the delivery hooks let a command run when they
can't start (D-54). The check inside `shipmill gh` is the barrier there.

Already shipped from these requests, and not repeated here: `shipmill gh pr merge` refuses a
pull request labelled `needs-decision` and a `--match-head-commit` shorter than a full SHA
(S-030-23, S-030-24, #961), `pr_gate.py`'s verdict line prints the full head it judged
(#1023), and `Serves:` accepts the quality bar's `Q-n` ids (#1020).

## Behaviour

### One place for every landing rule

Every rule that decides whether a pull request may land is a verdict of
`skills/github-pr-triage/scripts/pr_gate.py`, and the merge refuses anything but READY. A new
landing rule (such as spec 056's land window) is added to `pr_gate.py` as a verdict, never as
a separate check in the merge path.

### The merge runs the gate

`shipmill gh pr merge <n>` and the merge API `PUT repos/<o>/<r>/pulls/<n>/merge`, as the App
(where `_hold_never` in `src/shipmill/cli.py` runs today), run the `pr_gate.py` the wheel ships
on pull request n before gh runs: with `-R` the checkout's repo, `--checkout` the checkout,
and `--bot-login` the App's bot login, with the App's token. `src/shipmill/app_gh.py` reads
the merge's pin.

- **Exit 0 (READY) at head H.** A merge with no `--match-head-commit` (no `sha` field) runs gh
  with `--match-head-commit H` (`sha=H`) added, so GitHub merges only the head the gate judged.
  A merge whose pin names H runs as given. A merge whose pin names another full SHA exits 2 and
  gh never runs, naming both SHAs: the head moved since the session read it
- **Any other exit.** The merge exits 2 and gh never runs, printing
  `<merge command> is refused: pr_gate.py reads #<n> <VERDICT>` followed by the gate's verdict
  line and reason lines as it printed them. A `pr_gate.py` that exits 2 (a state it can't
  judge), can't be started, or prints no verdict line refuses the merge the same way: the merge
  fails closed

No flag of `shipmill gh` turns the gate off. The S-030-13 and S-030-23 holds keep running
before it, so a `never` zone or the `needs-decision` label still refuses with its own message.

### An agent's pull request

`pr_gate.py` reads a pull request as an agent's when its author is the `--bot-login`, when
`--agent` names it, or when its body carries the agent marker `<!-- shipmill:agent -->` on a
line of its own (D-62), so a pull request opened with a decider's token (D-65) is still an
agent's.

### The maintainer's acceptance is read from GitHub

`pr_gate.py` drops `--maintainer-accepted`: passing it exits 2, saying the acceptance is read
from the answer on GitHub. Instead it reads the answer itself, for each pull request that
would otherwise read NEEDS_DECISION (an `ask` zone, a Protected areas glob, or a direction
edit without `[agents]`):

1. **The question.** The newest needs-decision question (a comment whose first line is the
   marker `<!-- shipmill:needs-decision -->`, by the App or a trusted person) on the pull
   request, or, when the pull request has none and the App or an OWNER, MEMBER, or
   COLLABORATOR opened it, on an issue it closes or names as `Part of #N`. Anyone who can open
   a pull request can write `Fixes #N` in its body, so an outsider's pull request is answered
   on its own question only (#1122)
2. **The answer.** The first reply after that question by the reply rules credit.py's
   `answers` and retro.py's `first_answer` already read (S-049-4, S-030-18): a comment by an
   OWNER, MEMBER, or COLLABORATOR whose body carries no agent marker, or the App's relay whose
   first line is `Decision by @<login>` (the login bare or in a code span) naming the
   maintainer. A question with a newer question after it is no longer the one answered
3. **Acceptance.** The answer accepts when its whole reply takes the option the question marks
   `(recommended)` as it stands, read as S-030-18 reads it: its number alone (`1`, `1.`,
   `Option 1`), its text alone, or the option as listed, its number and its own text together
   (`1. <text>`, `1) <text>`, `1: <text>`, `Option 1: <text>`, the text the part before
   ` (recommended)`, with or without that mark; #1150). A number and a text naming different
   options, or a text that narrows or extends the option, takes neither. The whole reply is every non-blank line of the comment, a
   relay's after its `Decision by` line with the template's `Answered in the session:` taken
   off, the agent marker left out; a reply of more than one line (`1`, then `but rename X
   first`) answers in the person's own words. An answer in other words, another option, or no
   answer leaves the verdict NEEDS_DECISION
4. **The head it covers.** An answer covers the head its question names: a question on a pull
   request states the head's CI on the line under its first, `CI on <sha7>: ...`
   (needs-decision.md, #1028), and names that head in full on a hidden line under it,
   `<!-- shipmill:head <40-hex sha> -->`; that exact commit is the one answered. A commit's
   `committedDate` is its author's to set, a force-push's `beforeCommit` may be a head pushed
   after the answer, and a 7-hex prefix is matched by a commit made to order in about 2^28
   tries, so none of them names what the maintainer saw (#1122). A question without the
   hidden line leaves the verdict NEEDS_DECISION, so it is asked again with it. It covers the
   judged head when it is that commit, or when the pull request's own change is the same at
   both heads: the patch of
   `git diff $(git merge-base origin/<base> <head>) <head>` is equal, so a rebase or a merge of
   the base that changes nothing of the pull request's own still lands. A spec pull request
   compares its spec file with `specs.py same-approval` instead, so a format-only change lands
   on the answer (D-81). An answer on an issue given before the pull request opened covers
   every head; one given after binds to the head its question names, as on the pull request

With an accepting answer that covers the judged head, the `ask` zones and Protected areas
asks are lifted and CI decides, as `--maintainer-accepted` did. Without one, the
`needs-decision:` lines stay, and one more line says why the last answer didn't count:
`  needs-decision: answered at <sha7>, and the change differs since`,
`  needs-decision: the answer doesn't take the recommended option`,
or `` needs-decision: the question names no head: ask again with its `<!-- shipmill:head <sha> -->` line ``
(a head the checkout can't fetch reads as differing). A `never` zone stays MAINTAINER_ONLY whatever the answer (D-48).

### A review of the merging head

An agent's ready pull request that changes code and would otherwise read READY reads
UNREVIEWED, exit 9, with the line
`  unreviewed: no review of <head sha7> on record; review it, then record it with shipmill review record`,
until a review record covers the judged head. UNREVIEWED ranks between PENDING and BLOCKED;
`--wait` doesn't poll on it.

A pull request changes code unless every file it touches is documentation: a name ending
`.md`, `.mdx`, `.rst`, or `.txt`, or a path under `docs/`, and none of them the agents'
instructions (under `skills/`, `.claude/`, or `.claude-plugin/`, or named `CLAUDE.md`,
`AGENTS.md`, or `REVIEW.md`). A docs-only pull request, a spec pull request among them, needs
no review record. A person's pull request needs none either.

A review record is a pull request review on GitHub, read from
`GET repos/<o>/<r>/pulls/<n>/reviews`:

- the App's review whose body's first line is `<!-- shipmill:review merge -->`, or
- an APPROVED review by an OWNER, MEMBER, or COLLABORATOR whose body carries no agent marker

whose `commit_id` is the judged head, or a head whose own change is the same as the judged
head's (as for an answer). The App's newest review record for a covered head counts: one whose
first line is `<!-- shipmill:review refuse -->` leaves the pull request UNREVIEWED.

`shipmill review record <n> --head <sha> --verdict merge|refuse --body-file <file>`, in
`src/shipmill/cli.py`, posts that review as the App through `shipmill gh`: event `COMMENT`,
`commit_id` the head, and a body of the marker line followed by the file's text (the reviewer's
report). It exits 2 and writes nothing when `--head` isn't 40 hex characters, isn't pull
request n's current head, or the App isn't available.

github-pr-triage's reviewer brief (`skills/github-pr-triage/references/reviewer-brief.md`)
reports the head it reviewed; the landing session pushes that head, then records the
reviewer's verdict with `shipmill review record`. A small docs-only pull request reviewed
inline needs no record.

### The plan is written when the pull request opens

`shipmill gh pr create`, in a checkout with `[agents] app_id` set (as the App, or with a
decider's token), and whose default branch holds `docs/product.md`, reads the body it would
send (`--body`, `--body-file`, or stdin) with `pr_gate.py`'s `plan_problems` and the ids
`direction_ids` reads from the default branch. A body that has problems exits 2 and gh never
runs, printing each problem. A body with a line starting `Spec for #N` (spec 053's reading)
needs no plan, so `shipmill spec open` passes. A repo without `docs/product.md` on its default
branch is not checked, as `pr_gate.py` doesn't check it. The landing check in `pr_gate.py`
stays as it is.

### The skills

`skills/github-pr-triage/SKILL.md`, `skills/github-pr-triage/references/landing.md`, and
`skills/github-issue-triage/references/needs-decision.md` drop `--maintainer-accepted`: the
answer is read from GitHub, and the merge runs the gate itself, so running `pr_gate.py` before
the merge stays a way to read the verdict, not the barrier. The implementer brief
(`skills/github-issue-triage/references/implementer-brief.md`) writes the plan into the body
it opens the pull request with.

## Acceptance criteria

- S-055-1: `shipmill gh pr merge <n>` and the merge API `PUT`, as the App, run the wheel's `pr_gate.py` on pull request n with the checkout's repo, the checkout, and the App's bot login before gh runs, and exit 2 without running gh when it exits other than 0, printing `is refused: pr_gate.py reads #<n> <VERDICT>` and the gate's verdict and reason lines; on exit 0 they run gh
- S-055-2: When `pr_gate.py` reads READY at head H, a merge given no pin runs gh with `--match-head-commit H` (the API `PUT` with `sha=H`), a merge pinned to H runs as given, and a merge pinned to another full SHA exits 2 naming both SHAs without running gh
- S-055-3: A `pr_gate.py` that exits 2, can't be started, or prints no verdict line makes the merge exit 2 without running gh
- S-055-4: `pr_gate.py --maintainer-accepted` exits 2 with a message saying the maintainer's acceptance is read from the answer on GitHub
- S-055-5: `pr_gate.py` reads a pull request with an `ask` zone (or a Protected areas glob without `[agents]`) on CI alone when the newest needs-decision question on it names the judged head in full on its line `<!-- shipmill:head <40-hex sha> -->` (under its `CI on <sha7>` line) and has a first trusted answer that takes the `(recommended)` option; a commit's date, a force-push's `beforeCommit`, and a head sharing only the named head's 7-hex prefix are not covered, and a question without that line keeps NEEDS_DECISION with the line `` needs-decision: the question names no head: ask again with its `<!-- shipmill:head <sha> -->` line ``
- S-055-6: The same answer covers a judged head after a rebase or a merge of the base whose own change (the patch from the merge-base to the head) equals the answered head's, and doesn't cover one whose own change differs, which reads NEEDS_DECISION with the line `needs-decision: answered at <sha7>, and the change differs since`
- S-055-7: An accepting answer on an issue the pull request closes or names as `Part of #N`, when the pull request has no question of its own and the App or an OWNER, MEMBER, or COLLABORATOR opened it, counts as on the pull request; one given before the pull request opened covers every head. Any other author's pull request is answered only on its own question
- S-055-8: `pr_gate.py` keeps NEEDS_DECISION for no answer, a CONTRIBUTOR's or another bot's reply, a reply carrying the agent marker, a reply that picks another option or answers in its own words, a reply with any line past the option (its whole reply is read; a relay's `Decision by` line, `Answered in the session:`, and the agent marker are no part of it), and an answer to a question a newer question follows
- S-055-9: A relayed answer, the App's comment whose first line is `Decision by @<login>` or ``Decision by `@<login>` ``, counts as a trusted answer for S-055-5 to S-055-7
- S-055-10: For a spec pull request the answered and judged heads are compared with `specs.py same-approval`: exit 0 covers the judged head, exit 1 or 2 doesn't
- S-055-11: A `never` zone reads MAINTAINER_ONLY, exit 7, whatever the answer
- S-055-12: `pr_gate.py` reads a pull request as an agent's when its body carries the agent marker on a line of its own, whoever its author, as it does for the `--bot-login`'s
- S-055-13: An agent's ready pull request that changes a file outside documentation and would otherwise read READY reads UNREVIEWED, exit 9, with an `unreviewed:` line naming the head, when no review record covers its head
- S-055-14: The App's review whose first line is `<!-- shipmill:review merge -->`, or a trusted person's APPROVED review without the agent marker, whose `commit_id` is the judged head or a head with the same own change, lets that pull request read READY; the App's newest record `<!-- shipmill:review refuse -->` for the head keeps it UNREVIEWED
- S-055-15: A docs-only pull request (every file `.md`, `.mdx`, `.rst`, `.txt`, or under `docs/`, none under `skills/`, `.claude/`, `.claude-plugin/`, nor `CLAUDE.md`, `AGENTS.md`, `REVIEW.md`) and a person's pull request read READY with no review record
- S-055-16: `shipmill review record <n> --head <sha> --verdict merge|refuse --body-file <f>` posts, as the App, a pull request review with event `COMMENT`, `commit_id` the head, and a body whose first line is the verdict's marker; it exits 2 and writes nothing when the head isn't 40 hex characters or isn't pull request n's current head, or the App isn't available
- S-055-17: `shipmill gh pr create`, with `[agents] app_id` set and `docs/product.md` on the default branch, exits 2 without running gh when the body it would send has no plan `plan_problems` accepts, printing each problem, and runs gh for a valid plan, for a body with a `Spec for #N` line, and in a repo without `docs/product.md` on its default branch
- S-055-18: `github-pr-triage`'s `SKILL.md` and `landing.md` and `needs-decision.md` name no `--maintainer-accepted`; the reviewer brief and landing say the reviewed head is recorded with `shipmill review record`, and the implementer brief says the plan goes in the body the pull request is opened with
- S-055-19: An answer that names the `(recommended)` option as listed, its number and its own text together (`1. <text>`, `1) <text>`, `1: <text>`, `Option 1: <text>`, `Option 1. <text>`, the text the part before ` (recommended)`, with or without that mark, emphasis and code marks aside), takes it, for `pr_gate.py`'s acceptance and the retro's `recommended` count alike, through retro.py's `takes_recommended`; a number and a text naming different options, a text that narrows the option or has words past it, and a prefix of its text do not

## Out of scope

- A required status check on the default branch that runs the same gate, and CI reporting on every pull request (docs-only ones included) so such a check can be required: the opportunity's last Success item, a follow-up once this ships; changing the repository's settings stays the maintainer's step
- Proving the review was done by a different agent than the implementer: a record the App writes proves that a review of that head was recorded, not who thought it (see Decisions for you)
- A merge outside `shipmill gh` (plain gh, the web UI) or one `shipmill gh` writes as the host's login: a person's merge is theirs
- Detecting a plan edited after the pull request opened: the check runs at creation and at landing, as today
- The headless allowlist denials #959 counted: a skill-instruction fix, not a landing rule

## Decisions relied on

- D-34
- D-48
- D-49
- D-54
- D-62
- D-65
- D-67
- D-75
- D-81

## Issues

- shipmill/shipmill#1088: S-055-5, S-055-6, S-055-7, S-055-8, S-055-9, S-055-10, S-055-11
- shipmill/shipmill#1090: S-055-12, S-055-13, S-055-14, S-055-15, S-055-16, S-055-18
- shipmill/shipmill#1091: S-055-17
- shipmill/shipmill#1093: S-055-1, S-055-2, S-055-3
- shipmill/shipmill#1095: S-055-4
- shipmill/shipmill#1150: S-055-19

## Verification
