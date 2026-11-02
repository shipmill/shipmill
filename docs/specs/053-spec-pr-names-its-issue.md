# S-053: A spec pull request names its feature issue, and an approved spec no issue follows is reported

status: approved
serves: G-1

## Problem

A spec is split into build issues only when its feature issue reads UNBLOCKED, which needs
two things: the spec pull request's body says "Spec for #N", and #N carries a hold line naming
that pull request. The spec gate (`skills/github-issue-triage/references/spec-gate.md`) says
so, but only an agent that loaded github-issue-triage reads it.

In another repo, a planning agent wrote a spec and opened its pull request with no feature
issue: the body named the maintainer's decision, not an issue, and no issue held on the pull
request. The maintainer merged it on 2026-11-01. A day later it was still unsplit: no issue
read UNBLOCKED, so triage never ran `specs.py split`, and the gate reported nothing (#891).
Nothing in the tools stops a spec pull request without an issue, and nothing notices an
approved spec no issue follows.

This spec adds one command that opens a spec pull request the gate can follow, a check that
refuses one it can't, and a row that reports an approved spec nobody split, whoever opened it.

## Behaviour

### `shipmill spec open`

`shipmill spec open docs/specs/NNN-<slug>.md --issue N`, run from the repo's checkout, opens
the spec pull request for a spec file already written (by `specs.py new`, then filled in):

1. Checks, before any write: the path is `docs/specs/NNN-<slug>.md`; the spec passes
   `specs.py check` and its status is `approved`; `--issue` names an open issue of the repo
   (not a pull request); no branch `spec/NNN-<slug>` exists on origin; and the App is
   available, as `shipmill gh` reads it (D-54). Any failure exits 2 with its reason and writes
   nothing: no branch, no commit, no push, nothing on GitHub
2. Creates `spec/NNN-<slug>` from `origin/<default>`, commits the spec file (and each path
   given with `--with <path>`, such as a `docs/decisions.md` entry the spec adds) as
   `Spec NNN: <title, lowercased first letter>`, and pushes the branch
3. Opens the pull request as the App, titled `Spec NNN: <title>`, its body's first line
   `Spec for #N`, followed by the text of `--body-file <file>` when given (the "Decisions for
   you" a spec pull request carries)
4. Comments the feature verdict on #N as the App, in the Feature template of
   `skills/github-issue-triage/references/comments.md`: `Triage: **feature**.`, then
   `Serves: G-n.` from the spec's `serves:` line (no goal for `serves: quality bar`), a line
   linking the pull request and the spec file, and the hold line
   `On hold: the build waits on <owner/repo>#<PR>, the spec PR.`
5. Prints the pull request's URL and exits 0

Without `--issue` it exits 2 saying a spec needs its feature issue, the issue the maintainer
filed or an accepted opportunity, and writes nothing. It never files the feature issue itself:
an issue an agent files is not the maintainer's filing (D-62, spec-gate.md, Where features
come from).

The command lives in `src/shipmill/cli.py` with its module `src/shipmill/spec_open.py`, and
reads the spec through `skills/github-issue-triage/scripts/specs.py`, which the wheel ships.
It asks no needs-decision question: the spec pull request's question stays the skill's.

### The merge gate refuses a spec pull request with no issue

`skills/github-pr-triage/scripts/pr_gate.py` reads a pull request as a spec pull request when
it adds a file `docs/specs/NNN-<slug>.md`. One whose body has no line starting `Spec for #N`
(after an optional list bullet, `owner/repo#N` of the same repo read the same) naming an open
issue of the repo reads REFUSED, exit 6, with the line
`  spec: names no feature issue: add "Spec for #N" for the open issue it specifies`, whoever
opened it. A draft stays DRAFT (D-52). A pull request that only edits an existing spec is not
checked: a revision may follow a closed feature issue.

### The watch reports an approved spec nobody split

`skills/github-ship-watch/scripts/watch_state.py` reads each spec on the checkout's default
branch and reports, in the ISSUES section, a row

`SPEC_UNSPLIT  S-NNN <title> (docs/specs/NNN-<slug>.md): approved, no build issues, no open issue follows it`

with the fix `/shipmill:github-issue-triage <owner/repo>`, for a spec whose status is
`approved`, whose Issues section has no `- owner/repo#N:` line, and that no open issue
follows: none reads BLOCKED or UNBLOCKED on the pull request that added the spec file, and
none links the spec file in its body. The row is an action, so the watch exits 1, and
`shipmill gate` takes it up in tier 6 with the issues triage owes (D-58).

github-issue-triage acts on it (`skills/github-issue-triage/SKILL.md`, `spec-gate.md`, An
approved spec nobody split): it finds the feature issue (the pull request that added the spec,
the issues naming its slug or number) or, with none, files one as the App, naming the spec and
the merged pull request whose merge approved it; then it links the spec in the issue body and
splits the spec as When the spec merges says. `skills/github-ship-watch/SKILL.md` lists the
row.

The spec gate names `shipmill spec open` as the way to open a spec pull request, in place of
the manual steps 4 and 5 of `spec-gate.md`.

## Acceptance criteria

- S-053-1: `shipmill spec open docs/specs/NNN-<slug>.md --issue N`, for an approved spec that passes `specs.py check` and an open issue N, pushes a branch `spec/NNN-<slug>` from `origin/<default>` whose one commit adds the spec file, opens a pull request whose body's first line is `Spec for #N`, comments on #N a comment starting `Triage: **feature**.` holding the line `On hold: the build waits on <owner/repo>#<PR>, the spec PR.`, prints the pull request's URL, and exits 0
- S-053-2: The verdict comment names the goals of the spec's `serves:` line as `Serves: G-n.`, and none for `serves: quality bar`; `--body-file` text follows the `Spec for #N` line in the pull request's body; each `--with` path is in the same commit
- S-053-3: `shipmill spec open` without `--issue` exits 2 with a message naming `--issue` and the feature issue, and creates no branch, pushes nothing, and writes nothing to GitHub
- S-053-4: `shipmill spec open` exits 2 and writes nothing when `--issue` names a closed issue, a pull request, or no issue of the repo
- S-053-5: `shipmill spec open` exits 2 and writes nothing when the path isn't `docs/specs/NNN-<slug>.md`, the spec fails `specs.py check` (printing its messages), or its status isn't `approved`
- S-053-6: `shipmill spec open` exits 2 and writes nothing when `spec/NNN-<slug>` already exists on origin
- S-053-7: Every write of `shipmill spec open` to GitHub goes through the App, as `shipmill gh` does; without the App available it exits 2 with `shipmill gh`'s reason before any push
- S-053-8: After `shipmill spec open`, `triage_state.py` reads issue N BLOCKED on the spec pull request, and UNBLOCKED once it merges
- S-053-9: `pr_gate.py` reads a ready pull request that adds `docs/specs/NNN-<slug>.md` and has no line starting `Spec for #N` naming an open issue of the repo REFUSED, exit 6, with the `spec: names no feature issue` line, for an agent's and a person's pull request alike
- S-053-10: `pr_gate.py` doesn't refuse for this a spec pull request whose `Spec for #N` line names an open issue, nor a pull request that only edits an existing spec file
- S-053-11: `watch_state.py` reports SPEC_UNSPLIT, with the fix `/shipmill:github-issue-triage <owner/repo>`, and exits 1 for a spec on the default branch that is `approved`, has no Issues lines, and no open issue follows (none reads BLOCKED or UNBLOCKED on the pull request that added it, none links its file in its body)
- S-053-12: `watch_state.py` reports no SPEC_UNSPLIT for a `draft` or `built` spec, an approved spec with Issues lines, one an open issue holds on through its pull request, or one an open issue's body links
- S-053-13: `shipmill gate` takes a SPEC_UNSPLIT row up in tier 6 and hands it to github-issue-triage
- S-053-14: `spec-gate.md` names `shipmill spec open` for opening a spec pull request and says how triage takes up SPEC_UNSPLIT; github-ship-watch's `SKILL.md` lists the row

## Out of scope

- A check in `specs.py check`: it reads files, not pull request bodies, so the merge gate holds the rule instead
- Filing the feature issue from `shipmill spec open`: an agent's issue is not the maintainer's filing; the SPEC_UNSPLIT path files one only after the maintainer's merge approved the spec
- The spec pull request's needs-decision question: it stays github-issue-triage's (comments.md, Feature)
- Specs in a product's home that a component's part follows (D-60): unchanged

## Decisions relied on

- D-5
- D-49
- D-52
- D-54
- D-58
- D-62

## Issues

- shipmill/shipmill#895: S-053-1, S-053-2, S-053-3, S-053-4, S-053-5, S-053-6, S-053-7, S-053-8
- shipmill/shipmill#896: S-053-9, S-053-10
- shipmill/shipmill#897: S-053-11, S-053-12, S-053-13, S-053-14

## Verification
