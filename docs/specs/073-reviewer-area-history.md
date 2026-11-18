# S-073: The PR reviewer knows the touched area's history

status: approved
serves: G-2

## Problem

The PR reviewer judges a change by its diff, the linked issue and triage's comment
(`skills/github-pr-triage/references/reviewer-brief.md`). It can't see why the touched area
looks the way it does, so it can pass code that is correct and still the wrong change: a
revert of the same change two weeks ago, an earlier `needs-decision` answer that settled the
trade-off, an incident on the same files, or an open PR changing the same lines (#1220,
grouped into #1221, which the maintainer accepted on 2026-11-18).

It hits the maintainer of every gated repo: each change the reviewer passes that undoes a
settled decision or repeats a reverted one comes back as a revert, an incident, or a question
the record already answered, and it grows with the share of pull requests no person reads.
Outside evidence: Linear runs a review agent on this input and reports three cases a
code-only reviewer missed (anecdotes, no numbers).

## Behaviour

**The history pack.** A new command, `shipmill review history <N>` (`src/shipmill/review_history.py`,
wired in `src/shipmill/cli.py` beside `review show` and `review record`), prints the history of
the files pull request #N touches, read from the repository checkout and GitHub only (no
other source, D-6). The touched files come from `gh api repos/{owner}/{repo}/pulls/<N>/files
--paginate`, as for `review show`. It reads, over the last `--days D` days (default 180, at
least 1):

1. **Reverts.** Commits on `origin/<default>` that touched a touched file (`git log
   origin/<default> --since=<D days ago> -- <files>`) whose message has a `This reverts commit
   <sha>` line or whose subject starts `Revert "`, and merged pull requests that touched a
   touched file whose body has a `Reverts #N` or `Reverts <owner/repo>#N` line, the line
   GitHub's Revert button writes (the same reading as spec 058). Each item names the revert,
   the change it reverted (the commit or pull request), and the touched files they share
2. **Settled decisions.** Merged or closed pull requests that touched a touched file, found by
   the `(#N)` of the squash subjects in that log, carrying a needs-decision question
   (`<!-- shipmill:needs-decision -->`) with an answer by the protocol's reply rules (an
   OWNER, MEMBER, or COLLABORATOR other than the App, its body without the agent marker,
   D-62), or a decided comment (`<!-- shipmill:decided ... -->`). Each item names the pull
   request, the question's first sentence or the decision's sentence, the answer's text (at
   most 600 characters, then `…`), its author, and whether a veto followed a decided comment
3. **Incidents and postmortems.** Issues, open or closed in the window, labelled the
   `[operate] incident_label` of `.github/shipmill.toml` (default `incident`), and files under
   `docs/postmortems/` changed in the window, whose text names a touched file or the directory
   holding it. Each item names the issue or file, its title, its state, and the paths it
   named
4. **Open pull requests.** Every other open pull request whose files include a touched file,
   with its number, title, head branch, author, and the touched files they share

Each item gets an id `H-1`, `H-2`, and so on in the order above, newest first within a kind;
at most `--limit K` items per kind (default 10), and a line `H: K of M <kind> shown` when
more matched. A kind with no item prints `none`. `--json` prints one object with a key per
kind holding a list of items, each with its `id`. Text from an author who isn't an OWNER,
MEMBER, COLLABORATOR, or the App (D-16) is never printed: such an item keeps its number and
kind, and its title and body read `(untrusted author, text left out)`. `--before <sha>`
reads the history as it stood at that commit: the window ends at the commit's committer date,
and only items dated before it count, so a past pull request can be reviewed with the history
its reviewer would have had. A pull request that doesn't exist, a `--days` or `--limit` below
1, or a `--before` that isn't a commit of the checkout exits 2 naming the fix; a GitHub read
that fails exits 2, never a partial pack.

**The reviewer gets it.** `skills/github-pr-triage/references/reviewer-brief.md` gains a
`{history}` field, filled like `{review_rubric}` from a checkout at `origin/<default>`:
`uvx shipmill==<pinned> review history <N>`. The Open PR brief holds it under "The touched
area's history", and step 3 adds a check: for each `H-n`, say whether the PR contradicts it
(`contradicts`, `consistent`, or `unrelated`) with one line of reason; a `contradicts` the
PR's body or plan doesn't explain (why the revert, answer, or incident no longer holds) is a
finding citing the `H-n`. The final report gains a "History" part, one line per `H-n` with
that word, which goes into the review record `shipmill review record` posts. A pack that
prints `none` for every kind drops the field and the check. The Post-merge review brief is
unchanged. `skills/github-pr-triage/SKILL.md` names the field where it lists how the brief
is filled.

Touched areas: `src/shipmill/review_history.py`, `src/shipmill/cli.py` (`review history`),
`skills/github-pr-triage/references/reviewer-brief.md`, `skills/github-pr-triage/SKILL.md`,
`docs/postmortems/` (read), `[operate] incident_label` (read), and
`tests/test_review_history.py`.

## Acceptance criteria

- S-073-1: `shipmill review history <N>` lists, for a pull request touching `a.py`, a commit on the default branch within `--days` that touched `a.py` and has a `This reverts commit <sha>` line, and a merged pull request that touched `a.py` with a `Reverts #M` body line, each as a revert item naming the reverted commit or `#M`; a revert older than `--days`, or one touching no touched file, is not listed
- S-073-2: a merged pull request that touched a touched file and carries a needs-decision question answered by a COLLABORATOR without the agent marker is listed as a settled-decision item with the question's first sentence, the answer's text cut at 600 characters, and its author; a reply carrying the agent marker or by an outsider is not read as its answer, and a decided comment is listed with whether a veto followed it
- S-073-3: an issue labelled the configured `[operate] incident_label` (default `incident` when `.github/shipmill.toml` sets none) whose body names a touched file or its directory, and a file under `docs/postmortems/` changed in the window that names one, are listed as incident items; an incident issue that names neither is not
- S-073-4: every other open pull request sharing a touched file is listed with its number, title, head branch, author, and the shared files; the pull request under review is never listed
- S-073-5: items carry ids `H-1`, `H-2`, … in the order reverts, settled decisions, incidents, open pull requests; at most `--limit` per kind, with an `H: K of M <kind> shown` line when more matched, and `none` for an empty kind; `--json` prints one object with a key per kind and an `id` on each item
- S-073-6: an item whose author is not an OWNER, MEMBER, COLLABORATOR, or the App prints its number and kind and `(untrusted author, text left out)` in place of its title and body, in the text and the `--json` output
- S-073-7: `--before <sha>` lists only items dated before that commit's committer date, so a revert made after it is not listed
- S-073-8: `review history` exits 2 with a message naming the fix, writing nothing, for a pull request that doesn't exist, a `--days` or `--limit` below 1, a `--before` that isn't a commit of the checkout, or a failed GitHub read
- S-073-9: `reviewer-brief.md`'s Open PR brief holds a `{history}` field filled by `review history <N>` from a checkout at `origin/<default>`, a step 3 check that has the reviewer say `contradicts`, `consistent`, or `unrelated` for each `H-n` and report an unexplained `contradicts` as a finding citing it, and a "History" part in the final report; the brief drops both when every kind is `none`, and the Post-merge review brief has none of them

## Out of scope

- Using a recent revert or incident on an area to pick a stricter approval tier (part 2 of #1220): it belongs with the tiers of #1209
- An automated replay of past reverted pull requests through the reviewer with and without the pack: `--before` makes one possible by hand, and running it is a measurement for the maintainer, not a suite (D-74 retired the eval gates); see "Decisions for you" in the spec PR
- History from outside GitHub and the checkout (an issue tracker, metrics, chat), per D-6
- Changing how `pr_gate.py` reads a review record: the History part is report text, not a field the gate parses

## Decisions relied on

- D-6
- D-16
- D-34
- D-62
- D-74

## Issues

## Verification
