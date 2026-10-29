# S-050: Tell an agent's text from a person's by its marker, never by its author

status: approved
serves: G-2

## Problem

shipmill decides whether a record on GitHub is a person's decision or an agent's text by who
wrote it (#795). That works only while agents and people write as different accounts:

- With `[agents] app_id`, the reply to a needs-decision question is a comment by an OWNER,
  MEMBER, or COLLABORATOR other than the App (D-49, the `--bot-login` row of
  `needs-decision.md`'s reply table). The App's comments never answer, since they are the App's
- Without the App (`[agents] identity = "host"`, spec 037), a session posts as the host's `gh`
  login, the same account as the maintainer. The reply is then any newer trusted comment
  without the needs-decision marker. A triage comment, a shipped notice, or any other agent
  comment posted after the question carries no such marker, so it reads as the maintainer's
  answer: the item reads DECIDED and the gate starts a session that acts on a decision nobody
  took. The same holds for a veto, which is read by its first word from a trusted author
- Spec 049 counts the author of an issue a pull request closes as a decider, "since the
  filing is the decision" (S-049-5). It runs only through `shipmill gh` with the App today,
  where an agent's issue is the App's and a bot is never a decider. Once an agent's issue can be
  written as a person, its author would be credited for a decision they never took. The spec
  gate reads "an issue the maintainer filed" the same way (`spec-gate.md`, `triage-rubric.md`),
  and without the App an issue the session filed already has the maintainer's author
  association

Reading the author fails open: wherever an agent writes as a person, a missing marker turns
agent text into a decision. The rule this spec builds is the issue's: an agent's text is told
from a person's by a sign the agent can't leave off, added by the tooling it writes through,
and a record whose origin can't be read counts as an agent's, so a failure is a missed
decision, never an invented one.

## Behaviour

### The marker

An agent's record carries the line `<!-- shipmill:agent -->`. A body **carries the marker**
when any of its lines, stripped of surrounding whitespace, matches
`<!-- shipmill:agent(?:\s[^>]*)?-->`, so a later attribute (`<!-- shipmill:agent via=gh -->`)
reads the same. shipmill writes it as the body's last line, after a blank line, and never as
its first line: the first line stays free for the markers and prefixes readers already match
there (`Triage:`, `<!-- shipmill:needs-decision -->`, `Decision by @<login>`, the plan-item
and upgrade markers). It is an HTML comment, so GitHub doesn't render it.

The marker is a new kind, not one of the existing `<!-- shipmill:... -->` markers: a person
posts some of those on purpose (a needs-decision question asked after the bot, D-29's
`close-confirmed`, D-46's plan marker), so their presence can't mean "an agent wrote this".

### `shipmill gh` adds it

`shipmill gh` (`src/shipmill/app_gh.py`, `src/shipmill/cli.py`) adds the marker to every body
it writes, in every mode it writes in: as the App, and as the host's login with `[agents]
identity = "host"` or `--as-host` (spec 037). The session's own text needs no marker, and the
comment templates in the skills stay as they are.

- **Creating a record:** `issue create`, `issue comment`, `pr create`, `pr comment`, `pr
  review`, and `issue close`, `issue reopen`, `pr close`, `pr reopen` with `--comment`/`-c`.
  `shipmill gh` reads the body from `--body`/`-b`, `--body-file`/`-F` (a path, or `-` for
  stdin), or `--comment`/`-c`, and gives gh one `--body` (or `--comment`) in their place: the
  same text, then a blank line and the marker. A body that already carries the marker gets no
  second one. A `pr review` given no body (an `--approve` alone) gets the marker as its body
- **A create it can't mark:** `issue create`, `issue comment`, `pr create`, and `pr comment`
  with no `--body` or `--body-file`, or with `--web`, `--editor`, or `--edit-last`, exit 2
  before gh runs, naming `--body-file`; for `--edit-last`, the message names the `gh api -X
  PATCH repos/<owner>/<repo>/issues/comments/<id>` edit instead
- **Editing a record:** `issue edit` and `pr edit` with a body flag, and `gh api` with `-X
  PATCH` on `repos/<owner>/<repo>/issues/<n>`, `pulls/<n>`, `issues/comments/<id>`,
  `pulls/comments/<id>`, or `pulls/<n>/reviews/<id>` with a `body` field. An edit keeps the
  origin the record was created with: `shipmill gh` first reads the record's current body with
  the same identity, and the new body carries the marker exactly when the current one does.
  So an agent's edit of a person's issue (linking its merged spec, adding a `Depends on` line)
  leaves it the person's, and no edit drops an agent's marker. A current body that can't be
  read exits 2, and the edit doesn't run
- **`gh api` creates:** `-X POST`, or fields with no method, on `repos/<owner>/<repo>/issues`,
  `issues/<n>/comments`, `pulls`, `pulls/<n>/comments`, `pulls/<n>/comments/<id>/replies`, or
  `pulls/<n>/reviews`: the `body` field given with `-f`, `-F`, `--field`, or `--raw-field` (a
  value, or `@<file>` for `-F`) is marked as above, and one holding the marker alone is added
  when none is given. Such a call with `--input` exits 2 before gh runs. `gh api graphql` with
  a mutation that writes a body (`addComment`, `updateIssueComment`, `createIssue`,
  `updateIssue`, `createPullRequest`, `updatePullRequest`, `addPullRequestReview`,
  `submitPullRequestReview`, `updatePullRequestReview`, `addPullRequestReviewComment`,
  `addPullRequestReviewThread`, `addDiscussionComment`, `updateDiscussionComment`,
  `createDiscussion`, `updateDiscussion`) exits 2, naming the REST form
- **Size:** a marked body longer than GitHub's 65,536 characters exits 2 before gh runs,
  rather than letting GitHub cut the marker off
- **Everything else is unchanged:** labels, assignees, merges (spec 049's `--body` is a commit
  message, not a record read as a decision), releases, and every read reach gh exactly as
  today, and the refusals of specs 012, 030, 037, and 049 hold as they are

### shipmill's own writes

`GhCli` in `src/shipmill/github.py` writes issues and comments for the release and operate
workflows (`create_issue`, `update_issue`, `comment_issue`, `close_issue`). Each of those
bodies ends with the marker too, and the body limit its `_fit` applies leaves room for it, so
cutting a long body never drops the marker.

### The skills' scripts write through `shipmill gh`

`gh_writer` in `skills/github-ship-watch/scripts/watch_state.py`, which `chains.py`
(`skills/github-issue-triage/scripts/chains.py`) and `shipped.py`
(`skills/github-pr-triage/scripts/shipped.py`) share, returns the `shipmill gh` command for
every checkout whose `.github/shipmill.toml` has an `[agents]` section, with or without
`app_id`, and plain `gh` only for one without `[agents]`. Without `app_id`, the script's write
then goes as the host's login with the marker when the repo sets `identity = "host"`, and
exits 2 otherwise, as spec 037 and D-54 already have it for the skills themselves.

### The readers

The needs-decision rules in `skills/github-issue-triage/scripts/triage_state.py`, which
`watch_state.py` reads through the same functions:

- **A reply** is a newer comment by an OWNER, MEMBER, or COLLABORATOR other than the
  `--bot-login`, carrying neither the needs-decision marker on its first line nor the agent
  marker. With `--bot-login` that changes nothing, since a person's comment doesn't carry the
  marker and the App's never counted
- **A veto** is a comment by an OWNER, MEMBER, or COLLABORATOR other than the `--bot-login`,
  without the agent marker, whose first word is `veto`
- **A comment whose author GitHub gives as null** (a deleted account) is never a reply and
  never a veto: its origin can't be read, so it counts as an agent's
- The question, the decided and veto-handled markers, and every other reader of trusted
  markers (D-29, the hand-off, verified, check-waiting, and check-failed markers) are
  unchanged: those markers are posted by agents on purpose, and the agent marker beside them
  changes nothing

`src/shipmill/credit.py` (spec 049) applies the same rule to its sources of a person's
decision:

- **An issue's author:** `CLOSES_QUERY` also reads each issue's `body`. An issue the pull
  request closes, or its parent, whose body carries the marker names no decider, whoever its
  author and association; one whose body isn't a string in GitHub's answer names none either,
  and the merge goes on with the other records
- **An answerer:** a reply carrying the marker names no one. The App's `Decision by
  @<login>` relay still names `<login>`: the App's comments carry the marker now, and the relay
  is read by its author and first line, as S-049-4 has it
- **An approver:** a review whose body carries the marker names no one; `credit_reviews` reads
  each review's body for it

`shipmill status` and `shipmill doctor`'s AGENT_AS_PERSON check (`src/shipmill/agent_as_person.py`,
spec 012) counts a body carrying the agent marker as an agent's, beside the markers it reads
today, so an agent record a person's login wrote is flagged by the sign this spec adds.

### The docs

- `skills/github-issue-triage/references/needs-decision.md`: a section on the agent marker,
  saying `shipmill gh` adds it and a session never writes it or removes it; both rows of the
  reply table and the veto rule name it; "Answered in the session" writes the `Decision by
  @<login>, relayed by <agent>` first line in both modes, not only as the App, so D-49's
  relayed answer reads the same without the App. The session removes the `needs-decision`
  label after it posts the relay, as today, which is what moves the item: the relay itself,
  carrying the marker, is no reply
- `skills/github-issue-triage/references/spec-gate.md` ("An issue the maintainer filed") and
  `skills/github-issue-triage/references/triage-rubric.md` (the feature row and "A new
  capability"): an issue whose body carries the agent marker is not the maintainer's filing,
  whatever its author association, and goes the way of any other request
- `docs/flow.md` names the rule in one line where it describes decisions

## Acceptance criteria

- S-050-1: `shipmill gh issue create`, `issue comment`, `pr create`, `pr comment`, `pr review`, and `issue|pr close|reopen --comment`, as the App and as the host's login (`identity = "host"` or `--as-host`), give gh one body flag whose text is the given `--body`, `--body-file <path>`, `--body-file -`, or `--comment` text followed by a blank line and `<!-- shipmill:agent -->` as its last line; a body already carrying the marker reaches gh unchanged, and `pr review --approve` with no body gets the marker alone
- S-050-2: `shipmill gh issue create`, `issue comment`, `pr create`, or `pr comment` with no `--body` or `--body-file`, or with `--web`, `--editor`, or `--edit-last`, exits 2 without running gh, naming `--body-file` (and for `--edit-last` the `gh api -X PATCH .../issues/comments/<id>` form)
- S-050-3: `shipmill gh issue edit`, `pr edit` with a body flag, and `gh api -X PATCH` on an issue, pull request, comment, or review with a `body` field read the record's current body first and give gh the new body with the marker when the current body carries it and without it when it doesn't; when the current body can't be read, they exit 2 and the edit doesn't run
- S-050-4: `shipmill gh api` creating an issue, pull request, comment, review comment, reply, or review on the endpoints the Behaviour lists gives gh the `body` field marked (from `-f`, `-F`, `--field`, `--raw-field`, or `-F body=@<file>`), or a `body` field holding the marker alone when none was given; such a call with `--input`, and `gh api graphql` with any mutation the Behaviour lists, exits 2 without running gh
- S-050-5: A marked body longer than 65,536 characters makes `shipmill gh` exit 2 without running gh, and `GhCli.create_issue`, `update_issue`, `comment_issue`, and `close_issue` in `src/shipmill/github.py` send bodies that end with the marker, a body cut to the limit included
- S-050-6: `shipmill gh` hands gh the arguments of a label, assignee, merge, release, or read command exactly as given, as today
- S-050-7: `gh_writer` in `watch_state.py` returns the `shipmill gh` command for a checkout whose config has `[agents]` with `app_id`, with `identity = "host"`, and with neither, and plain `gh` for one with no config or no `[agents]` section
- S-050-8: Without `--bot-login`, `triage_state.py` reads an issue labelled `needs-decision` as NEEDS_DECISION when every OWNER, MEMBER, or COLLABORATOR comment after its question carries the agent marker, and as DECIDED once a newer one without it comes; `watch_state.py` lists the first in its NEEDS_DECISION row and the second in ISSUES
- S-050-9: With or without `--bot-login`, a comment by an OWNER, MEMBER, or COLLABORATOR whose first word is `veto` and which carries the agent marker leaves a `decided` item out of VETOED, and a comment whose author is null is neither a reply nor a veto
- S-050-10: With `--bot-login`, every reply and veto case `triage_state.py`'s tests read today gives the same state, and a trusted person's comment without the marker after the App's question still reads DECIDED
- S-050-11: With `credit = "decider"`, an issue the pull request closes, or its parent, whose body carries the agent marker names no decider, whatever its author and author association; one whose body isn't a string in the GraphQL answer names none either, and the merge's other deciders are still credited
- S-050-12: With `credit = "decider"`, a reply or an approving review carrying the agent marker names no decider, an App comment whose first line is `Decision by @<login>` still names `<login>` when it carries the marker, and an issue a person filed without the marker still credits its trusted author as S-049-5 says
- S-050-13: AGENT_AS_PERSON in `shipmill doctor` flags an item or comment by a User author whose body carries the agent marker on any line
- S-050-14: `needs-decision.md` names the agent marker in both rows of the reply table and in the veto rule, says `shipmill gh` adds it and a session never writes or removes it, and writes the `Decision by` relay line in both modes; `spec-gate.md` and `triage-rubric.md` say an issue whose body carries the marker is not the maintainer's filing

## Out of scope

- A hook that refuses a session's write which bypasses `shipmill gh` without the App: hooks
  are the `security` zone, and D-54 lets a person's own Claude write as themselves when no App
  is set, so the hook can't tell a skill's write from the person's yet. Until a later spec
  adds one, a session that writes with plain `gh` against the skills' rule writes unmarked
  text; with the App, D-54's hook already refuses that write
- Reading `performed_via_github_app`: with an installation token the author is already the
  App's bot, so it adds no sign today, and whether GitHub sets it on records made with a user
  access token is what #793's spike confirms. The spec that builds on that spike adds it as the
  sign that wins over the marker
- Writing as the person who decided (#793's assisted mode), which this spec unblocks
- A repo whose config has no `[agents]` section: no gate runs there and no session posts a
  needs-decision question (D-21), and its scripts keep plain `gh`
- Label events, such as who added `planned` (S-049-6): they carry no body, so they keep their
  permission rule
- Commit messages, merge bodies, and release notes
- Records written before the build: they carry no marker and read as they do today

## Decisions relied on

- D-14
- D-16
- D-21
- D-49
- D-54
- D-61
- D-62

This spec departs from two approved rules, on purpose: the no-App row of `needs-decision.md`'s
reply table (a newer trusted comment without the needs-decision marker no longer answers when
it carries the agent marker), and S-049-4 and S-049-5, which it narrows to records without the
marker. It also changes the line in spec 037's migration note that the skills' scripts pick
plain `gh` without `app_id`. It supersedes no `D-n`: D-62 records the rule, and it refines D-49
and D-16's reading of replies and vetoes without replacing them.

## Issues

The build issues, filled in once they are filed: one `- owner/repo#N: S-050-1, S-050-2` per
line, naming the criteria that issue delivers. Each criterion belongs to exactly one.

- shipmill/shipmill#797: S-050-1, S-050-2, S-050-4, S-050-5, S-050-6
- shipmill/shipmill#798: S-050-3
- shipmill/shipmill#799: S-050-7
- shipmill/shipmill#800: S-050-8, S-050-9, S-050-10
- shipmill/shipmill#801: S-050-11, S-050-12
- shipmill/shipmill#802: S-050-13, S-050-14

## Verification

Filled in when the spec reaches `built`: one line per criterion id, saying how it was
checked against the default branch (beyond its tests) and the result.
