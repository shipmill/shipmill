# S-099: Find a spec's contradictions before it is approved

status: approved
serves: G-1, G-2

## Problem

An approved spec that contradicts itself, a `D-n` decision, or code already on the default
branch stops its build with a needs-decision question that only asks which of the two holds
(shipmill/shipmill#1146). The maintainer then settles what the written record should have
settled before the spec was approved. `specs.py check` reads a spec's sections, criterion
ids, the decisions listed under Decisions relied on, and the goals it serves; it never sees
a criterion that disagrees with another criterion, with a decision it cites, or with the
code.

The questions the maintainer answered between 2026-10-10 and 2026-11-13 show the kinds:
S-031-27 against S-031-29 and D-50 (shipmill/shipmill#628), S-034-8 against
`needs-decision.md` (shipmill/shipmill#672), S-038-12 against an earlier spec
(shipmill/shipmill#596), a criterion naming a CLI command that does not exist
(shipmill/shipmill#568), and a spec against the shipped behaviour of `chains.py` and the hook
rules (shipmill/shipmill#561, shipmill/shipmill#470). The maintainer's review of 573 answered
questions across 15 gated repos found about 15 of this kind, the largest group a better
written record would have removed. The maintainer filed the opportunity on 2026-11-14 and
accepted it.

Part of the check is mechanical: a path, command, or flag a criterion names that the code
lacks, or a `D-n` it cites that is gone or superseded. The rest is a reader's judgment, as
github-pr-triage's reviewer brief is for a pull request.

## Behaviour

### `specs.py contradictions`

`specs.py contradictions [--base REF] [--decisions F] [--json] SPEC`
(`skills/github-issue-triage/scripts/specs.py`) reads one spec file and reports what its
Behaviour and Acceptance criteria name that the code at REF (default `origin/main`) or the
decisions log does not have. It reads the code through git at REF (`git ls-tree -r`,
`git show`, `git grep`), never the working tree, so it judges the default branch the build
starts from; it reads the decisions log from the working tree (`--decisions F`, default the
log `check` reads), so a `D-n` that `spec open --with docs/decisions.md` adds in the same
pull request counts. It writes nothing. Like the rest of the script it runs on Python 3.10
with the standard library only.

Adds: `specs.py contradictions`, `specs.py split --base`, `skills/github-issue-triage/references/spec-reader-brief.md`

It reads the inline code spans (`` `...` ``) of the Behaviour and Acceptance criteria
sections and finds:

- **A missing path.** A span with no whitespace that is a path: it holds a `/` and its last
  segment has an extension or it ends in `/`, or it is a bare file name with an extension
  (looked up by base name anywhere in the tree). A span holding a placeholder or pattern
  (`<`, `>`, `{`, `}`, `*`, `?`, `[`, `#`, or `://`) is skipped. A path not in REF's tree is
  a finding
- **A missing command.** A span whose first word, after a `uvx NAME==VERSION` or
  `uv run [options] python` prefix, is a command of the repo: an entry of `[project.scripts]`
  in `pyproject.toml` at REF (read with `tomllib`, or line by line on Python 3.10, as
  `decisions.py` reads its table), or a script file in REF's tree named by path or base name.
  The first word after it that matches `[a-z][a-z0-9-]*` is its subcommand; when it appears
  as a quoted string literal (`"word"` or `'word'`) in none of the command's source files at
  REF (the script itself, or every file of the entry point's top-level package), it is a
  finding. Any other span, such as `gh pr list`, is not the repo's and is not checked
- **A missing flag.** Each `--flag` in a command's span, checked the same way as its
  subcommand
- **A missing or superseded decision.** Each `D-n` the Behaviour or a criterion cites that the
  log lacks, or that the log marks `Superseded by: D-m`, naming `D-m`. A line that says it
  supersedes (any form of the word on the same line) is not a finding: a spec may name the
  rule it replaces

A spec declares what it adds on lines of its Behaviour that start `Adds:`, followed by code
spans, as this spec's own line above does. A path, command, or flag an `Adds:` span names is
never a missing one. While the spec file is not on REF yet (its spec pull request is open),
a path on an `Adds:` line that REF already has, or a command span with no flag whose
subcommand REF already has, is a finding too, `already exists`: the spec thinks it new, and
the code may work otherwise. A flag is not held to this, since a flag's literal may belong
to another subcommand of the same source.

The text prints one line per finding, `<spec>:<line>: <kind>: <name>: <the other side>`,
the kinds `missing path`, `missing command`, `missing flag`, `missing decision`,
`superseded decision`, and `already exists`, the other side being what was read and where
(`not in origin/main`, `no "split" in skills/.../specs.py at origin/main`,
`docs/decisions.md:<line>: Superseded by: D-m`, `<path> at origin/main`). With none it
prints `no contradictions found`. `--json` prints one object:
`{"spec": "docs/specs/NNN-<slug>.md", "base": "origin/main", "findings": [{"line": 12,
"kind": "missing flag", "name": "--fleet", "other": "..."}]}`. It exits 0 with no finding,
1 with one, and 2 on bad input: no such spec file, a spec `parse` refuses, or a REF git
can't read.

### Where it runs

- **`shipmill spec open`** (`src/shipmill/spec_open.py`, spec 053) runs `specs.py
  contradictions` on the spec against origin's default branch after `specs.py check` and
  before its first write. A finding stops it: it exits 2, prints each finding, and pushes,
  opens, and comments nothing, as its other checks do
- **`specs.py split`** runs the same check first, with `--base REF` (default `origin/main`),
  since the code may have moved since the spec merged. A finding stops it: it exits 1, prints
  each finding on stderr, and prints no build issue
- **`specs.py check`** and CI do not run it: a built spec's names may be renamed later
  without the spec being wrong about the build it described

### The reader

`skills/github-issue-triage/references/spec-reader-brief.md` is the brief for the judgment
part, sent to a fresh agent (`subagent_type: general-purpose`, `isolation: "worktree"`),
never the spec's writer. It gets only the spec's path and REF, never the writer's reasoning.
It reads, at REF: the spec; `specs.py contradictions` on it; the full entry of each `D-n` the
spec names and of each one `decisions.py find` lists for the paths its Behaviour names; the
criteria of each spec `specs.py find` lists for those paths; and the code each criterion
names. It looks for four kinds: a criterion against another criterion of the spec, against a
`D-n`, against another spec's criterion, and against the code on REF (a behaviour that works
otherwise). It reports each as `C-n: <kind>: <spec>:<line> "<quoted>" against <path>:<line>
"<quoted>": <why, one sentence>`, or `none`.

### The gate

The spec gate (`skills/github-issue-triage/references/spec-gate.md`) gains a step between
**Check it** and **Open the spec PR**: run `specs.py contradictions` and send the reader brief,
then fix each finding in the spec (a wrong name, a missing `Adds:` line, a criterion that
disagrees). A contradiction only the maintainer can settle (two rules that both hold and
disagree) goes under the pull request's "Decisions for you" as its own item, with both lines
quoted and their `path:line`. So the spec pull request asks for approval with no
contradiction left unsaid.

## Acceptance criteria

- S-099-1: `specs.py contradictions SPEC` on a spec whose spans all exist at REF prints `no contradictions found` and exits 0; with a finding it prints one `<spec>:<line>: <kind>: <name>: <other side>` line per finding and exits 1; it exits 2 on a missing spec file or a REF git can't read
- S-099-2: a path span in Behaviour or a criterion that REF's tree lacks is a `missing path` finding at its line; a bare file name found anywhere in REF's tree, and a span holding `<`, `{`, `*`, `#`, or `://`, is not
- S-099-3: a span whose first word is a `[project.scripts]` entry of `pyproject.toml` at REF, or a script file of REF's tree, and whose subcommand appears as no quoted string literal in that command's source at REF, is a `missing command` finding; the same span with a `uvx NAME==VERSION` or `uv run --no-project python` prefix reads the same, and a span of another tool (`gh pr list`) is not checked
- S-099-4: each `--flag` in such a span that appears as no quoted string literal in the command's source at REF is a `missing flag` finding
- S-099-5: a `D-n` cited in Behaviour or a criterion that the decisions log lacks is a `missing decision` finding, and one the log marks superseded is a `superseded decision` finding naming the superseding `D-m` and the log's line; a line that also holds a form of "supersede" is not
- S-099-6: a path, command, or flag named on an `Adds:` line of the Behaviour is never a missing finding; while the spec file is not on REF, a path on an `Adds:` line that REF already has, or a command span with no flag whose subcommand REF already has, is an `already exists` finding, and once the spec is on REF neither is
- S-099-7: `specs.py contradictions --json` prints one object with `spec`, `base`, and `findings`, each finding with `line`, `kind`, `name`, and `other`, and the same exit codes as the text
- S-099-8: `specs.py contradictions` reads the code only at REF: a path present in the working tree but not at REF is still a `missing path` finding, and a `D-n` present only in the working tree's decisions log is not a `missing decision` finding
- S-099-9: `shipmill spec open` on a spec with a finding exits 2, prints each finding, and pushes no branch, opens no pull request, and posts no comment
- S-099-10: `specs.py split NNN` on an approved spec with a finding at `--base` exits 1, prints each finding on stderr, and prints no build issue; with none it splits as before
- S-099-11: `specs.py check` passes a spec whose names `contradictions` would report, so CI does not run the new check
- S-099-12: `skills/github-issue-triage/references/spec-reader-brief.md` exists and names the four kinds (criterion against criterion, against a `D-n`, against another spec, against the code), the reads (`specs.py contradictions`, `decisions.py find`, `specs.py find`), a fresh agent that is not the writer, and the report line `C-n` with both sides' `path:line` quoted, or `none`
- S-099-13: `skills/github-issue-triage/references/spec-gate.md` has a step between "Check it" and "Open the spec PR" that runs `specs.py contradictions` and the reader brief, and puts a contradiction only the maintainer can settle under "Decisions for you" with both lines quoted

## Out of scope

- Enforcing the reader's judgment in code: `spec open` cannot tell whether the reader ran or what it found; the brief and the gate step carry it
- Running the check in `specs.py check` or CI: the code moves after a spec is built (S-099-11)
- A second reader pass before the split: `split` repeats only the mechanical check
- Checking how a named command behaves (its exit codes, its output) mechanically: that is the reader's part, against the code
- A spec held in another, private repo of the product that a session cannot read: access across a product's repos (D-60, D-84), not this outcome
- A change to `docs/specs/TEMPLATE.md` or the built-in template for the `Adds:` line: the line is optional, and the gate documents it
- github-pr-triage's review of a spec pull request revised after an answer: D-81 already asks again on any change to a criterion

## Decisions relied on

- D-5
- D-21
- D-49
- D-81

## Issues

The build issues, filled in once they are filed: one `- owner/repo#N: S-099-1, S-099-2` per
line, naming the criteria that issue delivers. Each criterion belongs to exactly one.

## Verification

Filled in when the spec reaches `built`: one line per criterion id, saying how it was
checked against the default branch (beyond its tests) and the result.
