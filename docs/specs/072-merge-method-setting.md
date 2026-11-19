# S-072: Choose between a squash and a merge commit for landing pull requests

status: approved
serves: G-1

## Problem

shipmill lands every pull request with a squash merge, and the base of a stack with a merge
commit (D-33). A maintainer can't choose otherwise in shipmill's config: the only way to get
merge commits today is to turn off "Allow squash merging" in the repo's GitHub settings,
which D-33's fallback then follows. That setting also takes the squash away from people
merging by hand, `shipmill doctor` doesn't show the choice, and D-33 is enforced by review,
so the fallback is a rule the gate is told rather than one the code holds
(shipmill/shipmill#794).

The maintainers affected keep every commit of a branch on the default branch: projects that
review a pull request as a series of curated commits, and maintainers who want each commit
of a branch, not one per pull request, to count on its author's contribution graph. On one
maintainer's 14 active repositories over one UTC day (2026-10-28), 55 merged pull requests
held 86 commits, so a squash left 31 commits off the default branches. The maintainer asked
for the choice on 2026-10-29 and accepted the opportunity the same day, adding that the
plugin's delivery hook must hold the setting, that a method the repo doesn't allow fails
rather than falls back, and that every message naming a merge command follows the setting.

## Behaviour

### The setting

`.github/shipmill.toml` (D-4) takes a new optional key, `[agents] merge`, parsed by
`src/shipmill/agents.py`'s `AgentsConfig`:

```toml
[agents]
merge = "merge"   # or "squash", the default
```

- `"squash"`, or no key: a pull request lands with a squash merge, as today. No repo changes
  behaviour by upgrading shipmill (D-63)
- `"merge"`: a pull request lands with a merge commit, so each of its commits reaches the
  default branch
- Under either value, the base of a stack (a pull request another open pull request is
  stacked on) lands with a merge commit, so its child retargets and rebases clean, and a
  rebase merge stays refused. Under `"squash"` in a repo that doesn't allow merge commits,
  the base lands with a squash and its child is rebased onto the default branch, with the
  person's OK for the force push, as `landing.md` says today: the setting's own method, not a
  fallback
- Any other value, or one that isn't a string, fails to load with exit 2:
  `.github/shipmill.toml: [agents] merge must be "squash" or "merge", got <value>`

The setting's docs (`docs/flow.md`, the `[agents]` keys) say that a merge commit brings an
agent's in-between commits ("fix lint", "address review") onto the default branch, and that
squash stays the default while agents don't shape their commits.

D-96 records the rule and supersedes D-33: the method becomes the setting's, the fallback to
a merge commit where the repo doesn't allow a squash is gone, and the hook enforces it.

### The delivery hook

`hooks/delivery.py` (spec 026) reads `[agents] merge` with `tomllib`, as it reads
`[agents] app_id`, and gains a rule, `merge-method`, always on in a repo with `[agents]`, with
no switch:

- Under `"merge"`, `gh pr merge N --squash` (or `-s`, bundled or not), and a `gh api` merge
  call with `merge_method=squash`, exit 2 with spec 026's three lines:
  `shipmill hook merge-method: <command>`,
  `Rule: merge-method ([agents] merge = "merge", D-96)`, and an `Instead:` line with the same
  command taking `--merge` (or `merge_method=merge`). The same holds for `shipmill gh pr merge`
  and `uvx ... shipmill gh pr merge`, which the hook already checks
- Under `"squash"`, or no key, `--squash` and `--merge` both pass, as today: `--merge` is
  the method a stack's base takes, and the hook reads no GitHub state to tell a stack's base
  from another pull request (S-026-10)
- The `rebase-merge` rule stays and keeps its name; its `Instead:` line takes the setting's
  method: `--squash` under `"squash"` or no key, `--merge` under `"merge"`, and its `Rule:`
  line cites D-96
- A malformed `[agents] merge` refuses every guarded command with the config's error on the
  `Rule:` line, as S-026-12 does for a malformed `app_id`

The gate starts sessions and merges nothing itself, so this hook is what makes the setting a
rule the code holds.

### The merge through `shipmill gh`

`shipmill gh pr merge` (`src/shipmill/cli.py`, `src/shipmill/app_gh.py`), before it takes a
token, reads the repo's `allow_squash_merge` and `allow_merge_commit` (`GET repos/{repo}`)
when the command names `--squash` or `--merge`. When the named method's setting is off, it
exits 2 without merging, naming the repo setting and, when the method is the one
`[agents] merge` names, the key:
`[agents] merge = "merge" in .github/shipmill.toml, but the repo doesn't allow merge
commits (allow_merge_commit, Settings > General > Pull Requests); allow them, or set
[agents] merge = "squash"`. It never retries with the other method. A merge through the API
(`gh api` with a merge endpoint) gets the same check.

The messages that name a merge command follow the setting:

- The refusal of an API merge under a trailer setting (S-049-10, `[agents] author` or
  `credit = "decider"`) names `shipmill gh pr merge N --merge` under `"merge"`, and
  `--squash` under `"squash"` or no key
- The refusal of a merge that names no method under a trailer setting names `--merge` under
  `"merge"`, and `--squash (or --merge for a stack's base, D-96)` under `"squash"` or no key

Spec 049's credit trailer is written the same way under both values: under `"merge"`,
`--merge` writes the body GitHub's `merge_commit_message` setting would, followed by the
Co-authored-by trailers, as `--squash` does from `squash_merge_commit_message` today
(`src/shipmill/credit.py`'s `default_body`).

### `doctor`

`src/shipmill/doctor.py`, for a repo whose config has `[agents]`, prints a `merge` row:

- `PASS merge: squash (default, D-96)` with no key, `PASS merge: squash ([agents] merge)` or
  `PASS merge: merge ([agents] merge)` with one
- `WARN` instead, naming the repo setting and the fix, when the repo's `allow_squash_merge`
  or `allow_merge_commit` is off for the method the row names; a `WARN` also when merge
  commits are off under `"squash"`, since a stack's base can't land with one; a `WARN` saying
  the settings couldn't be read when the read fails, never a guess
- The `hooks` block gains a `merge-method` line saying on, and under which value it refuses
  `--squash`, and the `rebase-merge` line names D-96

### The skills

`skills/github-pr-triage/references/landing.md` (Merge style) and
`skills/github-pr-triage/SKILL.md` say the method is `[agents] merge` in the default branch's
`.github/shipmill.toml`, `squash` when unset; that a stack's base takes `--merge` under
either value, save the squash of a base under `"squash"` where merge commits are off; that
a method the repo doesn't allow is reported, never swapped for the one the setting doesn't
name;
and that the hook refuses the method the setting doesn't name. The references to D-33 there,
in `skills/github-pr-triage/scripts/pr_gate.py`'s comments, and in `docs/release-lanes.md`'s
hooks section name D-96.

## Acceptance criteria

- S-072-1: `AgentsConfig` reads `[agents] merge` as `squash` when absent or `"squash"` and `merge` when `"merge"`; any other string, or a value that isn't a string, exits 2 with a message naming `[agents] merge` and both values
- S-072-2: With `[agents] merge = "merge"`, `gh pr merge N --squash`, `gh pr merge N -s`, a bundled `-ds`, `shipmill gh pr merge N --squash`, and a `gh api` merge call with `merge_method=squash` each exit 2 from `hooks/delivery.py` naming `merge-method` and D-96, with an `Instead:` line holding the same command with `--merge` (or `merge_method=merge`); `gh pr merge N --merge` exits 0
- S-072-3: With `[agents] merge = "squash"`, and with no `merge` key, `gh pr merge N --squash` and `gh pr merge N --merge` each exit 0 from the hook, so a stack's base still takes `--merge` under either value
- S-072-4: Under `"squash"`, `"merge"`, and no key, `gh pr merge N --rebase`, `-r`, and a `gh api` call with `merge_method=rebase` exit 2 naming `rebase-merge` and D-96; the `Instead:` line takes `--squash` under `"squash"` or no key and `--merge` under `"merge"`
- S-072-5: With a malformed `[agents] merge`, a guarded command (`gh pr merge N --merge`, `git push --force origin feat:feat`) exits 2 from the hook with the config's error on the `Rule:` line, and an unguarded one (`git status`) exits 0
- S-072-6: `shipmill gh pr merge N --merge` with `[agents] merge = "merge"` in a repo whose `allow_merge_commit` is false exits 2 before any merge call, naming `[agents] merge` and `allow_merge_commit`, and makes no call with `--squash`; with `[agents] merge = "squash"` and `allow_squash_merge` false, `--squash` exits 2 the same way naming `allow_squash_merge`
- S-072-7: With `[agents] merge = "merge"` and a trailer setting (`[agents] author`, or `credit = "decider"`), the refusal of an API merge (S-049-10) names `shipmill gh pr merge N --merge`, and the refusal of a merge naming no method says to add `--merge`; under `"squash"` or no key they name `--squash` as today
- S-072-8: With `[agents] merge = "merge"` and a trailer setting, `shipmill gh pr merge N --merge` passes a `--body` holding the body GitHub's `merge_commit_message` setting would write followed by the decider's Co-authored-by trailer, as `--squash` does under `"squash"` from `squash_merge_commit_message`
- S-072-9: `shipmill doctor` in a repo with `[agents]` prints a `merge` row naming the method and where it comes from (`default` or `[agents] merge`); it WARNs naming the repo setting when the method's `allow_*` setting is off, when `allow_merge_commit` is off under `"squash"`, and when the settings can't be read; a repo without `[agents]` gets no `merge` row
- S-072-10: `shipmill doctor`'s `hooks` block prints a `merge-method` line saying on and which method it refuses, and its `rebase-merge` line names D-96
- S-072-11: `skills/github-pr-triage/references/landing.md` (Merge style), `skills/github-pr-triage/SKILL.md`, `docs/flow.md`, and `docs/release-lanes.md` name `[agents] merge` and D-96 as the Behaviour says, `landing.md` and `docs/flow.md` say that a merge commit brings an agent's in-between commits onto the default branch, and no text in them tells a session to land with the method the setting doesn't name where the repo doesn't allow the one it names
- S-072-12: `tests/fixtures/hooks/` holds a refused and an allowed fixture for `merge-method`, and a config fixture for each of `"squash"`, `"merge"`, and no key, which the hook tests of S-072-2 to S-072-5 read

## Out of scope

- How agents shape their commits before a merge commit lands them (squashing "fix lint"
  commits on the branch): a later opportunity, if merge commits make it wanted
- #793, the commits an agent writes as the maintainer: separate, and either ships without
  the other
- Worktree cleanup: a merge-commit branch is landed by ancestry, which the prune already
  reads (D-91, #244); nothing changes there
- `pr_gate.py`'s closing-keyword reading: a pull request's title and commits reach the
  default branch under both methods, so it reads them as today
- `shipmill setup` asking for the method: the key is set by hand, as `[agents] author` is
- A rebase merge as a third value: it rewrites SHAs and keeps neither benefit (D-33's Why)

## Decisions relied on

- D-4: `[agents] merge` lives in `.github/shipmill.toml`
- D-14: every agent merge goes through `shipmill gh`, which is where the repo setting check runs
- D-54 (superseding D-40, which superseded D-36): the delivery hook enforces settled delivery rules in repos with `[agents]`, with no switch for this one
- D-63: no key keeps today's squash, so no repo changes behaviour by upgrading
- D-96: the merge method is `[agents] merge`, default squash; a stack's base takes a merge commit; no rebase merge, no silent fallback

## Issues

- shipmill/shipmill#1343: S-072-1, S-072-6, S-072-7, S-072-8
- shipmill/shipmill#1344: S-072-2, S-072-3, S-072-4, S-072-5, S-072-12
- shipmill/shipmill#1345: S-072-9, S-072-10, S-072-11

## Verification
