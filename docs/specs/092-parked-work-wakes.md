# S-092: Work the gate parks moves again by itself or reaches the maintainer as one question

status: approved
serves: G-1, G-4

## Problem

"Work the gate parks waits until someone reads a report: idle and parked items never wake by
themselves" (shipmill/shipmill#1613, an accepted opportunity). By spec 061 (D-87), a subject
whose last session wrote nothing on it waits until it changes, with no ceiling, and the
GATE_IDLE row only reports it; an issue parked as triaged with nothing pending (TRIAGED) waits
the same way. Nothing in the loop wakes either one, so the gate's outcome depends on the
maintainer reading a report. In one connected repo on 2026-11-25, five open items sat in "needs
attention":

- A pull request labelled `rollout:high`, held for six days by a hold on an upstream report:
  one idle session, then nothing. Spec 061 names this case: a pull request held only by a hold
  comment waits as an idle subject until it changes
- Three issues, one of them a goal plan, wait on that pull request, so one idle pull request
  holds a whole goal
- The real hold is in a component repo, where the fix waits on the maintainer's merge. When it
  lands, nothing writes on the held pull request, so the chain does not wake by itself
- A sev2 incident whose alert recovered 12 days ago, parked as triaged with nothing pending,
  stays open

Spec 089 (S-089-12) wakes an idle subject whose newest waits-on marker by the bot names an item
updated since the hand, but only on a walk that reaches its tier, and the change check that
decides whether a tick walks reads only the gate's own repo: a close in another repo wakes
nothing until some other change or the next sweep makes a walk reach it. A subject with no
marker, and a TRIAGED issue, have no wake at all.

## Behaviour

This amends spec 046 (the change check), spec 061 (idle subjects and GATE_IDLE), spec 088
(`shipmill status --item`) and spec 089 (the waits-on marker) in `src/shipmill/walk.py`,
`src/shipmill/gate.py`, `src/shipmill/agents.py`, `src/shipmill/item_status.py`,
`skills/github-ship-watch/scripts/watch_state.py` and
`skills/github-issue-triage/scripts/triage_state.py`. Spec 061's saving stays: a subject wakes on
a real change of what it waits on, never on time alone, save once per idle stretch when it names
nothing to wait on; and the gate itself writes nothing on GitHub to wake anything, so no wake can
show in its own change check.

### Two `[agents]` keys

`src/shipmill/agents.py` reads two new integer keys in `[agents]` of `.github/shipmill.toml`,
each from 0 to 90, one value per repo:

- `idle_days`, default 3: how long an idle subject that names nothing to wait on waits before it
  is handed once more to say what it waits on. 0 never hands it on time
- `parked_days`, default 7: how long a TRIAGED issue with nothing new on it waits before it goes
  back to triage. 0 never returns it

A value outside 0 to 90, or not an integer, fails to load naming the key, as `retry_hours` does.
A config without the keys loads with the defaults (D-63).

### An idle subject records what it waits on

When a walk marks a hand idle (S-061-4, S-061-5) and the subject's newest waits-on marker by the
bot (spec 089) names an item, the hand records it in `handed.json` as `"waits":
"<owner/repo>#<N>"`, beside `idle`. The marker is the subject's fact on GitHub; `waits` is a cache
of it, as `handed.json` is of the gate's launches (D-87): deleted, the next walk past
`retry_hours` reads the marker again. A hand without `idle` never carries `waits`, and a
`handed.json` whose `waits` isn't `<owner/repo>#<N>` is malformed, exit 2 naming its path, as
any malformed hand is.

### The change check reads what idle subjects wait on

The change check (S-046-2, `tick_walk` in `src/shipmill/gate.py`) reads the `updatedAt` and
`closed` of every item an idle hand's `waits` names, in one GraphQL query per 100 items by URL
(`resource(url: ...)`, as `waited_query` reads them today), only when at least one idle hand
names one; a tick with none runs no such query. An item updated after its hand's `at` is a
change: the hand's idle mark and `waits` come off, so the walk reads the subject past
`retry_hours`, re-reads its marker, and hands it again by S-089-12. An item GitHub answers null
for (gone, or a repo the token can't read) is no change, as in `waited_updates`. The cursor and
signature are unchanged, so this read wakes a subject only once per change of the item it waits
on.

So the held pull request of the Problem wakes on the first tick after its upstream report in the
component repo closes, without anyone writing on the pull request, and the issues that depend on
it move once it merges, as spec 017's UNBLOCKED reads them.

### An idle subject that names nothing to wait on is handed once to say what it waits on

An idle hand is **due** when `idle_days` is not 0, it has no `waits` naming an open item (no
`waits`, or one whose item the change check or the walk read as closed), it has no `wake`, and
its `at` is `idle_days` or more ago. A due hand is a change on the gate's side (S-046-2), once:
the walk that meets it treats its subject as not taken, cuts the item to it as spec 061 cuts one,
and records the new hand with `"wake": "idle"`. A hand with `wake` is never due, so a subject is
handed on time at most once per idle stretch; a change on the subject (or on what it waits on)
replaces the hand with one without `wake`, which starts a new stretch.

The prompt (`src/shipmill/gate.py`, `prompt`) names a due subject as spec 061 names a cut one,
followed by `, idle <n> d`, and adds one line under the list: `#<N> waited <n> d with nothing
changed since a session wrote nothing on it: act on it if you can; else post its hold with the
waits-on marker naming the open item it waits on, or ask the maintainer one needs-decision
question naming the one step that clears it.` The numbers are digits the gate parsed (D-16).

The session's write is an ordinary session write: it moves the subject's `updatedAt`, so the
subject is not idle. A needs-decision question makes it an item that waits on a reply, which is
never an item (S-005-9), and the maintainer queue lists it (spec 069). A waits-on marker naming an
open item makes the next idle mark record `waits`, and the subject wakes when that item changes.
A due session that writes nothing leaves a hand with `wake` that turns idle and is never due
again until the subject changes.

`skills/github-issue-triage/references/needs-decision.md` and `skills/github-pr-triage/SKILL.md`
say what such a session does: act when it can; else the hold with the marker when the subject
waits on another item; else one needs-decision question whose recommended option is the one step
that clears it.

### A TRIAGED issue goes back to triage after `parked_days`

`triage_state.py` takes `--parked-days N` (default 0, none) and reads a TRIAGED issue as
**PARKED_DUE** when N is not 0 and the issue's `updatedAt` is N days or more ago, its note
`triaged <YYYY-MM-DD>, nothing since (<age>): plan, postpone, or close`, the date that of its
newest triage comment. A goal plan (labelled `goal-plan`) and an opportunity (labelled
`opportunity`) wait on the maintainer's answer and keep reading TRIAGED. PARKED_DUE is an action
state of tier 6 (`agent: true`), handed by its subjects as any tier 6 state is; `watch_state.py`
passes `[agents] parked_days` from the config it reads.

The session decides again by the rubric (`skills/github-issue-triage/references/triage-rubric.md`,
the PARKED_DUE row): plan it, postpone it with a `Revisit on:` line, or close it with its
evidence, such as an incident whose alert recovered, closed naming the recovery. Its triage
comment moves `updatedAt`, so the issue waits another `parked_days` at most before it returns.

### What reports say

- `watch_state.py`'s GATE_IDLE row keeps spec 061's detail, save its end: `waits on
  <owner/repo>#<N>` in place of `waits for a change` for a hand with `waits`; for a hand that will
  be due, `waits for a change, or is handed again <YYYY-MM-DD HH:MM> UTC to name what it waits
  on`; and for a hand with `wake`, `session <id>, handed it after <n> d idle, wrote nothing on it;
  waits for a change`. With `idle_days = 0` and no `waits`, the row reads as spec 061 words it
- `shipmill status --item N` (`src/shipmill/item_status.py`) says for an idle subject what it
  waits on (`<owner/repo>#<N>` changing, or a change on it) and, when one is coming, when the gate
  hands it again; for a TRIAGED issue, `it goes back to triage on <YYYY-MM-DD>` when `parked_days`
  is not 0, else as today

### Docs

- `skills/shipmill-setup/SKILL.md` and `docs/install.md`: the two keys, their defaults, and 0
- `skills/github-ship-watch/SKILL.md` and `watch_state.py`'s help text: GATE_IDLE's three endings
- `skills/github-issue-triage/SKILL.md`, `references/triage-rubric.md`, and `triage_state.py`'s
  help text: PARKED_DUE and what a session does with it
- `skills/github-issue-triage/references/needs-decision.md` and `skills/github-pr-triage/SKILL.md`:
  what a session handed a due idle subject does
- Spec 061, under its GATE_IDLE section, and spec 089, under S-089-12: a line saying spec 092
  reads the waited item in the change check and hands an idle subject that names nothing once
  after `idle_days`

## Acceptance criteria

- S-092-1: `[agents] idle_days` and `parked_days` load as integers from 0 to 90, default 3 and 7 without the key; a value outside that range or not an integer fails to load naming the key
- S-092-2: A walk that marks a hand idle whose subject's newest waits-on marker by the bot names `o/r#5` records `"waits": "o/r#5"` on that hand; a hand without `idle` never carries `waits`, and a `waits` not of the form `<owner/repo>#<N>` makes `handed.json` fail to load naming its path
- S-092-3: A tick with an idle hand whose `waits` names an item updated after the hand's `at`, and nothing else new, walks, takes the idle mark and `waits` off that hand, and hands its subject again; with the item not updated since the hand, the tick reads QUIET
- S-092-4: The change check reads the items idle hands' `waits` name in one GraphQL query per 100 of them, and runs no such query when no idle hand has `waits`; an item GitHub answers null for is no change
- S-092-5: With `idle_days = 3`, an idle hand with no `waits`, no `wake`, and an `at` 3 days ago is a change, the walk hands its subject cut as spec 061 cuts it, and the new hand records `"wake": "idle"`; at 2 days it is no change and stays idle
- S-092-6: An idle hand whose `waits` names an open item is never due, whatever its age; one whose `waits` names a closed item is due as one without `waits`
- S-092-7: A hand with `wake` that turns idle is never due again, and the next tick with nothing else new reads QUIET; a change on its subject replaces it with a hand without `wake`
- S-092-8: With `idle_days = 0`, no idle hand is ever due, and the gate hands idle subjects exactly as spec 061 and spec 089 say
- S-092-9: The prompt of a launch for a due subject names it with `, idle <n> d` and carries the line `#<N> waited <n> d with nothing changed since a session wrote nothing on it: ...` naming only digits the gate parsed
- S-092-10: The gate makes no write to GitHub to wake a subject or to return a TRIAGED issue: a tick that hands a due subject or a PARKED_DUE issue writes only through the session it starts
- S-092-11: `triage_state.py --parked-days 7` reads a TRIAGED issue whose `updatedAt` is 7 days or more ago as PARKED_DUE with the note `triaged <YYYY-MM-DD>, nothing since (<age>): plan, postpone, or close`, and one updated 6 days ago as TRIAGED; without the flag, or with 0, every such issue reads TRIAGED as before
- S-092-12: Under `--parked-days 7`, an issue labelled `goal-plan` or `opportunity` that reads TRIAGED keeps reading TRIAGED whatever its age
- S-092-13: PARKED_DUE is a tier 6 row with `agent` true, and `watch_state.py --json --tier 6` passes `[agents] parked_days` to the triage read
- S-092-14: `watch_state.py`'s GATE_IDLE row ends `waits on <owner/repo>#<N>` for a hand with `waits`, `waits for a change, or is handed again <YYYY-MM-DD HH:MM> UTC to name what it waits on` for a hand that will be due, and `session <id>, handed it after <n> d idle, wrote nothing on it; waits for a change` for a hand with `wake`; with `idle_days = 0` and no `waits` it reads exactly as S-061-20 says
- S-092-15: `shipmill status --item N` names the item an idle subject waits on, or when the gate hands it again, and for a TRIAGED issue under a non-zero `parked_days` the date it goes back to triage
- S-092-16: The files the Docs list names say what it says

## Out of scope

- A ceiling on a subject that waits on an open item: it waits on that item, which moves by its
  own repo's work, and spec 086's chain impact shows what it holds back
- A cross-repo `Depends on` line of an issue: triage reads it on any walk that reaches tier 6,
  and at least once per sweep, as today
- Ages per tier: only tiers 3, 4, and 6 have subjects, and one value per repo is what the issue's
  case needs (Decisions for you)
- The pin bump a woken chain may need after its upstream fix lands: the session handed the woken
  subject does it as any other work
- Closing an incident from its alert's recovery by itself: the PARKED_DUE session decides, with
  the recovery as its evidence

## Decisions relied on

- D-4: the two keys live in `.github/shipmill.toml`
- D-16: a due subject's prompt names only digits the gate parsed
- D-58: the change check, which this spec gives one more read under D-111
- D-63: a config without the new keys keeps loading
- D-87: idle subjects; D-111 refines it with the read of what they wait on and the one hand
  after `idle_days`
- D-100: the waits-on marker this spec records and reads in the change check
- D-111: added with this spec (Decisions for you)

## Issues

The build issues, filled in once they are filed.

## Verification

Filled in when the spec reaches `built`.
