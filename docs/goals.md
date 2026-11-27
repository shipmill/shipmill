# A goal, from written to met

A guide for the maintainer of a repository whose agents implement. It follows one goal of
your direction, `docs/product.md` ([direction.md](direction.md)), from the line you write
to the day you record it met: the plan product intake proposes, your answers to it, the
projects an accept files, and how a goal ends. The rules behind it are specs 096 to 106 in
[`docs/specs/`](specs/); [flow.md](flow.md#goals-plans-and-projects) has the states as
tables, and product intake's [plan.md](../skills/product-intake/references/plan.md) the
exact comments.

Nothing here is decided by an agent on your behalf: agents propose, file, and ask, and
only you accept a plan, change the direction, or merge its edit (D-10, D-34).

## 1. Write the goal

Each item of `## Goals` is one of two kinds (spec 105):

| Kind | Written | Ends |
|---|---|---|
| goal | `- G-n: <outcome>. Check: <check>. By: <horizon>` | when its check passes; the horizon is a date, `YYYY-MM-DD`, or a release, `X.Y.Z` |
| standing measure | `- G-n: Held: <statement>. Threshold: <threshold>. Source: <source>` | never: it is held for good |

Write the line with `shipmill product add goals "<outcome>"`, then give it its kind with
`shipmill product goal G-n --check "<check>" --by <horizon>` or `shipmill product held G-n
--threshold "<threshold>" --source "<source>"`. Each command changes the working tree only,
so the direction still lands through a pull request you merge. Without `uv tool install
shipmill`, run each command on this page as `uvx shipmill ...`.

Only a goal has the states below. A standing measure gets a plan only when you ask for one,
and a goal written in neither form (one from before spec 105) has no state and can't be
recorded met or dropped: `product met` and `product drop` refuse it. Give it a kind with
`product goal` or `product held` first.

## 2. The plan intake proposes

A plan is the work that reaches one goal, proposed as its own issue for you to answer
(spec 028). Product intake proposes one when the goal has no open plan and:

- **Nothing serves it** (`no-work`): no open spec, issue, pull request, opportunity, or
  plan item names the goal. This waits while `[agents] wip` has no room, and is never
  raised again for a goal whose newest plan you declined
- **You ask** (`requested in #N`): open an issue labelled `goal-plan` whose title names the
  one goal, or say "plan G-3" in a session. A request never waits for room
- **You accept an opportunity for it**: an opportunity you accept (the `planned` label) whose
  goal is named by your reply `accept G-<n>`, or by the one goal its `Serves:` line names.
  The new plan proposes it as a `feature` item, and replaces an open plan of the goal if
  there is one

The plan issue is titled `Plan for G-n: <the goal's text>` and labelled `goal-plan`. Its
Goal section copies the goal's `Check:` and `By:`, and its Work section lists the items in
the order they should start:

```markdown
- W-1 existing: #41
- W-2 feature: an album exports as a PDF
- W-3 fix: page numbers restart on each chapter (after W-2)
```

An `existing` item is an open issue that already serves the goal; a `feature` states an
outcome, never a design, and gets its own spec after the accept; a `fix` says what is wrong
today. The Order section says what reaching the goal looks like once the work is done.

## 3. Your answer

Answer with a reply on the plan issue. Its first line decides; the lines after it are kept
as your reason. Only a reply by an OWNER, MEMBER, or COLLABORATOR counts, or the App's relay
of an answer you gave in a session.

| First line | Does |
|---|---|
| `accept` | Files every `feature` and `fix` item |
| `accept W-1, W-3` | Files only the items named and drops the rest |
| `accept except W-2` | Files every item but those named |
| `decline <reason>` | Closes the plan as not planned; a `no-work` plan for the goal is not proposed again, only one you request |
| `hold until <condition>` | Holds the plan untouched until a date (`2026-12-15`), an issue or pull request closing (`#N` or `owner/repo#N`), or the next stable release (`release`) |
| `answer by YYYY-MM-DD` | Moves the date your answer is due, and answers nothing |
| anything else | Sends it back: the session rewrites the plan as you ask and it waits for your answer again |

- **A dropped item stays dropped.** Intake never proposes an item you cut again for the
  goal unless you ask for it
- **An accept it can't read is asked about.** A first line that starts with `accept` and is
  none of the three forms (an id the plan doesn't list, words after the ids) files
  nothing: the session asks you once which you meant
- **A held plan is re-checked when its hold is met.** The session posts one comment listing
  the items already done or gone stale, and the plan waits for your answer again
- **Your answer is due in seven days**, counted from the plan's newest revision, unless an
  `answer by` reply sets another date. Past it the plan is overdue, and while any plan of
  the product is overdue no `no-work` plan is proposed and no held project starts; work
  already started goes on
- **A goal has one open plan.** A newer plan of the same goal replaces the older one, which
  its session closes as not planned; a replaced plan counts as neither declined nor
  answered

## 4. The projects an accept files

An accept chooses the work, not its design. Product intake files each kept `feature` and
`fix` item as an issue labelled `project` and makes it a sub-issue of the plan, and links
each kept `existing` item of the repository as a sub-issue too. An accepted opportunity
proposed as an item is not filed again: it is labelled `project` itself. Filing starts no
build: a `feature` goes through triage's spec gate like any feature, and a `fix` gets its
own triage verdict.

Each issue labelled `project` is a project's head (spec 106); you can make any issue a head
by labelling it. The project's **check issue** is the head's sub-issue titled `Check: <what
will be true>` with a `## Check` section someone other than the builder can run, and its
**parts** are the head's other sub-issues and the check issue's.

| State | When |
|---|---|
| held | the head has no check issue yet, or is labelled `held` |
| active | the head and its check issue are open, and a part is open or none is filed yet |
| in focus | active and labelled `focus` |
| closing | the project's work is done (every part closed, no pull request on the head open, and with no part filed one merged) and the check issue is open, for someone other than the builder to run |
| closed | the head closed as completed |
| stopped | the head closed as not planned with the App's stop record |

A held project is not split into issues: no spec, build issue, or implementer starts for
it. When its turn comes, a session files its check issue first, or removes the `held` label
when the check issue exists already; only then does triage split it and dispatch its parts.

## 5. How many run at once

`[agents] projects = N` in `.github/shipmill.toml` limits how many of the product's
projects are active at once. It is set once, in the product's home (a component that sets it
is refused), as an integer from 1 up to `[agents] wip`'s ceiling:

```toml
[agents]
projects = 2   # at most 2 projects active or in focus across the product
```

Active and in-focus projects count; held and closing ones don't. An accept beyond the
room still files every head: the ones over the limit are held, and the accept stands, so you
are not asked again. As a slot frees, the held heads start in order: the oldest accepted
plan's first, in its Work order, then heads with no plan by when they were labelled.
Without the key there is no limit, and every held head starts in its turn.

## 6. Hold, focus, or stop a project

- **Hold it**: label the head `held`. It reads held, so nothing new starts for it, until
  its turn starts it again as above (without `[agents] projects`, and with no plan overdue,
  that is the next pass)
- **Focus it**: label an active head `focus`. Your steps on it come first; it still counts
  as one active project
- **Stop it**: reply on the head with a first line `stop: <reason>`. The session closes the
  open parts and the check issue as not planned with `Project stopped: <reason>`, closes
  their open pull requests unmerged, and keeps merged work, reverting only the pull
  requests a `Revert on stop: #<pr>` line of the check issue names. It opens a pull request
  setting the project's spec to `stopped`, then closes the head with the stop record.
  Product intake reads a stopped project as a declined opportunity, so a new request for
  the same outcome is answered with your reason
- **A project with no change for 14 days** gets a question on its head: continue, hold, or
  stop. `continue` needs nothing more, `hold` labels it `held`, and `stop` stops it

`shipmill status --item <head>` names a project's state, who holds it, and what moves it; for
a held one, what it waits for (`a free slot: 2 of 2 active`, `plan #P overdue`, or `held by
the maintainer`). `--item G-3` does the same for a goal, and `--item <plan>` for a plan.

## 7. Met or dropped

- **When the plan's work has closed**, the session closes the plan and posts its outcome:
  what the plan's Order promised, what holds, what is still missing, and a `Goal check:` line
  saying whether the goal's own check `holds`, `fails`, or `can't be run by an agent`. When
  it holds, the session opens a pull request adding `. Met: <date>` to the goal, with a
  standing measure in its place where the goal must stay true. You merge it or change it;
  until then the goal stays planned. When the check fails or can't be run, the goal is
  written again, and its next plan starts from what is still missing
- **When the horizon passes first** (the date has ended, or the release is tagged), the
  session opens an issue labelled `goal-review` asking you to extend it (a new horizon),
  rewrite it (a new check), or drop it (with a reason). On your answer it opens the edit
  as a pull request only you merge
- **By hand**, any time: `shipmill product met G-n [--on YYYY-MM-DD]` or `shipmill product
  drop G-n --reason "<reason>"` writes the sentence (`. Met: <date>`, or `. Dropped: <date>:
  <reason>`) in the working tree, for a pull request you merge

A met or dropped goal keeps its id, so every reference to it still resolves. It gets no new
plan, and `specs.py check` refuses a draft or approved spec that serves it.
