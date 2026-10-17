# S-023: What the agents cost

status: draft

## Problem

Postponed by the maintainer on 2026-10-17: recorded now, built later, with no build issues
until it is taken up again.

The gate starts agent sessions that triage, implement, review, and merge, and nothing
records what they spend. The maintainer can't answer:

- **What does a closed issue or a merged pull request cost?** The metrics count what the
  line delivers (`skills/github-ship-watch/scripts/metrics.py`: DORA, issue to release,
  human touch, agent share), never what it took
- **Where is it wasted?** A session that changes nothing, a retry on unchanged findings
  after `retry_hours`, a pull request closed unmerged, or a revert spends as much as one
  that lands, and only its cost shows it
- **Which stage to change?** Triage, implementation, review, and watch may want different
  models or prompts, and there is no number per stage to choose by

A session spends model tokens (money through the API, quota through a subscription), CI
minutes, and the maintainer's time on its questions. This spec measures the first and
reports it beside the metrics; budgets and gates on it come after there are numbers.

## Behaviour

### A ledger of the gate's sessions

For every session the gate starts (`src/shipmill/gate.py`), headless or interactive, the
gate appends one line to `<state>/costs.jsonl` under its state directory once the session
has ended:

```json
{"session": "<uuid>", "repo": "owner/repo", "mode": "headless", "started": "...", "ended": "...",
 "items": ["#12", "#15"], "tokens": {"claude-opus-5-5": {"input": 0, "output": 0, "cache_read": 0, "cache_write": 0}},
 "outcomes": {"merged": ["#31"], "closed": ["#12"], "decisions": ["#15"], "refused": []}}
```

- `items` are the findings the gate launched the session for
- `tokens` come from the session's own transcript, which Claude Code keeps by session id,
  summed per model across the session and its subagents. A transcript the host no longer
  holds records `tokens: null`, never zeros
- `outcomes` are what changed on GitHub between the session's start and end and names it:
  pull requests it merged, issues it closed, `needs-decision` questions it posted, and
  pull requests it closed unmerged, read through the App's identity (spec 004)
- A session with no outcome is recorded too: it is the waste the ledger exists to show

### Money, only when the policy prices it

Tokens are the measure. A cost in money appears only when `.github/shipmill.toml` (D-4)
prices the models:

```toml
[agents.prices]    # USD per million tokens; a model not listed has no money cost
"claude-opus-5-5" = { input = 0.0, output = 0.0, cache_read = 0.0, cache_write = 0.0 }
```

shipmill ships no price table: prices drift and depend on the plan, and a subscription
spends quota, not money.

### `shipmill cost`

`shipmill cost [--repo owner/repo] [--days 7] [--json]` reads the ledger and prints, per
repo:

| Measure | Definition |
|---|---|
| Per outcome | tokens (and money, when priced) divided by merged pull requests and by closed issues |
| Waste | the share of tokens spent in sessions with no outcome or only a refused pull request |
| Per stage | tokens by the skill that ran the session (triage, resolve, pr-triage, watch), read from the gate's prompt |
| Unknown | sessions whose transcript was gone |

It changes nothing. A measure with nothing to measure says "no data", never 0, as
metrics.py does.

### In the weekly retro

`skills/github-ship-watch/scripts/retro.py gather` takes `--costs <costs.jsonl>`, and the
retro comment adds the week's cost measures beside last week's when the retro runs on the
gate's host. A proposal may cite a stage whose waste recurred.

## Acceptance criteria

- S-023-1: After a session the gate started ends, `<state>/costs.jsonl` holds one line for it with its session id, repo, mode, start, end, and the items it was launched for
- S-023-2: The line's `tokens` sum the session's transcript per model, its subagents included, and are `null` when the transcript is missing
- S-023-3: The line's `outcomes` list the pull requests merged, issues closed, questions posted, and pull requests closed unmerged by the gate's identity between the session's start and end; a session with none records empty lists
- S-023-4: `[agents.prices]` accepts per-model USD prices for input, output, cache_read, and cache_write; any other key fails the policy with exit 2; without it no money cost is printed anywhere
- S-023-5: `shipmill cost` prints per-outcome tokens, the waste share, tokens per stage, and the count of unknown sessions for the window, and "no data" for a measure with nothing to measure
- S-023-6: `retro.py gather --costs <file>` includes this week's and last week's cost measures in its output

## Out of scope

- Budgets and gates on cost (a per-repo or per-issue cap that turns into `needs-decision`):
  a later spec, once the ledger has real numbers
- Choosing a model per stage: decided from these numbers, not by this spec
- CI minutes and the maintainer's time: CI from the forge's billing, time from the
  `needs-decision` round trips metrics.py can add later
- Sessions a person starts by hand, outside the gate
- A fleet-wide or hosted dashboard: the ledger is per host

## Decisions relied on

- D-4: prices live in `.github/shipmill.toml`
- D-17: the gate tracks a headless session by its process and keeps its log under the state directory

## Issues

## Verification
