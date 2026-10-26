# The needs-decision protocol

## Who decides

Every session in a repo whose `.github/shipmill.toml` has `[agents]`, a gate session or not, places each decision before it takes it (spec 030, D-48). A decision falls in one or more **zones**, and each zone has one **level**, set in the config's `[decisions]` section and read from the default branch, never from the change:

| Level | The session |
|---|---|
| `act` | decides and goes on; the commit, the pull request's plan, or the triage comment is the record |
| `notify` | decides, posts the [decided comment](#a-decided-comment) and the `decided` label, and goes on; the maintainer may veto |
| `ask` | asks with this protocol, the [zone line](#the-zone-line) under the marker, and leaves the item until a trusted reply |
| `never` | may prepare the change (a pull request, an issue, a draft) but never takes the decision: never merges, accepts, closes, or answers it, even when the maintainer says yes in chat |

`shipmill decide levels` prints each zone's level, its floor, where the level comes from, and `veto_hours`. The zones:

| Zone | Covers |
|---|---|
| `direction` | an edit of `docs/product.md` or `docs/product/` (D-34) |
| `decision-policy` | the `[decisions]` section of `.github/shipmill.toml`; always `never` |
| `scope` | accepting or declining an opportunity (D-10), approving a spec, accepting a goal plan, creating or editing a milestone |
| `rule-departure` | a change that departs from an active `D-n` or an approved spec's `S-NNN-k` |
| `contract-change` | changing or removing a command, flag, argument, exit code, env var, output or file format, default, limit, public API, or stored state an upgrade reads |
| `contract-addition` | adding one of those while every existing use behaves as before; a new runtime dependency |
| `security` | `.github/**`, a secret or credential, a token's or a workflow's permissions, the delivery hooks' rules, the gate's tool allowlist |
| `protected` | a file a `REVIEW.md` Protected areas glob covers |
| `interpretation` | choosing between readings of an approved spec, a `D-n`, or an issue, where each reading meets the criteria |
| `triage-verdict` | won't fix, duplicate, postpone, or close as done on an issue |
| `implementation` | work order, how a change splits into pull requests, internal design, refactors, tests, docs of existing behaviour |
| `unknown` | a decision no other zone covers |

The release side's zones (`release`, `breaking-release`, `deploy`, `rollback`, `intake`, `upgrade`) take their levels from `[autonomy]` and D-39, and `decide levels` lists them too. Without `[agents]` there are no zones: the skills' own rules (the [design gate](design-gate.md)'s, the [spec gate](spec-gate.md)'s) say when to ask.

### Placing a decision

1. **Code first.** For a change on a branch or a pull request, ask `shipmill decide classify` through the CLI the skill pins, with `--pr <n> --json`, or `--files <path>...` for a change without a pull request (paths alone, so the changelog and spec-status rules don't apply). It reads the levels at `--ref`, `origin/HEAD` by default, so a change that edits `[decisions]` is judged by the levels it would replace. The zones it prints hold, whatever the session thinks of them. Its `candidates` are the `D-n` entries whose "Applies to" covers the change, never zones: read each, and call the change `rule-departure` when it departs from one or you can't tell
2. **Then the model.** For each decision code doesn't see (a verdict, a reading of a spec, a contract addition, a candidate `D-n`), pick its zone from the table. When two zones could fit, pick the one with the stricter level; when none fits, it is `unknown`
3. **The strictest level wins.** A decision in several zones takes the strictest of their levels, in the order `act`, `notify`, `ask`, `never`, and the session follows that level's path:
   - **`act`:** go on. No question, no decided comment
   - **`notify`:** post the [decided comment](#a-decided-comment), add the `decided` label, and go on
   - **`ask`:** post the needs-decision question ([Asking](#asking)) with its [zone line](#the-zone-line), and leave the item
   - **`never`:** prepare what helps (a pull request, an issue with the evidence), assign it to the maintainer, label it `role:maintainer` (a person's item, spec 036; the older `human` label reads the same but isn't written), say in one comment what the maintainer does by hand, and leave it. A reply never moves it: no answer in the session or on GitHub lets the agent take the step. `pr_gate.py` reads such a pull request as MAINTAINER_ONLY (exit 7), which `--maintainer-accepted` doesn't lift, and `shipmill gh pr merge` refuses it with exit 2

A session a person started by hand still asks in the session for `ask`, with AskUserQuestion as usual; `never` holds there too, even when the person says yes.

### The zone line

A needs-decision question carries its zone on its second line; the first line stays the marker the scripts read, and the retro counts the asks per zone from the second:

```markdown
<!-- shipmill:needs-decision -->
<!-- shipmill:zone contract-change -->
@<login> Decision needed: <the question, one sentence>
```

The session that takes up the answer edits that line of the question to `<!-- shipmill:zone contract-change answer=recommended -->`, or `answer=other` when the reply picked another option or its own words.

### A decided comment

A `notify` decision is one comment on the item it belongs to, posted through `--body-file`, and the `decided` label on the item (create the label with `shipmill gh label create decided` when the repo lacks it):

```markdown
<!-- shipmill:decided zone=interpretation until=2026-10-20T14:00:00Z -->
@<login> Decided without waiting: <the decision, one sentence>

Why: <one or two sentences, naming the D-n or S-NNN-k it rests on>
Not taken: <the other option, and what it would have meant for users>

Reply with a comment starting with `veto` before 2026-10-20 14:00 UTC to reverse it, adding what you want instead if you like. A later veto still counts and gets a follow-up.
```

`zone` is the decision's zone id, and `until` the post time plus `veto_hours`, in UTC. `<login>` is the person the gate's prompt names, as for a question, so GitHub notifies them.

- **The work doesn't wait.** The session goes on at once, and a pull request carrying a `notify` decision merges when it is otherwise ready, inside the window too. `pr_gate.py` prints a `notify: <zone>: <reason>` line for one: post the decided comment before the merge, unless one for that zone is already on the pull request
- **A rule goes to the log.** When the decision sets something later work must respect (a format for a new output, a reading of a criterion the next pull request relies on), also record it with `decisions.py add --zone <id>`, which writes its `- Zone: <id> (notify, veto until <until>)` line; one decisions pull request per pass still holds ([design-gate.md](design-gate.md#recording-a-decision)). A decision that sets no rule is recorded by the comment alone

### Taking up a veto

A veto is a comment newer than the decided marker, by an OWNER, MEMBER, or COLLABORATOR other than the App, whose first word is `veto` in any case; an outsider's comment, or a `veto` in the middle of a comment, never counts (D-16). `triage_state.py` reads such an item as VETOED until a newer `<!-- shipmill:veto-handled ... -->` comment by the App answers it, closed issues of the last 14 days included, and `watch_state.py` lists it in its VETOED row, which starts a session. That session:

1. Reads the veto. When it says what to do instead, that is the maintainer's decision: do it. When it doesn't, the decision moves to `ask`: post the needs-decision question with the options, the vetoed one last
2. Undoes what it can. Not landed (a pull request or an issue still open): revise or close the pull request, restore the issue's labels. Landed: open a revert pull request for a merged change (`implementation`, its plan citing the veto), reopen a closed issue. A published release is never unpublished: file a follow-up issue to fix forward
3. Supersedes the `D-n` the decision recorded, if any, with `decisions.py add --supersedes`, the veto's comment as the source
4. Posts `<!-- shipmill:veto-handled zone=<id> -->` as the first line of a comment saying what it did, and removes the `decided` label. Without a veto the label stays, as the record the retro counts

## Gate sessions

A session the shipmill gate started can't count on an answer in the session: it runs in the background, and nobody may attach. So every question a gate session asks goes to GitHub first, interactive or headless (D-21), and the item waits there while the rest of the repo keeps moving (spec S-005, D-17).

A session is a **gate session** when its prompt carries one of the gate's paragraphs:

- **`Gate session:`** an interactive session (`claude --bg`). Post the question with this protocol, then ask the same question in the session with AskUserQuestion too
- **`Headless:`** a headless session (`claude -p`), or any session where AskUserQuestion is unavailable. Nobody answers AskUserQuestion or a permission prompt: post the question with this protocol and leave the item

A session the user started by hand, whose prompt carries neither paragraph, asks with AskUserQuestion as usual and posts no marker or label.

Every place github-issue-triage, github-issue-resolve, and github-pr-triage would ask the user (triage's design-gate questions and a PR's "decisions for you", resolve's product decisions and spec departures, pr-triage's denied action and a departure from a `D-n`) follows this protocol in a gate session, before anything else.

**Who does a step is not a question.** A step only a person can do goes to a role ([triage-rubric.md](triage-rubric.md), A person's item): its issue is labelled `role:<name>` and assigned the role's users at once ([spec-gate.md](spec-gate.md), A step only a person can do). A role nobody fills, or one `[agents.roles]` doesn't define, falls back to the maintainer: the users `[agents.roles] maintainer` lists, or with none the host's `gh` login. An unassigned item reads ASSIGN_DUE, and with the `--role` flags never NO_ASSIGNEE, so no session asks who does it. A team is mentioned in the hand-off, never assigned. Only an assignment GitHub refuses comes here: a question naming the users it couldn't assign and GitHub's message, with assigning the maintainer recommended.

## Asking

1. Post one comment on the issue or pull request the decision belongs to, through `--body-file` (never an inline `--body`):

   ```markdown
   <!-- shipmill:needs-decision -->
   @<login> Decision needed: <the question, one sentence>

   1. <option> (recommended): <why>
   2. <option>: <what it costs>

   Reply here with a number or your own answer; shipmill takes this up on the tick after your reply.
   ```

   The marker is the comment's first line, with or without an App: it is how `triage_state.py` and `watch_state.py` tell the question from the reply when the session posts as the maintainer. `<login>` is the person the gate's prompt names (the host's `gh` login). Put the recommendation first, and say in each option what it means for users and what it costs, in words a user of the tool knows. Name `D-n` entries and `S-NNN-k` criteria when the question is a departure from one. With `[agents]` in the config, the question's zone goes on the second line, right under the marker ([The zone line](#the-zone-line))
2. Add the `needs-decision` label to the item: `gh issue edit <n> --add-label needs-decision` (or `gh pr edit`). From now on the scripts read the item as waiting, not as work, so the gate doesn't start a session for it again
3. **Interactive (`Gate session:`) only:** ask the same question, with the same options in the same order, with AskUserQuestion. An answer in the session: follow [Answered in the session](#answered-in-the-session). No answer: the item already waits on GitHub, and the gate's `max_wait_minutes` stops the waiting session (D-15); whoever answers on GitHub later is read as below
4. **Headless:** Leave the item: don't build, push, merge, or comment on it further in this session. Go on with the other items, and report this one under the decisions you left

A triage verdict that waits on a decision says so in its first line ("Waits on your decision below") and leaves the **Decision needed** block out: the block is this comment, posted right after the verdict, since a comment can't start with both `Triage:` and the marker.

## Answered in the session

An interactive gate session that gets the answer through AskUserQuestion puts the record on GitHub before it acts, so the item doesn't wait on a question already answered and the thread shows who decided:

1. Post the answer on the item as a comment without the marker, through `--body-file`. Posted as the App (`shipmill gh` with `[agents] app_id` set), its first line names who decided and who relayed it, so the thread tells a person's decision from agent text:

   ```markdown
   Decision by @<login>, relayed by <agent>

   Answered in the session: <the option or the user's own words>
   ```

   `<login>` is the person who answered, `<agent>` the tool that relays it (`Claude Code`)
2. Remove the `needs-decision` label: `gh issue edit <n> --remove-label needs-decision` (or `gh pr edit`)
3. Record the answer with `decisions.py add` when it sets a rule, as the [design gate](design-gate.md) says, and go on

## A denied tool call is a decision

A headless session runs with an allowlist of tools and can't prompt for more, so Claude Code denies a call outside it.

**One allowlisted command per Bash call.** Claude Code checks each part of a compound command on its own, and one part that isn't on the list denies the whole call, which reads like "Bash was denied". So a headless session runs one command per Bash call: `git -C <dir> ...`, not `cd <dir> && ...`; no variable assignments, no `;` or `&&` chains, and no pipes into tools that aren't on the list (use `gh --jq` and the Read and Grep tools instead). When a denied call chained commands and every command the step needs is on the list, rerun them as separate calls: that isn't routing around the list, since each call passes it on its own.

A command that isn't on the list is different. Don't retry it in another form or route around it. Treat the denial as a decision for the user: post the comment above on the item you were working on, naming the tool and the command you tried, with the options (widen the gate's allowlist with `--claude-arg=--allowedTools --claude-arg "<tool>"` on `shipmill gate` or `shipmill launchd`, or do that step by hand), add the label, and leave the item. The allowlist grows from these comments, in review, instead of from guesses.

## While it waits

The scripts read a labelled item as waiting, not as work: `triage_state.py` reports it as NEEDS_DECISION (no action, so it doesn't make the script exit 1), and `watch_state.py` leaves it out of ISSUES and PRS_OPEN and lists it as `#N` in its NEEDS_DECISION row, which starts no session. It waits until a reply comes:

| | The question | A reply |
|---|---|---|
| With `--bot-login` (the gate's App, spec 004) | The newest comment by that login whose first line is the marker | A newer comment by an OWNER, MEMBER, or COLLABORATOR other than that login, without the marker |
| Without it | The newest comment whose first line is the marker, by an OWNER, MEMBER, or COLLABORATOR | A newer comment by an OWNER, MEMBER, or COLLABORATOR without the marker |

A marker comment from any other author never counts, so an outsider can't re-park an answered item, and with `--bot-login` the bot's comment without the marker (a triage comment) is no question. With `--bot-login`, when an OWNER, MEMBER, or COLLABORATOR posts a marker comment after the bot's, the person asked after the bot did, and the item reads as labelled with no question. A comment from any other author association never counts as a reply, so an outsider can't wake an item. A labelled item with no question waits until a person takes the label off: someone parked it on purpose.

## Taking up an answered item

Once a trusted person replies, `triage_state.py` reads an issue as DECIDED, an action read before any other state, so `watch_state.py` lists it in ISSUES and the gate starts a session on the next tick, whatever the reply links. A pull request reads as open work again (PRS_OPEN). Once the label is off, the item reads its usual state (NEW, NEEDS_PR, UNBLOCKED, and so on). The session that takes it up:

1. Reads the reply. A reply that answers none of the options, or asks something back, is a new question: ask again with this protocol
2. Removes the `needs-decision` label before it acts on the answer: `gh issue edit <n> --remove-label needs-decision` (or `gh pr edit`)
3. Records the answer with `decisions.py add` when it sets a rule, as the [design gate](design-gate.md) says, and goes on

On a spec PR, a trusted answer that takes every recommendation unchanged is the spec's approval: the session lands the spec PR through github-pr-triage once it is mergeable and green, rather than leaving the merge to the maintainer, who may still merge it by hand; an answer that changes a recommendation revises the spec and asks again, and a spec PR that edits `docs/product.md` stays the maintainer's to merge (D-49, D-34, [spec-gate.md](spec-gate.md#approved-by-an-answer)).
