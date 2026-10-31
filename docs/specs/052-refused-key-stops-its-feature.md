# S-052: A refused config key stops only the feature it configures

status: approved
serves: G-1

## Problem

A config key shipmill refuses stops everything that loads the config: `Policy.load`
(`src/shipmill/policy.py`) raises on `[lanes.stable] min_soak_days` (S-029-9), and
`AgentsConfig.parse` (`src/shipmill/agents.py`) raises on `[agents] plugin_update`
(S-031-22), so every command exits 2 and every gate tick fails before it does anything.

On 2026-10-21, 0.60.0 deprecated `plugin_update` and 0.61.0 refused it 27 minutes later. The
floating `@v0` tag moved to 0.61.0, and five client gates on one host exited 2 on every tick
for about 45 minutes, until each config was fixed by hand: a down gate can't land its own fix
(#575). A sixth client still set `min_soak_days`, one key away from the same failure.

The maintainer decided (#575, D-64): a refused key turns off only the feature it configures,
with a FAIL in `doctor` and a line in each tick, while the gate keeps running every other
agent. When a deprecated key may be refused at all is D-63's question, which spec 047 gives
its evidence; D-64 adds that the refusal comes no sooner than 14 days after the release that
deprecated it.

## Behaviour

### The catalogue

A new module, `src/shipmill/refused.py`, lists every key shipmill refuses. An entry names:

- the table and the key, such as `[lanes.stable]` and `min_soak_days`
- the spec that removed it
- what it turns off, in a few words, or `nothing` when the feature it configured is gone
- the fix, the text the refusal's message ends with today

The entries at the start:

| Key | Spec | Turns off | Fix |
|---|---|---|---|
| `[lanes.stable] min_soak_days` | 029 | the stable lane | delete it, or run `shipmill upgrade --apply stable-every-batch` |
| `[agents] plugin_update` | 031 | nothing: gate sessions load the installed plugin | delete it |

Each entry's message is the line it raises today (`SOAK_REMOVED`, `PLUGIN_UPDATE_REMOVED`),
followed by `; <what it turns off> is off` when it turns something off.

### Loading

`Policy.load` and `AgentsConfig.parse` no longer raise for a catalogued key, whatever its
value. They drop the key, read the rest of the table as if it weren't there, and record the
refusal on the loaded policy (`Policy.refused`, a tuple of the catalogue's entries the config
sets, `[agents]`'s included, since `Policy` holds the parsed `[agents]` table). A key no release of shipmill ever knew still fails the load with exit 2, as D-63 keeps
it, and so does any other error in the table.

Every `shipmill` command that loads the config prints each refusal once on stderr, as
`shipmill: refused: <message>`, before its own output, and otherwise runs as it would without
the key: same output on stdout, same exit code. `--json` output carries the refusals as a
top-level `"refused"` list of `{"key", "spec", "off", "fix"}` where the command already prints
an object.

### What turns off

- **The stable lane**, while `[lanes.stable]` sets `min_soak_days`: the planner
  (`src/shipmill/planner.py`) treats the stable lane as configured but off. `shipmill plan`
  says `stable: off: <message>`, and no run releases on it, whatever its triggers say: a
  promotion that would be due without the key isn't, and `shipmill plan --lane stable` (a
  stable release by hand) exits 2 with the message. Every other lane plans and releases as it would without the key
- **Nothing**, while `[agents]` sets `plugin_update`: the config reads as if the key weren't
  there

### Where a refusal shows

- `shipmill doctor` (`src/shipmill/doctor.py`): one FAIL row named `refused` for each refusal,
  its detail the message; the `policy` row reads PASS when nothing else is wrong, and every
  other check still runs
- `shipmill status` (`src/shipmill/status.py`): one FAIL row for each refusal, with its fix as
  spec 011 requires of every non-OK row
- The gate (`src/shipmill/gate.py`): a tick on a config with a refusal runs as it would without
  the key: it walks, launches, sweeps, and lands. Its decision line ends with
  `; refused: <key> (spec NNN)` for each refusal, and `tick.json` records them under
  `"refused"`. The gate never exits 2 or writes an ERROR tick (S-048-9) for a catalogued key
- `watch_state.py` and `shipmill factory` read the gate's `tick.json` as they do today; a
  refusal is not a failing tick

### Refusing a key later

`docs/release-lanes.md`, where it says how shipmill retires a config key, says that a refused
key turns off only its feature, that refusing one is a maintainer's decision under D-63 and no
sooner than 14 days after the release that deprecated it (D-64), and that the refusal adds an
entry to `src/shipmill/refused.py` rather than a raise.

### The superseded criteria

The build marks S-029-9 and S-031-22 dropped in spec 029 and spec 031, each pointing at the
criteria of this spec that replace its exit 2, and updates their tests
(`tests/test_doctor_stable.py`, `tests/test_plugin_update_removed.py`) to this spec's
behaviour.

## Acceptance criteria

- S-052-1: `src/shipmill/refused.py` lists `[lanes.stable] min_soak_days` (spec 029, the stable lane, the `stable-every-batch` upgrade) and `[agents] plugin_update` (spec 031, nothing), each with its table, key, spec, what it turns off, and its fix
- S-052-2: A policy whose `[lanes.stable]` sets `min_soak_days`, with any value, loads; `Policy.refused` names it, and every other key of the table reads as without it
- S-052-3: A config whose `[agents]` sets `plugin_update`, with any value, loads; `Policy.refused` names it, and every other `[agents]` key reads as without it, `AgentsConfig.parse` on that table included
- S-052-4: A config with a key no release of shipmill knew, in `[lanes.stable]` or `[agents]`, still fails to load with exit 2 naming the key
- S-052-5: `shipmill plan --dry-run` on a config that sets either refused key prints `shipmill: refused: <message>` once on stderr, and exits with the code and stdout it has on the same config without the key, save the stable lane's line for `min_soak_days`
- S-052-6: While `min_soak_days` is set, `shipmill plan` says `stable: off: <message>` and plans no stable release when one would be due without the key, and the dev and rc lanes plan as without the key
- S-052-7: While `min_soak_days` is set, `shipmill plan --lane stable` exits 2 with the message and plans no release
- S-052-8: `shipmill doctor` on a config with a refused key prints one FAIL row named `refused` with the message, a PASS `policy` row when nothing else is wrong, and every other check it prints without the key
- S-052-9: `shipmill status` on a config with a refused key prints a FAIL row for it whose fix is the entry's fix
- S-052-10: A gate tick on a config that sets `plugin_update` takes the decision and launch it takes without the key, its decision line ends with `; refused: [agents] plugin_update (spec 031)`, `tick.json` records the refusal under `"refused"`, and the tick is not an ERROR tick
- S-052-11: A command whose `--json` output is an object carries a `"refused"` list of `{"key", "spec", "off", "fix"}` on a config with a refused key, and an empty list without one
- S-052-12: `docs/release-lanes.md` says a refused key turns off only its feature, that refusing a key is a maintainer's decision under D-63 no sooner than 14 days after its deprecating release, and that a refusal is an entry in `src/shipmill/refused.py`
- S-052-13: Spec 029 marks S-029-9 and spec 031 marks S-031-22 dropped, each naming the criteria of this spec that replace it

## Out of scope

- When a deprecated key may be refused: D-63 makes it a maintainer's decision on evidence, and spec 047 (`shipmill deprecations`) gives that evidence; D-64's 14-day floor is held by review, not by code
- A config upgrade per deprecation that the gate applies and lands in its own repo (#575's option 3): it may come later on top of this spec, through its own issue
- A deprecated key that still works (D-63's warnings): spec 047 catalogues those in `src/shipmill/deprecations.py`; this spec's catalogue holds only keys that are refused
- The release workflow's own steps outside `shipmill` (`land.yml`): they run the commands above and inherit their exit codes

## Decisions relied on

- D-4: settings live in `.github/shipmill.toml`
- D-63: a config that loaded keeps loading; a refusal is the maintainer's decision on evidence
- D-64: a refused key stops only its feature, and is refused no sooner than 14 days after its deprecation

## Issues

The build issues, filled in once they are filed: one `- owner/repo#N: S-NNN-1, S-NNN-2` per
line, naming the criteria that issue delivers. Each criterion belongs to exactly one.

## Verification

Filled in when the spec reaches `built`: one line per criterion id, saying how it was
checked against the default branch (beyond its tests) and the result.
