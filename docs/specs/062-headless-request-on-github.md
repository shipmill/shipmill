# S-062: A headless session's request to the maintainer always exists on GitHub

status: approved
serves: G-4

## Problem

"A headless gate session's final text is read by no one, yet a request to the maintainer can
end up only there" (shipmill/shipmill#1012). In a connected private repo a session found that a
CI log might hold a database password. It couldn't confirm it, because the command was denied,
and it wrote "For you: check the log and rotate it" in its final message. No issue and no
`needs-decision` question existed, and the value was in the log. A second session of that repo
left a crash it had found in its final text the same way.

The headless paragraph of the gate's prompt (`src/shipmill/gate.py`, `headless_paragraph`)
says a decision for the user becomes the needs-decision protocol, and so does
`skills/github-issue-triage/references/needs-decision.md` (D-21), but only the agent's
instructions hold that. The maintainer sees what waits on them from GitHub (G-4); a request
that exists only in a session's log never reaches that view. The delivery hooks (spec 026)
enforce other rules in code, but only on PreToolUse and PostToolUse.

The opportunity is shipmill/shipmill#1049. Its main risk: telling a request from a report is a
heuristic over free text, so a check that refuses a stop can loop a session that has nothing
left to do.

## Behaviour

This spec extends spec 026 (the delivery hooks, `hooks/hooks.json` and `hooks/delivery.py`)
and spec 005 (the headless launch).

### What Claude Code provides

A `Stop` hook runs when the main agent finishes its turn and is about to end; a subagent's end
is `SubagentStop`, another event, which this spec doesn't hook. Its input JSON carries
`session_id`, `transcript_path` (the session's JSONL transcript), `cwd`, `hook_event_name`
(`Stop`), and `stop_hook_active`, true when the session is already continuing because a Stop
hook refused its stop. Exit 2 refuses the stop and shows stderr to the model, which continues;
exit 0 lets it end; exit 1 is a non-blocking error. Some versions also carry
`last_assistant_message`. The build confirms with a probe, as spec 005 did, that a Stop
refusal continues a `claude -p` session on the Claude Code version the gate runs, and records
the version in the build's pull request.

### The hook

`hooks/hooks.json` gains a `Stop` entry, with no matcher, running `hooks/delivery.py stop`
through the same start snippet as the other two, with a timeout of 10 seconds. When the
snippet can't start the script it prints its one stderr line and exits 1, as D-54 holds for
every delivery hook: the session ends unchecked.

`delivery.py stop` checks a stop only when all of these hold; otherwise it exits 0 with no
output and reads no transcript:

- the input's `hook_event_name` is `Stop`
- its own environment sets `SHIPMILL_GATE=1`, which `ClaudeCli.start` puts in every headless
  session's `--settings` env (D-82): an interactive session, a person's session, and a
  subagent's end are never checked
- the repo `cwd` is in has a `.github/shipmill.toml` with an `[agents]` section, as for the
  other rules (spec 026, Where the rules apply)

### At most one refusal per session

The loop is the main risk, so two guards hold it, either one enough:

- **`stop_hook_active` true:** exit 0, whatever the final text says
- **A refusal record:** right before it refuses, the hook creates the empty file
  `shipmill-stop-<session_id>` in the system's temporary directory (Python's
  `tempfile.gettempdir()`, which follows `TMPDIR`), exclusively (`O_CREAT | O_EXCL`). When the
  file already exists, or can't be created, it exits 0 instead of refusing. A session is
  therefore refused at most once, whatever Claude Code sends on a later stop

**What the hook can't read lets the session end.** A transcript that is missing or holds a
line that isn't JSON, a final text it can't find, no `SHIPMILL_MAINTAINER` in its environment,
or a `session_id` outside `[A-Za-z0-9-]+` exits 1 with one stderr line naming what it couldn't
read; the stop never exits 2 for it. Input that isn't the hook JSON exits 1, as S-026-11 says.

### The final text addresses the maintainer

The **final text** is the input's `last_assistant_message` when it is a string, else the text
blocks of the transcript's last assistant entry.

It **addresses the maintainer** when either holds:

- it names `@<login>`, bare or in a code span, compared case-insensitively and not followed by
  another login character, where `<login>` is `SHIPMILL_MAINTAINER` from the hook's
  environment: the login the headless paragraph names, set by the gate (below)
- one of its lines, past leading whitespace and the markup `#`, `>`, `-`, `*`, `_`, and a list
  number such as `1.`, starts with one of the phrases in `ADDRESSES`
  (`hooks/delivery.py`), compared case-insensitively: `For you`, `For the maintainer`, `For @`,
  `Decision needed`, `Needs your decision`, `Action needed`, `Your turn`

A final text that does neither ends the session, unchecked further.

### The session put a request on GitHub

The session **put a request on GitHub** when its transcript holds a Bash tool call that the
PreToolUse reader (`commands`, `gh_call`) reads as a `gh` write, plain or through `shipmill gh`
(directly or as `uvx --from <spec> shipmill gh`), that is:

- `gh issue create`, or
- `gh issue edit` or `gh pr edit` with an `--add-label` value naming `needs-decision`, alone or
  in a comma-separated list

and whose tool result in the transcript is not an error (`is_error` not true). The label is
the protocol's step that makes an item wait (needs-decision.md, Asking), and an issue is where
a request with no item goes. Any other write, such as a comment alone, reads as no request.

### The refusal

A checked stop whose final text addresses the maintainer while the session put no request on
GitHub is refused: the record is created, and the hook exits 2 with three stderr lines, in the
shape S-026-9 gives every refusal:

```
shipmill hook request-on-github: your final message asks @<login> for something, and this session filed no issue and labelled nothing needs-decision
Rule: a headless session's request to the maintainer is on GitHub before it ends (needs-decision.md, Gate sessions)
Instead: post each request as a needs-decision question on its item, or file an issue for one with no item; if each is already on GitHub, end with a line naming it as owner/repo#N. You can end after this.
```

The last sentence tells the model that the next stop ends the session, so it never argues with
the hook.

### The gate

`ClaudeCli.start` (`src/shipmill/gate.py`) adds `SHIPMILL_MAINTAINER` to the `--settings` env
beside `SHIPMILL_GATE`, set to the login the headless paragraph names (the host's `gh` login,
S-004-12). An interactive launch sets neither, as today. The headless paragraph gains one
sentence at its end: `Before you end, every request to @<login> in your final message is an
issue or a needs-decision question on GitHub.`

### doctor and the headless pause

The self-test of `shipmill doctor`'s hooks block (S-026-15) adds two Stop cases against the
install a session would load: a refusing fixture (an address, no write, `stop_hook_active`
false, `SHIPMILL_GATE=1` and `SHIPMILL_MAINTAINER` set, `TMPDIR` a new empty directory) must
exit 2, and the same with `stop_hook_active` true must exit 0. Either failing is a FAIL naming
the fix, as the PreToolUse case is. A headless gate's self-test before a session (S-026-16)
runs the same cases, so a gate whose Stop hook doesn't work starts no session (D-54).

### How the tests drive it

`tests/test_delivery_hooks.py` runs `hooks/delivery.py stop` as a subprocess with an input from
`tests/fixtures/hooks/` and a transcript fixture in Claude Code's JSONL shape, taken from a real
headless session with ids and paths replaced, as S-026-17 does for the other events. `TMPDIR`
is a test's temporary directory, so the refusal record is the test's.

### Docs

- `skills/github-issue-triage/references/needs-decision.md`, Gate sessions: a headless session
  can't end with a request to the maintainer only in its final message; the Stop hook refuses
  the first such stop
- `docs/install.md`, where it lists the hooks: the Stop hook and what it checks
- Spec 026, under S-026-19: a line saying spec 062 added the Stop hook

## Acceptance criteria

- S-062-1: `hooks/hooks.json` declares a `Stop` hook with no matcher that runs `hooks/delivery.py stop` through the same start snippet as the PreToolUse hook with a 10 second timeout; with no `uv` on PATH, no Python 3.11 or newer, or the script missing, it exits 1 with one stderr line naming `shipmill doctor`, never 2
- S-062-2: A Stop input whose transcript would be refused exits 0 with no output and reads no transcript when `SHIPMILL_GATE` isn't `1`, when the repo has no `.github/shipmill.toml` or no `[agents]` section, and outside a git repo
- S-062-3: A Stop input with `stop_hook_active` true exits 0 whatever its final text and transcript
- S-062-4: In a checked stop, a final text naming `@<login>` (bare, in a code span, or in another case) with no request in the transcript exits 2 with exactly the three stderr lines the Behaviour gives; `@<login>x` alone doesn't address the maintainer
- S-062-5: In a checked stop with no request in the transcript, a final text with a line starting, past the listed markup, with each phrase of `ADDRESSES` exits 2, and a final text that names no `@<login>` and starts no line with a listed phrase exits 0
- S-062-6: A successful `gh issue create`, `gh issue edit N --add-label needs-decision`, `gh pr edit N --add-label bug,needs-decision`, each plain, through `shipmill gh`, or through `uvx --from <spec> shipmill gh`, in the transcript makes a checked stop that addresses the maintainer exit 0; the same call with an error result, and a `gh issue comment` alone, don't
- S-062-7: After one refusal, a second Stop input with the same `session_id` and `stop_hook_active` false exits 0; when the refusal record can't be created, the hook exits 0 instead of refusing
- S-062-8: A missing transcript, a transcript line that isn't JSON, no assistant text, no `SHIPMILL_MAINTAINER`, and a `session_id` outside `[A-Za-z0-9-]+` each exit 1 with one stderr line naming what couldn't be read, never 2
- S-062-9: The final text is `last_assistant_message` when the input carries it as a string, and otherwise the text blocks of the transcript's last assistant entry
- S-062-10: `ClaudeCli.start`'s `--settings` env holds `SHIPMILL_MAINTAINER` set to the login the headless paragraph names, beside `SHIPMILL_GATE=1`; an interactive launch's holds neither
- S-062-11: The headless paragraph ends with `Before you end, every request to @<login> in your final message is an issue or a needs-decision question on GitHub.`
- S-062-12: `shipmill doctor` FAILs naming the fix when the install's Stop hook doesn't exit 2 on the refusing fixture or doesn't exit 0 on it with `stop_hook_active` true, and a headless gate whose self-test fails that way starts no session
- S-062-13: `tests/fixtures/hooks/` holds Stop inputs and JSONL transcripts in Claude Code's shape for a refused stop, a stop allowed by a request, a stop allowed by `stop_hook_active`, and a stop with no address
- S-062-14: `skills/github-issue-triage/references/needs-decision.md`, `docs/install.md`, and spec 026 say what the Docs list says

## Out of scope

- Telling whether each request in the final text is on GitHub: the check reads one request
  write in the session as enough. A session that asked one question and left a second request
  only in its text ends unrefused; the headless paragraph's new sentence covers that case
- A subagent's writes: they are in the subagent's own transcript, so a main session whose
  subagent asked is refused once, and the refusal's last line lets it name the question and end
- A fallback after a session ends anyway, such as the gate filing an issue with the final text
  as the App: it would post model text nobody reviewed, and the opportunity asks that the
  session itself put the request on GitHub (Decisions for you)
- Interactive gate sessions and a person's sessions: a person can read their final text
- Agents other than Claude Code, as spec 026 leaves them out
- Reading a request's wording beyond the address check: no model is called from a hook

## Decisions relied on

- D-17: headless gate sessions run as `claude -p`, so their final text goes only to a log
- D-21: every gate session asks through the needs-decision protocol; this spec holds it in
  code for the headless ones
- D-54: delivery rules are plugin hooks in repos with `[agents]`; only the script's own
  refusal exits 2, a hook that can't start its script exits 1, no session can turn a rule off
  for itself, and a headless gate whose self-test fails starts no session
- D-82: `SHIPMILL_GATE=1` in a headless session's `--settings` env tells the hook a gate
  session from a person's, and can only turn a rule on

## Issues

The build issues, filled in once they are filed: one `- owner/repo#N: S-NNN-1, S-NNN-2` per
line, naming the criteria that issue delivers. Each criterion belongs to exactly one.

## Verification

Filled in when the spec reaches `built`: one line per criterion id, saying how it was
checked against the default branch (beyond its tests) and the result.
