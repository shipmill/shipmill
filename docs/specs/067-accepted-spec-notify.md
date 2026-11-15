# S-067: Approve the spec of already accepted work with notice

status: approved
serves: G-1

## Problem

The `scope` zone of the decision policy (spec 030) holds four decisions under one level with
the floor `ask`: accepting an opportunity, approving a spec, accepting a goal plan, and a
milestone. A maintainer who keeps "do we build this at all" for themselves, and lets agents
go on with the spec of work they already accepted, can't say so: `scope = "notify"` is
refused, and no narrower zone exists (#1042, grouped into #1045).

So every accepted feature is asked about twice: once when the maintainer accepts the work,
and again for its spec, and its build waits on that second answer. In shipmill/shipmill
over the 30 days to 2026-11-13, 13 questions fell in `scope` and 6 were answered with the
recommended option as it stood.

The maintainer changed N-3 of `docs/product.md` on 2026-11-15 (#1186, from their answer on
#1045): approving the spec of work not yet accepted stays theirs; the spec of accepted work
no longer is by the direction.

## Behaviour

A new zone, `accepted-spec`, takes the approval of a spec whose work is already accepted out
of `scope`. Everything else in `scope` stays as it is.

**The zone table.** `skills/github-issue-triage/scripts/decisions.py`'s `ZONES` gains
`accepted-spec` right after `scope`, with the default `ask` and the floor `notify`, and
`src/shipmill/decide.py`'s `Zone` gains it in the same place, with its floor's reason: "the
maintainer may always veto the spec of work they accepted (D-48)". The default stays `ask`,
so no repository changes behaviour by upgrading shipmill (D-63): a repository opts in with
`[decisions] accepted-spec = "notify"` in `.github/shipmill.toml`, a `decision-policy`
change only the maintainer makes. `scope` keeps the default and the floor `ask`.
`[decisions.paths]` takes no paths for `accepted-spec`, as for `scope` (spec 057).

**Accepted work.** A spec's work is accepted when every issue its pull request's body names
on a `Spec for #N` line (the line `pr_gate.py` reads, spec 053) is open and either:

- an accepted opportunity: labelled both `opportunity` and `planned`, or
- an issue the maintainer filed: its author is an OWNER, MEMBER, or COLLABORATOR, and its
  body carries no `<!-- shipmill:agent -->` marker (D-62)

Any other spec, one whose pull request names no such issue among others included, stays
in `scope`. A label or an author that can't be read counts as not accepted, so a failure
asks rather than decides.

**Code tells the zone.** `shipmill decide classify --pr N` (`src/shipmill/classify.py`)
reports `accepted-spec` in place of `scope` for a `docs/specs/*.md` whose status line becomes
`approved`, when the pull request's spec work is accepted as above, with the reason naming
the issues. Every other zone the change shows is reported as before (a `docs/decisions.md`
change, a path under `docs/product/`, a protected path), and the strictest level wins, as
spec 030 says.

**At `notify`.** A session that opens or takes up a spec pull request in `accepted-spec`
at `notify`, and in no stricter zone, takes the recommended option of each item under the
pull request's "Decisions for you" and posts spec 030's decided comment on the pull request,
its zone line `<!-- shipmill:zone accepted-spec -->`, naming the head it decided on in a
`<!-- shipmill:head <sha> -->` line, with the `decided` label. An item of "Decisions for you"
whose own zone is stricter (a departure from a `D-n`, a contract change at `ask`, a
protected path) makes the whole pull request ask, through the needs-decision protocol, as
today. `skills/github-issue-triage/references/spec-gate.md`, `references/needs-decision.md`
(Who decides) and `references/comments.md` (Feature) say so.

**Landing.** `skills/github-pr-triage/scripts/pr_gate.py` accepts a spec pull request
without a maintainer's answer when the base branch's `[decisions]` sets `accepted-spec` to
`notify`, its spec work is accepted, and the newest decided comment of `--bot-login` on it
names the zone `accepted-spec` and the pull request's current head, or a head whose spec
change `specs.py same-approval` finds format-only (D-81). A later change to the spec that is
not format-only needs a new decided comment. A notify pull request merges without waiting
for its window (D-48).

**The build waits for the window.** A spec approved at `notify` is split as today, but
`triage_state.py` reads each build issue it filed BLOCKED, with the note `veto window of
#<spec PR> until <time>`, until the spec pull request's veto window (`veto_hours` from its
merge) has passed, so no implementer starts while a veto can still stop the build. A trusted
veto on the spec pull request within its window is spec 030's VETOED: the session takes it
up by reverting the spec's status to `draft` in a pull request, closing the build issues as
not planned with a comment naming the veto, and asking the maintainer on the feature issue
through the needs-decision protocol, in `scope`.

**The retro.** `retro.py gather --decisions` counts `accepted-spec` as its own zone, so a
question or a decided comment in it is no longer counted in `scope`.

## Acceptance criteria

- S-067-1: `shipmill decide levels --json` lists `accepted-spec` right after `scope`, with `level` `ask`, `floor` `notify`, and `source` `default` for a config without it
- S-067-2: `Policy.parse` accepts `[decisions] accepted-spec = "notify"` and `"ask"`, and exits 2 for `accepted-spec = "act"` naming the floor `notify` and its reason; `scope = "notify"` still exits 2 naming the floor `ask`
- S-067-3: `[decisions.paths.accepted-spec]` exits 2 saying the zone takes no paths
- S-067-4: `shipmill decide classify --pr N` reports `accepted-spec` and not `scope` for a spec whose status line becomes `approved` when every `Spec for #N` issue of the body is open and labelled `opportunity` and `planned`, or was filed by an OWNER, MEMBER, or COLLABORATOR with no agent marker in its body
- S-067-5: `shipmill decide classify --pr N` reports `scope` for the same spec when one `Spec for` issue is an opportunity without `planned`, an issue filed by the App or with the agent marker in its body, an issue by an outside contributor, a closed issue, or an issue whose labels or author can't be read
- S-067-6: `shipmill decide classify --pr N` reports `direction` beside `accepted-spec` for a spec pull request that also changes `docs/product.md`, and `decision-policy` for one that also changes `[decisions]`
- S-067-7: `pr_gate.py` accepts a spec pull request in `accepted-spec` with no maintainer's answer when the base's `[decisions]` sets `accepted-spec = "notify"` and a decided comment of `--bot-login` with the zone `accepted-spec` names the current head
- S-067-8: `pr_gate.py` refuses that spec pull request when the base sets `accepted-spec` to `ask` or leaves it out, when the head's config sets it to `notify` but the base doesn't, when the decided comment names a head whose spec change `specs.py same-approval` finds not format-only, when the decided comment's zone is not `accepted-spec`, or when the decided comment is not the `--bot-login`'s
- S-067-9: `triage_state.py` reads a build issue of a spec approved at `notify` BLOCKED with the note `veto window of #<spec PR> until <time>` while the spec pull request's veto window is open, and as it would without this spec once it has passed
- S-067-10: `retro.py gather --decisions` counts questions and decided comments whose zone line names `accepted-spec` in an `accepted-spec` row, not in `scope`

## Out of scope

- Setting `accepted-spec = "notify"` in shipmill/shipmill's own `.github/shipmill.toml`: a `decision-policy` change, which only the maintainer makes (D-48)
- A feature item of an accepted goal plan (spec 028): its spec stays in `scope`; a plan's acceptance chose the work, and widening this zone to it is its own request
- Accepting an opportunity, a goal plan, or a milestone: they stay in `scope` with the floor `ask` (D-10)
- `act` for `accepted-spec`: the floor keeps a veto window on every spec

## Decisions relied on

- D-5
- D-10
- D-34
- D-48
- D-49
- D-62
- D-63
- D-81
- D-88

## Issues

- shipmill/shipmill#1190: S-067-1, S-067-2, S-067-3, S-067-10
- shipmill/shipmill#1191: S-067-4, S-067-5, S-067-6
- shipmill/shipmill#1193: S-067-7, S-067-8
- shipmill/shipmill#1192: S-067-9

## Verification
