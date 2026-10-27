---
name: product-intake
description: Turn a GitHub repo's product feedback into opportunity issues the maintainer accepts or declines. Groups feature requests, ideas, and discussions that ask for the same outcome (with thumbs-up reactions as demand) into one opportunity issue each, keeps it updated instead of opening a second, records a decline so the same request is never proposed again, takes the requests triage hands over, and hands an accepted opportunity back to github-issue-triage's spec gate. Also proposes a plan of work for a goal of the repo's direction and, once the maintainer accepts it, files its items. Use when the user asks to "group the feature requests", "run product intake", "what are users asking for", "turn feedback into opportunities", or "what should we build next". Not for bugs or contract changes (github-issue-triage) or for releases (github-ship-watch).
---

# Product Intake

Feedback in, opportunities out. Many requests ask for one outcome in different words; intake groups them into one **opportunity issue** that states the problem in the users' words, who it affects, the evidence, and what success looks like. The maintainer decides on the opportunity, not on each request: accept (label `planned`) or decline (close as not planned, with the reason in a comment). Nothing is built from an opportunity until it is accepted and its spec merges. Milestones are the maintainer's own list of what a version must hold (D-32): intake never proposes, ranks, or creates one, save the milestone an accepted goal plan names (D-38).

A goal of `docs/product.md` that nothing serves gets a **plan issue**: the work that reaches it, which the maintainer accepts, declines, or asks to edit in a reply ([Plan a goal](#6-plan-a-goal)).

## Inputs

- Repo `owner/name` and a local checkout (for the config and the decisions log)
- Scope from the user's wording, read narrowly:
  - "status" or "what are users asking for": report only, change nothing
  - "intake" (the default): the report, plus the writes `[autonomy] intake` allows
  - "intake and triage": also hand ACCEPTED opportunities to github-issue-triage

## Autonomy

`[autonomy] intake` in `.github/shipmill.toml` sets how far a pass goes; the script prints it on its first line:

| Level | A pass |
|---|---|
| `observe` | Reports the groups it would make, and each PLAN_DUE goal with the plan's proposed text, and writes nothing: no plan issue, no comment, no filed item |
| `propose` (the default) | Opens and updates opportunity issues, comments on the requests it groups, and labels pure duplicates; opens plan issues and, once the maintainer accepts one, files its items |

There is no `act`: shipmill refuses it, since an opportunity is a proposal by nature and only the maintainer accepts or declines one. An open `shipmill-hold` changes nothing here, as intake never acts.

## Hard rules

1. **Grouping is judgment; the states are facts.** `scripts/intake_state.py` says what is grouped and where each opportunity stands. Which requests ask for the same outcome is your call, made from the requests' own words
2. **One opportunity per outcome, updated in place.** Before opening one, read every opportunity the script lists, open and closed. A request that fits an existing one is added to its Evidence section; never open a second issue for the same outcome
3. **A declined outcome is never proposed again.** A new request for a declined outcome goes into the declined opportunity's Evidence section, and the request gets a comment with the recorded reason. Don't reopen it and don't open a new one: reconsidering is the maintainer's call, made by reopening the issue themselves
4. **Never accept, decline, or close for the maintainer.** Intake writes opportunities and comments; the `planned` label and the close are the maintainer's. Accepting or declining is the `scope` zone, whose floor is `ask` ([Who decides](../github-issue-triage/references/needs-decision.md#who-decides)). Don't close requests either, a pure duplicate included: it gets the `duplicate` label and a link
5. **Bugs and contract changes aren't feedback.** The script already leaves out issues triage gave an implement, feature, duplicate, or won't fix verdict. If an untriaged issue is a bug, leave it to github-issue-triage rather than grouping it. A request triage handed over with its **opportunity** verdict is feedback: group it like any other
6. **GitHub data only** (D-6's spirit): issues, discussions, and reactions. No external tracker, survey, or analytics source
7. **Write as the App when the repo has one.** When `.github/shipmill.toml` sets `[agents] app_id`, every `gh` call that writes (an issue, a comment, a label, a pull request, a review, a merge, a release) runs as `shipmill gh <the same arguments>` from the repo's checkout, in every session, gated or started by hand, so its author is the App's bot, not the maintainer (spec 012, D-14). Run it as `uvx shipmill==0.81.1 gh ...`, the release this plugin pins (spec 031), in every session, a headless gate's included, whose allowlist has `Bash(uvx *)`. Reads may keep plain `gh`. A `shipmill gh` that exits 2 is a stop: report its message and never retry the write with plain `gh`. Without the App, shipmill drafts and the person posts (spec 033, D-54): with `app_id` set, the skill runs `shipmill app-token --check` before its first write to GitHub, a push included, from the repo's checkout and through the same pinned `uvx` as `shipmill gh`; reading comes before it as it is. Exit 0: go on. On its exit 2, or a `shipmill gh` exit 2 naming the missing key, it stops there: its report's first line says the App isn't available here, quoting the check's reason, and that shipmill wrote nothing to GitHub, and it hands over the text of each write it would have made, in order, each with its target and the exact text (the repo and the issue or discussion; an opportunity issue's title, body, and labels, the comment's body, the label's name), final and ready to paste or to post with the person's own `gh`, a command it may print and never runs. It never writes with plain `gh`, `GH_TOKEN`, or a push as the person, and never asks for or fetches the key
8. **An opportunity names the goal it serves (D-34, spec 024).** When the default branch has `docs/product.md`, read its Mission, Users, Goals, and Non-goals (step 1). Every opportunity issue's body says `Serves: G-n` (several as `Serves: G-2, G-3`) or `Serves no goal`, and the accept question to the maintainer, intake's triage line on the opportunity and its line in the report, says the same. Demand still counts, but an opportunity that serves no goal is never proposed for acceptance on demand alone: its recommendation is that the maintainer adds the goal it would need to the direction, or declines it. One that hits a non-goal says `Serves no goal; hits N-n` with the non-goal's words, and its recommendation is to decline it citing `N-n`; intake still files it and never declines it itself (rule 4). A repo without `docs/product.md` groups and recommends as before, with no `Serves` line
9. **A plan changes only on the maintainer's answer (D-10, D-34).** Never accept, decline, or edit a plan without a trusted answer: a reply from an OWNER, MEMBER, or COLLABORATOR other than the `--bot-login`, newer than the plan's newest revision, as the script reads it. A reaction, a label, an untrusted comment, or your own judgment is no answer. Never add a goal or edit `docs/product.md` for a plan, not even when a plan shows the direction is missing one: only the maintainer changes the direction; say so in the report

## The script

`scripts/intake_state.py <owner/repo>` answers the status question. Run it with `uv run --no-project python` (or `python3`, 3.10+) from the repo's checkout, at the start of a pass and again before the report. Exit 0 means nothing needs action, 1 that a row below does, 2 a gh failure or malformed config (report it and stop).

| State | Means | Do |
|---|---|---|
| NEW_FEEDBACK | An open request or discussion no opportunity lists | Group it (Workflow, step 2) |
| OVERLAP | Listed by two opportunities that are open or declined | Keep it in the one that fits and remove it from the other's Evidence |
| ACCEPTED | Labelled `planned`, not yet handed to triage | Hand it to github-issue-triage's [spec gate](../github-issue-triage/references/spec-gate.md) (step 5) |
| NO_REASON | Closed as not planned with no comment | Ask the maintainer for the reason, and record it as a comment on the issue once they give it |
| OPPORTUNITY_OPEN | Waiting for the maintainer | Nothing; list it in the report with its evidence |
| HANDED_OFF | Accepted, and triage gave it a newer verdict | Nothing: triage and the spec gate own it |
| DECLINED | Closed as not planned; the note is the reason, the oldest comment from an hour before the close on | Nothing, except rule 3 for new requests |
| DONE | Closed as completed | Nothing |
| MERGED | Closed as a duplicate of another opportunity | Check the surviving one lists its members; until it does they read NEW_FEEDBACK |

What the script decides for you, so the pass doesn't re-derive it:

- **Feedback** is an open issue with no skip label and no closing triage verdict, plus each open discussion outside Announcements when Discussions are on (`--category` names the ones to count). The skip labels are `SKIP_LABELS` at the top of `intake_state.py`: `bug`, `roadmap` (a tracking issue isn't a request), and shipmill's own. `--skip-label L` (repeatable) adds to them for one run; for a label every pass should skip, add it to `SKIP_LABELS`
- **A member** of an opportunity is any issue or discussion its `## Evidence` section links in this repo (`#N`, `owner/repo#N`, or a github.com link). Membership is what the opportunity's body says, so editing the Evidence section is how a request joins or leaves
- **Evidence** per opportunity: its member count, and the thumbs-up reactions on the members and on the opportunity itself, closed members included
- **The triage marker**: a comment starting `Triage:` with the verdict in bold. Intake's own comments use `Triage: **opportunity**`, so `triage_state.py` reads a grouped request or an opportunity as triaged instead of NEW. Never put the word "implement" in one: `triage_state.py` would read it as NEEDS_PR

`--label`, `--accepted-label`, and `--marker` rename `opportunity`, `planned`, and `Triage:` for a repo that uses other names. `--json` prints JSON lines, the first one `{"autonomy": ...}`.

`--plans` adds the goal plans (spec 028) after the opportunity rows: a row per goal a plan is due for, then a row per issue labelled `goal-plan`. Pass `--wip N` with `[agents] wip`, and `--bot-login '<slug>[bot]'` when `[agents] app_id` is set (quoted, as zsh globs the brackets; a gate session's prompt names it). Without the App's login a revision never counts, so a plan only the maintainer's own login writes can't be edited ([plan.md](references/plan.md), A revision).

| State | Means | Do |
|---|---|---|
| PLAN_DUE | A goal with no open plan, and a trigger holds; the note is `no-work`, `stalled`, or `requested in #N` | Propose a plan (step 6) |
| PLAN_WAITS | A `no-work` or `stalled` goal while `[agents] wip` has no room | Nothing; list it as waiting for room |
| PLAN_OPEN | Waiting for the maintainer's answer, or an accept older than the body's last edit (`edited after accept`) | Nothing; list it in the report |
| PLAN_ANSWERED | A trusted answer, noted `decline` or `edit` | Close it as not planned, or revise it (step 6) |
| PLAN_ACCEPTED | Accepted, and an item isn't filed or isn't in the named milestone; the note names them | File the work (step 6) |
| PLAN_FILED | Accepted, every item filed and in the milestone | Nothing: triage owns the items, and closes the plan once they close |
| PLAN_MALFORMED | Open, and `plans.py check` refuses the body; the note names the line | Fix the App's own body; when the maintainer's edit broke it, ask through github-issue-triage's [needs-decision](../github-issue-triage/references/needs-decision.md) protocol |
| PLAN_DECLINED | Closed as not planned; the note is the reason | Nothing: a `no-work` plan for the goal is never proposed again |

`scripts/plans.py check FILE` checks a plan body against the grammar in [references/plan.md](references/plan.md) (exit 0, or 2 naming each line and rule), reading the goal ids from `docs/product.md`. `scripts/plans.py items <owner/repo>#P [--bot-login '<slug>[bot]'] --json` lists plan #P's items, one JSON line each with its `id`, `kind`, `text`, `after`, and the `issue` carrying its plan-item marker, or `null`.

## Workflow

### From triage

github-issue-triage sends a user's request for a new capability here instead of writing a spec for it: it comments `Triage: **opportunity**` on the request and leaves the grouping to intake. That comment is a hand-off, not a grouping: the script reads the request NEW_FEEDBACK until an opportunity's Evidence section lists it, and `triage_state.py` reads it TRIAGED, so neither skill asks for it twice. Group it in step 2 as usual; intake's own comment on it, linking the opportunity, follows triage's. Triage keeps the rest: a request an accepted opportunity already covers gets triage's **feature** verdict, held on that opportunity, and a bug or contract tweak stays an **implement**. The way back is step 5: an accepted opportunity is what triage writes a spec for.

### 1. Take stock

```bash
uv run --no-project python <skill>/scripts/intake_state.py <owner/repo>
gh label list -R <owner/repo>
```

When the default branch has `docs/product.md`, read the parts of the direction intake uses (rule 8), from the checkout after `git fetch`, each as `uvx shipmill==0.81.1 product show ...`, the release this plugin pins, in every session:

```bash
shipmill product show --section mission --section users --section goals --section non-goals
```

It exits 2 on a direction that breaks its grammar: open and update no opportunity that pass, and name the problem in the report. With a direction, run the script with `--plans` (and its `--wip` and `--bot-login`) instead, so the plan rows come too.

Read each NEW_FEEDBACK item in full (`gh issue view <n> --json title,body,comments`, or the discussion page), and the body of every opportunity the script lists, closed ones included. Run `decisions.py find` (github-issue-triage's script) with the areas the requests touch: a request that breaks a settled `D-n` rule is still an opportunity, but its Problem section says which rule it runs into.

### 2. Group

Two requests belong together when they want the **same outcome** for the user, even if they propose different solutions. "Export as CSV" and "let me open the report in a spreadsheet" are one outcome; "faster export" is another. Prefer a group the maintainer can accept or decline in one sentence. For each NEW_FEEDBACK item:

- **Fits an open or accepted opportunity**: add it to that opportunity's Evidence
- **Fits a declined opportunity**: rule 3. Add it to the declined opportunity's Evidence, and comment the recorded reason on the request
- **Fits a done opportunity**: comment on the request that it shipped, naming the release when the opportunity says it; add it to the Evidence only if it asks for more than what shipped
- **A new outcome**: a new opportunity, even with one request behind it; the evidence count tells the maintainer how strong it is
- **Not a request** (a bug, a question, a support request): leave it for github-issue-triage, or label it `bug` when that is plainly what it is

### 3. Write

Under `propose`, write each group with the templates in [references/opportunity.md](references/opportunity.md), every body through `--body-file` in the repo's `tmp/`. Its `Serves` line (rule 8) names a goal only when the outcome reaches it in the goal's own words; never stretch a goal to fit the demand, and never invent one. Create the `opportunity` and `planned` labels once if they're missing. Then:

- Open the opportunity issue with the `opportunity` label, and comment intake's triage line on it
- Comment on each request it groups, linking the opportunity
- Add the `duplicate` label to a request only when it is a pure duplicate: the same outcome, nothing the opportunity doesn't already say

Updating an opportunity edits its body: add the request to Evidence, refresh the counts, and keep the rest unless the new request changes who is affected or what success means. Re-run the script; the grouped items now read as members.

Under `observe`, write nothing: put each proposed group in the report with its requests and evidence.

### 4. The maintainer's call

Accepting is the `planned` label, declining is closing the opportunity as not planned with the reason in a comment. When a reason is a rule rather than a one-off ("shipmill stays GitHub-only"), recommend recording it in the decisions log through the [design gate](../github-issue-triage/references/design-gate.md) (Recording a decision); the log entry, not the opportunity, is what later designs are checked against. Don't add the entry yourself unless the maintainer says so.

### 5. Hand an accepted opportunity to triage

An ACCEPTED opportunity is a **feature**: under "intake and triage", run github-issue-triage on it, which runs the spec gate. The opportunity issue becomes the feature issue: the spec PR's body says "Spec for #N" with the opportunity's number, and triage's **feature** comment with its hold line makes the script read it HANDED_OFF. The spec's Problem section starts from the opportunity's Problem and Evidence. Without "and triage", list it in the report as waiting for triage.

### 6. Plan a goal

A plan is the work that reaches one goal of the direction, proposed as its own issue for the maintainer to answer (spec 028). Its template, grammar, and comments are in [references/plan.md](references/plan.md). Act on the plan rows of `intake_state.py --plans`, in the order it prints them.

**PLAN_DUE: propose.** Read the goal, its measure when spec 027 gives one, the code, the specs (`specs.py find`), and the open issues and opportunities, and write the work that reaches the goal: `existing` for an open issue that already serves it, `feature` for an outcome a user gets, `fix` for what is wrong today, in the order the work should start, `(after W-k)` where one needs another. Don't design the features: each gets its own spec after the accept. Write the body to `tmp/`, run `plans.py check` on it until it exits 0, then:

- Under `propose`, open it as the plan issue, labelled `goal-plan`, and comment intake's triage line on it. For `requested in #N`, comment the plan's link on #N and close #N as completed; the request's own text is never overwritten
- Under `observe`, open nothing and comment nothing: put the goal, its trigger, and the plan's full proposed body in the report

**PLAN_ANSWERED: do what the answer says**, and only that (rule 9):

- `decline`: close the plan as not planned (`shipmill gh issue close <P> --reason "not planned"`); the maintainer's reply is the recorded reason
- `edit`: rewrite the body as the reply asks, raising `rev`, check it, edit the issue (`shipmill gh issue edit <P> --body-file ...`), and post the `plan-revised` comment; the plan waits again. A reply that asks for more than the plan can say (a new goal, a change to the direction) is reported, not done

**PLAN_ACCEPTED: file the work.** The accept chose the work, not its design. First `plans.py items <owner/repo>#P --bot-login '<slug>[bot]' --json`: an item whose `issue` isn't `null` is filed already, so a resumed pass never files one twice. Then, for each `feature` and `fix` item still `null`, in Work order:

1. Open its issue from plan.md's filed item template: the first line is the plan-item marker `<!-- shipmill:plan-item #P W-n -->`, then the item, `Serves: G-n`, the plan's link, and a `Depends on owner/repo#M` line per `(after W-k)`, M being W-k's issue (the one filed for it, or an `existing` item's own number). With a Milestone title, open it in that milestone
2. Make it a sub-issue of the plan: `chains.py link <owner/repo>#P --child <owner/repo>#<item> --no-text` (github-issue-triage's script) from the checkout. `--no-text` writes GitHub's relation alone; without it the link appends a `Depends on` line to the plan's body, an edit after the accept that reads PLAN_OPEN and can break the Milestone section. When it exits 2 (the forge refuses sub-issues), stop filing and report the plan with the error
3. For each `(after W-k)`, run `chains.py link <owner/repo>#<item> --blocked-by <owner/repo>#M` (github-issue-triage's script) from the checkout: it adds GitHub's relation and finds the `Depends on` line already there

When the Milestone names a title, put every filed item and every `existing` item of this repository in it (`shipmill gh issue edit <n> --milestone "<title>"`), creating the milestone first when `gh api 'repos/<owner/repo>/milestones?state=all' --jq '.[].title'` doesn't list it (`shipmill gh api repos/<owner/repo>/milestones -f title="<title>"`, D-38). A plan naming `none` touches no milestone. Leave `existing` items otherwise as they are. Re-run the script: the plan reads PLAN_FILED. Comment the filed line on the plan.

Filing starts no work: dispatch no implementer and write no spec. A `feature` item goes through github-issue-triage's [spec gate](../github-issue-triage/references/spec-gate.md) like any feature, its own spec approved by its own merge; a `fix` item gets its own triage verdict. Triage takes them up on its next pass, within `[agents] wip`, oldest first, so Work order is build order.

## Report

Lead with what needs the maintainer: the OPPORTUNITY_OPEN issues, strongest evidence first, each with its request count, thumbs-up, the goal it serves or that it serves none (rule 8), and a one-line recommendation (accept or decline, and why; for one serving no goal, add the goal it would need or decline, never accept on its demand alone). Then what the pass wrote (opportunities opened and updated, requests linked), the NO_REASON issues, the ACCEPTED ones waiting for triage, and the feedback left ungrouped with the reason. Plans come next: each PLAN_OPEN plan waiting for an answer, the plans proposed, revised, declined, and filed this pass (with the filed issues), the goals PLAN_WAITS holds, and under `observe` each due plan's proposed text. On a quiet pass, one line: "No new feedback; N opportunities wait for your call."

## Improve the skill

When a pass groups badly (two outcomes in one issue, a request proposed again after a decline), add the lesson to step 2. When a script misreads a state, fix `intake_state.py` and add a case to shipmill's `tests/test_intake_state.py`. When a lesson goes into the skill, add a case under `evals/` that fails without it, in the same pull request.
