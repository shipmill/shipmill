# Triage rubric

## Verdicts

| Verdict | When | Comment says |
|---|---|---|
| **implement** | A confirmed bug; or behaviour the docs already promise but the code breaks; or a small additive feature that fits the release phase | The plan in 2 to 4 bullets; "I'll link the PR here" |
| **opportunity** | A user's request for a new capability (a new command, layer, or workflow) that no accepted opportunity covers yet. Product intake groups it with the requests for the same outcome, and the maintainer accepts or declines the group (D-10); triage doesn't group or write a spec for it | That it goes to product intake, and what happens there ([comments.md](comments.md), Opportunity) |
| **feature** | New behaviour beyond a bug fix or a contract tweak (a new command, layer, or workflow) that fits the release phase, and that the maintainer already wants: an accepted opportunity (labelled `planned`), a request an accepted opportunity covers, or an issue the maintainer filed (one whose body carries the agent marker `<!-- shipmill:agent -->` is not the maintainer's filing, whatever its author association). A small additive feature such as a new flag stays **implement**, through the design gate | The spec PR's link and a hold line naming it; implementers start once it merges ([spec-gate.md](spec-gate.md)) |
| **postpone** | A new capability, a new wire contract, or a design that must land with sibling issues; or a feature that serves no goal of the direction ([below](#the-direction-the-goal-it-serves)) | Why now is the wrong time, the plan, and what it waits on; for no goal, the goal it would need. Add the `postponed` label |
| **clarify** | You can't reproduce it, or it needs a product or spec decision | The exact question, with options and your recommendation |
| **duplicate** | Same root cause as another issue | A link; close it |
| **won't fix** | It works as intended, or it conflicts with the project's principles, or it hits a non-goal of the direction (`N-n`) | Evidence from the code or docs, or the non-goal it hits; close it |

## The direction: the goal it serves

When the default branch has `docs/product.md` (D-34, spec 024), new behaviour is judged against it. Read only the sections each step needs, from the checkout after `git fetch`, each as `uvx shipmill==0.100.2 product show ...`, the release this plugin pins, in every session:

| Step | Sections | Read them with |
|---|---|---|
| Verdicts | Goals, Non-goals | `shipmill product show --section goals` and `--section non-goals` |
| The spec gate | Users, Goals | `shipmill product show --section users` and `--section goals` |

Every verdict on an issue that asks for new behaviour (a small additive feature under **implement**, a **feature**, an **opportunity**) names the goal it serves in the comment's verdict line, `Serves: G-n` ([comments.md](comments.md)), or the non-goal it hits:

- **It hits a non-goal:** **won't fix**, citing `N-n` and the non-goal's words. A request the maintainer wants anyway changes the direction first, which only the maintainer does
- **It serves no goal:** a **feature** (new behaviour the maintainer already wants) gets **postpone**, saying which goal it would need; the maintainer adds the goal to the direction or lets it wait
- **A user's request that serves no goal** still gets **opportunity** and goes to product intake: its verdict line says it serves no goal, the opportunity issue says so too, and the maintainer accepts or declines it there (D-10)
- **A bug fix or a contract tweak** serves the quality bar and needs no goal: its verdict names none, and nothing here holds it

A repo without `docs/product.md` keeps the verdicts above as they are, with no `Serves:` line. `shipmill product show` exits 2 on a direction that breaks its grammar: give no verdict on new behaviour until the maintainer fixes it, name the problem in the report, and go on with the bug fixes.

A reporter's open questions get answers in the comment. If the code can settle one, investigate: "does a library WARNING bypass redaction via `logging.lastResort`?" was answerable with a probe, and the answer was yes.

## A new capability: opportunity or feature

Bugs, contract tweaks, and small additive features keep their verdicts. For a request for a new capability, read who wants it before writing a spec:

1. **An accepted opportunity covers it** (an issue labelled `opportunity` and `planned` whose outcome is the request's): the verdict is **feature**. The spec is the opportunity's: run the spec gate on the opportunity issue if triage hasn't yet, add the request to the opportunity's Evidence section, and hold the request on the opportunity issue ([comments.md](comments.md), Feature, covered by an opportunity)
2. **The issue is an accepted opportunity**, or the maintainer filed it (`gh api repos/<owner>/<repo>/issues/<n> -q .author_association` says OWNER, MEMBER, or COLLABORATOR): **feature**, through the spec gate. The maintainer's own issue is already their decision. An issue whose body carries the agent marker (`<!-- shipmill:agent -->` on any line, which `shipmill gh` adds) is not the maintainer's filing, whatever its author association: an agent wrote it, so unless it is an accepted opportunity it goes to step 3
3. **Anything else**, an open or declined opportunity's outcome included: **opportunity**. Intake adds it to the matching opportunity or opens a new one, and records a decline's reason on it; the maintainer's accept is what makes it a feature

`intake_state.py <owner/repo>` (product-intake's script) lists the opportunities and which are ACCEPTED; read the open and planned ones before deciding.

## The release phase sets the bar

Read it from the tags and the manifest version.

- **Pre-1.0 or active development:** implement most confirmed requests.
- **A release candidate, or a breaking release waiting for the maintainer:** implement bugs, broken promises, security or privacy fixes, and small additive features a consumer port needs now. Postpone new wire contracts, new commands, and designs spanning several issues. A behaviour change is acceptable only if it's small and is listed under Breaking.
- **Stable:** anything breaking waits for a major version. Implement it behind a new option, or postpone it.

## Verify before deciding

1. Open the cited files on `origin/<default>`, not on the commit the issue names.
2. Reproduce the issue with its own snippet. Record the actual output.
3. Grep the default branch's CHANGELOG `Unreleased` section and recent commits (`git log --oneline -30`) for work on the same symptom. Main may already handle it:
   - fully: comment and close
   - partly: implement only the remainder, and say so
   - differently: keep main's design and graft onto it. An exit code main already had replaced the one a PR invented
4. For a test flake, read the code under test before calling it a test problem. A heartbeat burst and a Windows replace-versus-read race were both real bugs.

## Grouping and splitting

- **One mechanism, several issues:** decide on it once and comment the same plan on each issue. For example, `env=` aliases for both flags and settings, or a data-only output, line-mode stdin, and typed stdin records.
- **Small part, big part:** ship the small part now, and postpone the rest. For example, an unsupported annotation raising `RegistrationError` now, with typed lists of objects later.
- **Spec-governed behaviour:** when the fix would depart from a spec the project implements (a default value, a required field), the verdict is **clarify**. File an upstream report in this repo with the requirement IDs, the exact numbers, and a proposal ([comments.md](comments.md), Upstream report), and hold the issue on it; never file an issue in the spec's repo.

## Links between issues

An issue waits on another in either of two forms, and `triage_state.py` reads them as one set, in any repo:

- **Text:** a body line `Depends on owner/repo#N` (or `#N` in the same repo), read once the issue is triaged. Any reader sees it, and a forge without issue relations still holds on it. Its strict shape (spec 041) is `Depends on[:] <ref>[, <ref> and <ref>...] [<note>]`: references (`owner/repo#N`, an issue or pull URL, `#N`, or a `#{key}` placeholder) separated by `,`, `and`, or spaces, then an optional note after ` (`, `;`, or ` — `, whose references hold nothing. Context goes on its own line, never on a Depends on line: a line that names a reference among other words reads MALFORMED_DEPENDS. A Depends on line inside a ``` or ~~~ fence holds nothing
- **Native:** an issue GitHub records it blocked by (`blockedBy`), or a sub-issue. The note marks a hold only GitHub records `(native)` and a sub-issue `(child)`, such as `o/r#12:open(child)`; a parent's note starts with `children K/N closed`. Where the forge can't read them, the script holds on text alone and prints one `note: native relations unavailable:` line

Write a link with `chains.py link`, which writes both forms at once: `chains.py link <owner/repo#N> --blocked-by <owner/repo#M>` (N waits on M) or `chains.py link <owner/repo#P> --child <owner/repo#C>` (C under P, and P waits on it). Run again, it prints `already linked` and changes nothing; when the forge refuses the relation (no dependencies or sub-issues there, a cross-owner link) it still writes the line and prints `text only: <error>`. It exits 2 naming the reference for a malformed one, a missing issue, a pull request, or an issue linked to itself, and, before any write, with `closes a cycle:` and the loop for a link whose other end already waits on this issue through open holds. Run from a checkout whose config sets `[agents] app_id`, it writes through `shipmill gh` as the App and exits 2 with `shipmill gh`'s message when that fails. A relation someone set in the UI holds as it is: don't copy it into text.

**In a component** (its config sets `[product] home`), an item waits only on items in the same repo, and `chains.py link` exits 2, before any write, for a reference to another repo (D-47). Write a dependency on another repo as a stand-in instead of a direct `Depends on owner/repo#N` line: an issue in this repo labelled `upstream`, saying what work it needs, with a `Stands in for owner/repo#N` line when the other repo's issue already exists ([comments.md](comments.md), Upstream report). Hold the waiting issue on the stand-in with `chains.py link <owner/repo#N> --blocked-by <owner/repo#S>`; the product's coordinator routes it and closes it once the other repo's work is done (SKILL.md, Reports from other repos). Outside a product, a hold on another repo is written as above.

## A person's item

Label an issue `role:<name>` when only a person can do it: a server change, a key rotation, a payment, a step that needs a secret. The role is whoever fills it: one person, several, or a team. Pick the role and assign its users at once, as [spec-gate.md](spec-gate.md) says (A step only a person can do), and give the issue a `## Check` section: a command or a URL, and what it must return. Its assignees need not be collaborators; a session acts on the trusted author's `## Check`, never on a report's text. It counts as triaged from the start, so its holds apply with no triage comment, no implementer is dispatched for it, and `--wip` never counts it.

An issue labelled `human`, the label before roles (spec 017), is a person's item too and counts as `role:maintainer`. Nothing relabels it; a session reads `human` and never writes it on a new item. Label names are compared case-insensitively.

**Roles.** `[agents.roles]` in `.github/shipmill.toml` lists who fills each role: GitHub logins, and teams as `@<org>/<team-slug>` (shipmill-setup's SKILL.md). `shipmill roles`, run through the CLI the skill pins, prints them resolved, `maintainer` first, and `roles --flags` prints them as the `--role NAME=FILLER[,FILLER...]` flags `triage_state.py` takes, one per role. The gate passes those flags on every state read, and its prompt tells the session to pass the same flags when it reads the state again: do so, every read.

- **The maintainer fallback:** the maintainer is the users and teams `[agents.roles] maintainer` lists, or with nobody listed the host's `gh` login (`gh api user`), the person a needs-decision question mentions. A role set to `[]` resolves to the maintainer's fillers, and `shipmill roles` marks it `fallback`
- **An item's roles:** its `role:<name>` labels, `human` as `role:maintainer`. A label naming a role no `--role` flag gives resolves to the maintainer's fillers, and the note says `role:<name> undefined`. Several role labels resolve to the union of their fillers
- **Users are assigned, teams are mentioned:** GitHub can't assign a team, so a team never becomes an assignee; the hand-off mentions it. A role filled by teams only is labelled and left unassigned, and its item goes from its holds straight to HANDOFF_DUE
- **Assignees win:** once an item has assignees, they do it, whatever its roles say; a person chose them, and nothing reassigns it

`triage_state.py` reads it, after UNTRUSTED, UPSTREAM, NEEDS_DECISION, DECIDED, VETOED, and OFF_MILESTONE, as:

| State | Means | The session |
|---|---|---|
| ASSIGN_DUE | With the `--role` flags: no assignee, and its roles resolve to at least one user. Read while a hold is still open too, so the step is its people's the moment it is filed or labelled. Its note reads `assign @a @b (role:infra)`, and its `--json` line has an `assign` list | Assigns those users, with no comment: `gh issue edit <n> --add-assignee <a>,<b>`. When GitHub refuses the assignment, or the item still reads ASSIGN_DUE on the next read, ask the maintainer through the [needs-decision protocol](needs-decision.md) who does it instead (D-21) |
| NO_ASSIGNEE | No assignee, and the state was read without the `--role` flags (an older gate, or a read by hand) | Asks nobody: reads the state again with the flags `shipmill roles --flags` prints, where the item reads ASSIGN_DUE or goes on to its holds. With the flags, NO_ASSIGNEE is never read, so a session never asks who does a step. When `shipmill roles` exits 2, report what it names and leave the item |
| BLOCKED | A hold is still open, as for any issue | Nothing |
| HANDOFF_DUE | Every hold closed (or it never had one), and no hand-off came after the newest close | Posts the hand-off ([comments.md](comments.md), A person's item), mentioning every assignee and every team its roles resolve to: GitHub's mention is the notification. The note reads `for @a @example-org/legal`, and with the flags its `--json` line has an `assignees` list (empty for a team-only role's item) and a `teams` list |
| WITH_PERSON | A hand-off came after the newest hold closed, and no done report after it | Nothing, however old: one mention per unblock, no reminders. github-ship-watch lists it with the assignees and teams it waits on |
| VERIFY_DUE | A done report came after the newest hand-off | Runs the `## Check`. It holds: a comment with what was checked and what came back, then close the issue as completed, which unblocks what it held. It fails: a new hand-off saying what failed and what came back, so it reads WITH_PERSON again. No `## Check`: close it on the report, saying so |
| VERIFY_CLOSED | Closed as completed by someone other than the `--bot-login`, with a `## Check`, and no verified comment after the close | Runs the `## Check`. It holds: the verified comment. It fails: reopen the issue with a hand-off saying what failed, and everything it held reads BLOCKED again |

A hand-off is a comment whose first line is `<!-- shipmill:handoff -->`, and a verified comment one whose first line is `<!-- shipmill:verified -->`; each counts only from the `--bot-login` or an OWNER, MEMBER, or COLLABORATOR (D-16). A done report is a comment whose first line starts with `done`, in any case, by an assignee or a trusted author.

A check the session's tools can't run (a host it can't reach, a command outside a headless session's allowlist) goes to the maintainer through the [needs-decision protocol](needs-decision.md), with two options: "close it on the report" and "it isn't done". Never close a person's item on a check that didn't run without that answer.

## A parent's check

A parent (an issue with sub-issues that isn't a person's item) may carry a `## Check` section in its body, read as a person's item's is: a command or a URL and what it must return, saying what must hold in production and how to see it (spec 042). A parent without one reads as before: UNBLOCKED once its last child closes, and the session closes it ([comments.md](comments.md), A parent's close). A feature issue gets one from the spec gate when its build deploys ([spec-gate.md](spec-gate.md), Split it into build issues).

`triage_state.py` reads a parent with a check, where it would read UNBLOCKED, as:

| State | Means | The session |
|---|---|---|
| VERIFY_DUE | Every hold closed, and no check-failed comment came after the newest close. Its note starts `children K/N closed`, then each hold, and ends `run its ## Check` | Runs the check (below) |
| CHECK_FAILED | Every hold closed, and a check-failed comment came after the newest close. Its note starts `check failed <date>`, then the progress and the holds | Files the fix as a new child (below) |
| WITH_PERSON | Every hold closed, and a check-waiting comment came after the newest close, with no check-failed or verified comment after it. Its note starts `check waiting on @login since <date>`, then the progress and the holds | Nothing: a person runs the check by hand (below). Not an action |
| VERIFY_CLOSED | Closed as completed by a pull request, a commit, or the `--bot-login`, with no verified comment after its last close (read with `--closed N`). Its note reads `closed by #N`, `closed by commit <sha>`, or `closed by @<login>`, then `run its ## Check` | Runs the check (below) on the closed parent. It never reads SUSPECT_CLOSE |

A check-failed comment is a comment whose first line is `<!-- shipmill:check-failed -->`, a check-waiting comment one whose first line is `<!-- shipmill:check-waiting -->`, and a verified comment one whose first line is `<!-- shipmill:verified -->`; each counts only from the `--bot-login` or an OWNER, MEMBER, or COLLABORATOR (D-16). The newest close is the latest close among the parent's holds, children and `Depends on` lines alike, so a fix child that closes after the check-failed comment makes the parent read VERIFY_DUE again. While a hold is open the parent reads BLOCKED, with or without a check. A person's item with sub-issues stays a person's item (above), and an `upstream` report reads UPSTREAM here: its check is the coordinator's (SKILL.md, Reports from other repos). A parent closed by hand by a trusted person other than the `--bot-login` is that person's call and reads as any other close.

The session runs the check:

- **It holds:** close the parent as completed (`gh issue close <n> --reason completed`), then post the verified comment ([comments.md](comments.md), A parent's check) with the check that ran, what came back, and each child and how it closed. It goes after the close, so `triage_state.py` dates it there and the parent doesn't read VERIFY_CLOSED. A feature issue first gets its spec verified ([spec-gate.md](spec-gate.md), Verify the whole spec). On VERIFY_CLOSED the parent is closed already: post the verified comment alone
- **It fails:** post the check-failed comment with the check, what came back, and what it must return; on VERIFY_CLOSED, reopen the parent first (`gh issue reopen <n>`). The parent then reads CHECK_FAILED
- **The change hasn't reached production yet** (the deploy run for the merge is still going, or the version served predates the merge): no comment and no close. It isn't a failure; the parent reads the same on the next read
- **The session can't run it** (a production log, a dashboard, a host it can't reach, a command outside a headless session's allowlist): a question through the [needs-decision protocol](needs-decision.md) (D-21) on the parent, saying what the check is and why it can't run here, with two options: "leave it open: I check it and close it by hand" (recommended when nothing else shows the result) and "close it unchecked". The parent reads NEEDS_DECISION until the answer. Never close a parent on a check that didn't run without that answer
- **Never a write to production.** A check only reads: it runs a command or opens a URL and compares what comes back. A check that needs a deploy, a rollback, a data change, or any other write is one the session can't run, so it goes to the maintainer as above. shipmill decides and verifies; the platform executes (D-31)

On CHECK_FAILED, file the fix as a new issue in the parent's repo, naming the parent, the check, and what came back ([comments.md](comments.md), A parent's check), triage it **implement**, and make it a child: `chains.py link <owner/repo#parent> --child <owner/repo#fix>`. The parent then reads BLOCKED on the fix, and VERIFY_DUE again once it closes. When you can't tell what the fix is, ask on the parent through the needs-decision protocol instead. A failure reopens no child: the children stay closed, and the fix is new work.

Taking up the answer ([needs-decision.md](needs-decision.md), Taking up an answered item): on "close it unchecked", close the parent as completed, then post the verified comment saying no check ran and who decided, which ends the state; on "leave it open", post the check-waiting comment naming who answered ([comments.md](comments.md), A parent's check): the parent then reads WITH_PERSON, which needs nothing, while that person checks it and closes it by hand. A child that closes after it, or a check-failed or verified comment after it, ends the wait.

## Flags from `triage_state.py`

| Flag | Act |
|---|---|
| NEW | Triage it |
| NEEDS_PR | Dispatch an implementer, or explain on the issue why the plan changed |
| IN_PROGRESS | Nothing, unless the PR stalled |
| DONE_NOT_CLOSED | Close it and cite the merged PR |
| SUSPECT_CLOSE | Check the fix is on the default branch. If it isn't, reopen and explain; if the close is right, post the close-confirmed comment (comments.md, Follow-ups) |
| BLOCKED | Nothing, until the upstream issue closes or the spec PR merges. In a component, a note ending `the coordinator's hold on the home <owner/home>: waits for the coordinator, ask nobody` is a hold on a home item this session can't read: leave it and ask nobody, never a needs-decision question about whether it merged (D-60) |
| UPSTREAM | Nothing: an upstream report waits outside, for the coordinator its note names or, with `no coordinator`, the maintainer, who closes it with what changed |
| OFF_MILESTONE | A build issue isn't in its feature issue's milestone (spec 022): set its milestone to the parent's, as the note names it |
| UNFILLED | A `Depends on #{Bk}` placeholder from `specs.py split` was never filled in: edit the issue body to name the dependency's number |
| MALFORMED_DEPENDS | A `Depends on` line its note names (`line <n>: <the line>`) carries other words beside its references, so it holds on all of them until fixed. Rewrite it in the body as the App: one strict `Depends on` line naming the references you read as the author's dependencies, and the rest of the old line on a line of its own after it. Which references are holds is an `interpretation` decision ([Who decides](needs-decision.md#who-decides)): at `notify`, post the decided marker naming the old and the new line; a veto puts the old line back |
| CYCLE | It is on a cycle of the repo's open issues, each holding the next, so none can start; its note starts `cycle <loop>`, such as `cycle o/r#3 -> o/r#5 -> o/r#3`. On the loop's first item, ask the maintainer which link is wrong through the [needs-decision protocol](needs-decision.md) (D-21), one option per link of the loop, your recommendation first with its reason ([comments.md](comments.md), A cycle). Once it reads DECIDED, remove both forms of the chosen link as the App, the body's `Depends on` line and the native relation (GraphQL `removeBlockedBy` or `removeSubIssue`), then remove the label. The other items on the loop read BLOCKED with `cycle <loop> waits on owner/repo#N` while the question waits: nothing to do for them |
| SPEC_REFUSED | The spec PR it waits on closed without merging: the spec was refused. Decide again in a new triage comment: revise the spec in a new PR (with a new hold line), postpone, or won't fix |
| UNBLOCKED | Read the upstream outcome, update the plan on the issue, then resume. A dependency noted `:not_planned` was closed without its work: decide again whether the issue still stands. A parent whose holds are only its children (each noted `(child)`) is done: close it with a comment listing each child and how it closed ([comments.md](comments.md), A parent's close); a feature issue first gets its spec verified ([spec-gate.md](spec-gate.md), Verify the whole spec). A parent with a `## Check` never reads UNBLOCKED: it reads VERIFY_DUE ([A parent's check](#a-parents-check)) |
| ASSIGN_DUE | A person's item nobody is assigned to, read with the `--role` flags: assign the users its note names, with no comment (above) |
| NO_ASSIGNEE | A person's item nobody is assigned to, read without the `--role` flags: read the state again with `shipmill roles --flags`, never ask who does it (above) |
| HANDOFF_DUE | A person's item whose holds all closed: post the hand-off to its assignees and its roles' teams (above) |
| WITH_PERSON | Nothing: it waits on its assignees, however long. Never mention them again. A parent (its note starts `check waiting on @login`): it waits on that person to run its `## Check` by hand ([A parent's check](#a-parents-check)) |
| VERIFY_DUE | A person's item: a done report came after the hand-off, run the `## Check` (above). A parent (its note starts `children K/N closed`): its holds all closed, run its `## Check` ([A parent's check](#a-parents-check)) |
| CHECK_FAILED | A parent's check failed after its newest close: file the fix as a new child with `chains.py link <owner/repo#parent> --child <owner/repo#fix>` ([A parent's check](#a-parents-check)) |
| VERIFY_CLOSED | A person closed their item by hand, or a parent closed before its check ran: run its `## Check` (above, and [A parent's check](#a-parents-check)) |
| DECIDED | A trusted person answered its needs-decision question: read the reply, remove the `needs-decision` label, and act on it ([needs-decision.md](needs-decision.md), Taking up an answered item). With its note ending "relayed", the answer is the App's relay of a session's answer and the label is off already: act on the relay, then post the triage comment for the answer, which ends the state |
| VETOED | A trusted person vetoed a decision an agent took at `notify` (spec 030), on an open issue or one closed in the last 14 days: take the veto up as SKILL.md's VETOED step says, ending with the `<!-- shipmill:veto-handled zone=<id> -->` comment and the `decided` label removed |
| POSTPONED | Skip it |
| REVISIT | A stable release came out after it was postponed. Apply this rubric again under the new phase |
