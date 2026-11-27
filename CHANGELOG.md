# Changelog

All notable changes to shipmill, named release-lanes before 0.3.0. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project follows
[Semantic Versioning](https://semver.org/). shipmill releases itself with its own
bot.

## [Unreleased]

## [0.193.0] - 2026-11-27

### Added

- `shipmill project check <head> --title "<what will be true>" --check-file <path>` files a project's check issue (`Check: <title>` with its `## Check`, and `## Cleanup` from `--cleanup-file`) and links it as the head's sub-issue; it refuses a head that has an open check issue already (spec 108, #1811)
- `shipmill opportunity decline <n> --by <login> --reason "<why>"` records the maintainer's decline as a relay, then closes the opportunity as not planned, and `shipmill opportunity accept <n> G-<n>|new --by <login>` on an opportunity not yet `planned` adds `planned` after its relay (D-115); product intake reads a relayed decline's reason from its line, and the credit names the maintainer a relayed accept names (spec 108, #1812)
- Each lifecycle command (`shipmill project`, `opportunity`, `goal-plan answer`, `decision answer`) prints the item's state after the move's URL, as `shipmill status --item` reads it, and product intake, the needs-decision protocol, and the flow name spec 108's commands as the way a session makes each move (spec 108, #1813)

## [0.192.0] - 2026-11-27

### Fixed

- `retro.py dedupe` also searches the closed issues by each title's words, and a proposal whose title matches one closed as not planned reads `DECLINED` (a `declined` field in `--json`, exit 1) so the weekly retro no longer reopens a declined `Direction: G-n met` or `stalled` proposal; one closed as completed still reads NEW (#1765)
- An issue labelled `postponed` with no `Triage:` comment by an OWNER, MEMBER, or COLLABORATOR or the `--bot-login` reads NEW in `triage_state.py`, its note `postponed label without a triage comment`, so a session triages it instead of skipping it for good; `intake_state.py` reads the label the same way, and an issue postponed with a trusted triage comment reads POSTPONED or REVISIT as before (#1766)

### Changed

- `pr_gate.py` refuses an agent's pull request whose plan's `Serves:` names none of the goals the newest trusted `Triage:` verdict of an issue it closes or is `Part of` names (`Serves: quality bar` included), read from the issue threads it already reads; a verdict naming no goal accepts the plan as before. github-issue-resolve, triaging an issue itself, reads the direction's Goals and Non-goals and applies triage's rule (#1767)

### Added

- Commands that write the maintainer's answer a session heard, in the form its reader counts, as `shipmill gh` writes, and remove `needs-decision`: `shipmill decision answer <n> <option>|--own`, `shipmill goal-plan answer <n> accept|decline|hold|send-back`, `shipmill project continue|hold|stop <n>`, and `shipmill opportunity accept <n> G-<n>|new`, each with `--by <login>`; each refuses before writing any answer its reader wouldn't count (spec 107, #1783)
- `shipmill project add|focus|unfocus|resume <n> --by <login>` record the maintainer's move on a project as a relay, then move its label (`project`, `focus`, `held`), and `shipmill project hold` now labels the head `held` after its comment; each refuses a move the head's reader wouldn't count, and `resume` waits for a free slot under `[agents] projects` (spec 108, #1810)

## [0.191.0] - 2026-11-27

### Changed

- Setup and docs: `shipmill-setup` asks whether each goal ends on a check or is held at a threshold and writes it with `product goal` or `product held`, offering a registry measure only for a standing measure; `docs/direction.md`'s example has one goal and one standing measure; the new `docs/goals.md`, linked from the README and `docs/install.md`, walks one goal from written to met (#1788)

## [0.190.1] - 2026-11-27

### Fixed

- Product intake no longer lists a filed plan item, or an issue labelled `project`, as NEW_FEEDBACK until triage gives it a verdict: an issue whose body's first line is the plan-item marker, written by the `--bot-login` or an OWNER, MEMBER, or COLLABORATOR, is the maintainer's accepted work, and an outsider's copy of the marker changes nothing (#1774)

## [0.190.0] - 2026-11-27

### Added

- `shipmill status --item G-3` names a goal's state, who holds it, and what moves it, and `--item N` does so for a goal plan (`answer due <date>, overdue` past its date) and a project's head (a held one names what it waits for: `plan #P overdue`, `a free slot: K of N active`, or `held by the maintainer`); the watch runs product intake with `--goals` and `--projects` and lists GOAL_OVERDUE, PLAN_REPLACED, PROJECT_START_DUE, PROJECT_IDLE, PROJECT_STOP_DUE, GOAL_PROPOSAL_DUE, and NEEDS_GOAL on the PLANS row, so the gate starts a session for each, trusting an accepted opportunity by its opener (intake's lines for those states now carry `author` and `association`) and a replaced plan only for a trusted newer one; intake's `--json` first line names the product's overdue plans (`overdue`) while any is; `fleet.py queue` shows an overdue plan as an overdue `PLAN` row and an opportunity that names no goal as an `OPPORTUNITY` row; docs/flow.md gives the states, labels, and markers, and spec 106 is built (#1743)

## [0.189.0] - 2026-11-26

### Added

- An accepted opportunity names its goal (spec 106): with `--plans`, one accepted from this release on reads ACCEPTED_INTO the goal a trusted `accept G-<n>` reply or its one-goal `Serves:` line names, GOAL_PROPOSAL_DUE (an action) for `accept new goal` until the App's `goal-proposal` issue is its parent, then GOAL_PROPOSED, or NEEDS_GOAL for no goal still open; one accepted before keeps its path to the spec gate. A goal reads PLAN_DUE for a request or an accepted opportunity even with an open plan, the older open plan reads PLAN_REPLACED (an action) by the newer, and a replaced plan is no decline. A plan's `feature` item naming an accepted opportunity files no issue: the opportunity, labelled `project` and linked as the plan's sub-issue, is its head (#1742)

## [0.188.0] - 2026-11-26

### Changed

- `pr_gate.py` prints a `no checks: none ran on <sha7>` line under a PENDING PR whose head ran no checks at all, so a repository that runs no CI on pull requests no longer reads as CI still running; the verdict and its exit code are unchanged (#1776)

## [0.187.0] - 2026-11-26

### Added

- A goal plan's answer date (spec 106): a PLAN_OPEN plan's note ends `answer by <date>`, seven days after its newest revision or its re-check after a hold, or the date the newest trusted `answer by YYYY-MM-DD` reply sets (a reply that answers nothing), and `--json` gives it as `answer_by`; past that date in UTC the plan reads PLAN_OVERDUE, no action. The ship watch accepts PLAN_OVERDUE and still lists the plan as waiting on the maintainer (#1738)
- Projects start in turn (spec 106): `intake_state.py --projects` reads PROJECT_START_DUE, an action, for the product's held heads while the room under `[agents] projects` is above 0 (without the key, every held head), a filed plan item's first by its plan's accept time and Work order, then heads with no plan by when they were labelled; product-intake's skill gives its step, the check issue filed first. While a plan of any repo of the product reads PLAN_OVERDUE, no head starts and every `no-work` plan of the product reads PLAN_WAITS `plan <owner/repo>#P overdue`; a requested plan is still proposed (#1740)

## [0.186.0] - 2026-11-26

### Changed

- Spec 105 (a goal or a standing measure) is built and verified, and `docs/direction.md` lists `shipmill product goal` and `shipmill product held` beside `product measure` (#1691)

### Added

- A goal or a standing measure (spec 105): `shipmill product goal G-n --check <check> --by <horizon>` rewrites a goal in the working tree as `<outcome>. Check: <check>. By: <horizon>`, keeping its outcome, and `shipmill product held G-n --threshold <threshold> --source <source>` rewrites it as `Held: <statement>. Threshold: <threshold>. Source: <source>`, keeping its statement and its measure line; each prints the line, edits a Goals section moved to `docs/product/` where it lives, and exits 2 writing nothing for the other kind (naming `product edit`), a horizon that is neither a date nor a version, or, for `goal`, a goal with a measure line (naming `product measure G-n --clear`). `product add` and `product edit` now refuse a text that would leave the direction failing `product check`, such as a malformed goal, with exit 2 and the lines `product check` gives, writing nothing (#1730)
- A goal plan follows its goal's kind (spec 105): `plans.py check` reads each goal's kind from `docs/product.md` and wants `Check:` and `By:` in the Goal section for a goal, `Threshold:`, `Source:`, then `Measure:` for a standing measure, and `Measure:` alone for a goal in neither form, exiting 2 naming a missing line, a line of the other kind, or one given twice; `Follows:` comes after the last of them. `intake_state.py --plans` reads a goal's `kind` from `product show --json` and proposes no `no-work` plan for a measure, which is planned only on request (`requested in #N`) (#1731)
- Product intake holds a new outcome while `[agents] outcomes` has no room: `intake_state.py` reads a request with intake's held comment HELD, `held since <date>`, which never sets exit 1; once room comes back held requests read NEW_FEEDBACK first, oldest held first, and the maintainer's `propose` reply asks for one by name past the limit; the skill gains the HELD state, the hold in its workflow, a hard rule, the room in its report, and the held comment's template (spec 101) (#1733)
- A goal of kind goal ends met or dropped (spec 106): the direction records `. Met: <date>` or `. Dropped: <date>: <reason>` after its horizon, `product check` refuses either on a measure or a goal of no kind, a bad date, an empty reason, or both, `product show --json` gives every goal `state` and `ended`, and `shipmill product met G-n [--on DATE]` and `shipmill product drop G-n --reason TEXT` write the sentence. A met or dropped goal reads no plan trigger, and `specs.py check` refuses a draft or approved spec that serves one. A spec's new `stopped` status needs no Verification section, and `specs.py split` refuses it (#1736)
- Goal states (spec 106): `intake_state.py --goals` reads GOAL_PROPOSED (a trusted `goal-proposal` issue), then for each goal of kind goal GOAL_MET, GOAL_DROPPED, GOAL_PLANNED (an accepted plan open, or a project head of one of its plans), or GOAL_WRITTEN, with `state`, `holder`, and `by` in `--json`, and GOAL_OVERDUE, an action, for a written or planned goal past its date or with its release tagged, until the App's `goal-review` issue names that goal and horizon. product-intake's skill gives GOAL_OVERDUE's question (extend, rewrite, or drop, the edit a pull request only the maintainer merges) and PLAN_DONE's `Goal check:` line with the pull request proposing the goal met (#1737)
- Projects (spec 106): `intake_state.py --projects` reads each head issue labelled `project` (a trusted author's, or labelled by someone other than its opener) as PROJECT_HELD, PROJECT_ACTIVE, PROJECT_FOCUS, PROJECT_CLOSING (its note the check issue's unchecked `## Cleanup` lines), PROJECT_CLOSED, or PROJECT_STOPPED, from its `Check: ` sub-issue and its parts, with `state`, `holder`, `check`, and `parts` in `--json`. `[agents] projects = N` caps the product's projects active or in focus at once (1 to wip's ceiling, set in the home only, a component that sets it refused naming the home), counted across the product's repos through `shipmill gh --product`, one call per owner, and printed as `projects active: K of N (product <owner/home>)`. An accepted plan's filed `feature` and `fix` items are labelled `project` (#1739)
- Projects (spec 106): `intake_state.py --projects` reads PROJECT_IDLE, an action, for an active, in-focus, or closing head whose tree (its comments, check issue, parts, and the pull requests closing them) has had no update for 14 days and no needs-decision question by the `--bot-login` since, and PROJECT_STOP_DUE, an action, on a trusted `stop: <reason>` reply or a `stop` answering that question; a stopped project's row names the reason from its stop record. `triage_state.py` reads a held project's head and its open sub-issues as BLOCKED `project #<head> held`, so nothing is split or built for it. product-intake's skill gives the idle question, the stop's steps, and matches a new request against a stopped project as against a declined opportunity (#1741)

### Fixed

- `shipmill product measure` checks the direction it would leave, as `product add` and `product edit` do: a measure line under a goal of kind goal is refused with exit 2 and `product check`'s lines, writing nothing, instead of leaving `docs/product.md` failing `product check` (#1759)

## [0.185.0] - 2026-11-26

### Changed

- Spec 098 (the maintainer holds a goal plan until a condition they name) is marked built, its Verification naming the tests that check each criterion on the code (#1683)
- `shipmill status --item` follows a held goal plan: while held, its holder is `postponed`, waiting on the event `held until <condition>`; once the hold is met, product intake's re-check holds it; once re-checked, it waits on the maintainer's answer again. `shipmill status` adds no WAITS ON YOU reason for a held plan or one whose re-check is due. The watch's `--item` read gains a `PLAN_HELD` row naming each held plan's condition, which the full report doesn't list (spec 098) (#1734)

### Added

- The direction tells a goal from a standing measure (spec 105): `shipmill product check` reads each goal of `## Goals` as a goal, `<outcome>. Check: <check>. By: <YYYY-MM-DD or X.Y.Z>`, a measure, `Held: <statement>. Threshold: <threshold>. Source: <source>`, or neither, and refuses a malformed one, or a `  measure:` line under a goal, naming the file, the line, the goal, and the form it takes; `shipmill product show --json` gives every goal its `kind`, `outcome`, `check`, `by`, `past`, `held`, `threshold`, and `source`, and a component reads its product's goals the same way (#1726)
- product-intake's `intake_state.py` counts the product's outcomes in flight under `[agents] outcomes`: every open opportunity of the repo, or of the product's home and its listed repos (read through `shipmill gh --product`, one call per owner; a component reads the limit from its home's config), printed as `outcomes in flight: K of N` and as an `outcomes` key on `--json`'s first line; without the key its output is unchanged, and the watch accepts the new key and makes no FEEDBACK_DUE row for a held request (#1728)

## [0.184.0] - 2026-11-26

### Changed

- `fleet.py queue` times a goal plan re-checked after its hold was met from the later of its newest revision and the hold's `met_at`, so a plan held for a month doesn't come back as the oldest item; a held plan, and one whose re-check is due, stay off the queue. product-intake's skill and the plan's triage line give the `hold until <a date, #N, or release>` answer, and the ship-watch skill's Fleet section says a held plan is no `PLAN` row until its condition is met (spec 098) (#1732)

## [0.183.0] - 2026-11-26

### Changed

- Specs 098, 101, 105 and 106 name their build issues: #1729, #1732 and #1734 for holding a goal plan (#1683), #1727, #1728 and #1733 for limiting the outcomes that wait on the maintainer (#1510), #1726, #1730 and #1731 for telling a goal from a standing measure (#1691), and #1736 to #1743 for the states of a goal, a plan, and a project (#1688)
- `doctor`'s `claude auth` row names the token file's fingerprint (the name of its pause record), the date the file was written and its expiry a year later, and whether a pause record holds for it, naming a still-held record for the fingerprint the gate's last launch ran with, which the file no longer holds, as stale; it reads the records and writes none, and the row now FAILs once the token is past a year, with the same fix as its WARN at 330 days (#1725)

### Added

- `[agents] outcomes` in `.github/shipmill.toml`: the most outcomes (open opportunities) the product keeps in flight at once, from 1 up to `[agents] wip`'s ceiling; a bad value is refused naming the key, and a component (`[product] home`) that sets it is refused naming the home, where the product's limit is set (spec 101) (#1727)
- Product intake: the maintainer holds a goal plan with `hold until <YYYY-MM-DD | #N | owner/repo#N | release>`; `intake_state.py --plans` reads it PLAN_HELD, no action, and once the condition is met PLAN_HOLD_MET, an action the watch's PLANS row lists, until the App's `<!-- shipmill:plan-recheck -->` comment returns it to PLAN_OPEN `hold met: ...`; `--json` rows carry `hold` (`until`, `met_at`), and `--stable-tag-regex` sets which tags are a release (spec 098) (#1729)

## [0.182.0] - 2026-11-26

### Changed

- Spec 097 (a finished plan says whether the goal moved) is marked built, its Verification naming the tests that check each criterion on the code (#1682)
- A goal plan whose filed work has all closed now reads TRIAGED in `triage_state.py`, with the note `work closed; product intake reports the outcome`, instead of UNBLOCKED, so triage leaves it to product intake to close with its outcome rather than closing it with the parent's close comment (spec 097) (#1711)

### Added

- Decision D-114 records that an accepted goal plan's existing items of this repository become its sub-issues, so a plan of existing work waits on its items and closes like any plan, refining D-38 and spec 028 (#1706)
- `intake_state.py --plans` reads a partial accept of a goal plan (spec 096): `accept W-1, W-3` keeps the items named and `accept except W-2` drops them, directly or relayed (D-68); an accepted row's `--json` line has `kept` and `dropped`, the filing reader looks at the kept items alone and the note names `dropped: <ids>`, any other first line starting with the word `accept` reads PLAN_ANSWERED `unclear accept: <rule>` until the --bot-login's needs-decision question makes it PLAN_OPEN `unclear accept asked`, and a PLAN_DUE row's `dropped` lists the items the goal's earlier plans dropped (#1708)
- Product intake files only the items a partially accepted goal plan kept (`accept W-1, W-3` or `accept except W-2`), names the dropped ones in its filed line, asks once about an unclear accept, and never proposes a dropped item again unless the maintainer asks; the watch leaves a plan whose unclear accept was asked to its needs-decision question (#1709)
- `intake_state.py --plans` reads a finished goal plan (spec 097): an open accepted plan whose filed items and `existing` items of this repository have all closed reads PLAN_DONE, an action, its note naming each item, its issue, and how it closed, and a goal's newest plan closed as completed with no trusted `<!-- shipmill:plan-outcome -->` comment after its last close reads PLAN_DONE `closed without an outcome`, with no `no-work` row for its goal meanwhile; once the outcome is posted, the goal's PLAN_DUE and PLAN_WAITS notes end `; follows #P` and their `--json` rows carry `follows` and `missing`, the outcome's `Still missing:` items (#1710)
- A finished goal plan reports its outcome (spec 097): the watch lists PLAN_DONE in the PLANS row as an action, so `shipmill gate` starts product intake for it; product-intake's skill and plan.md give its step, checking the Order's end state against trusted text, closing an open plan as completed, and posting the `<!-- shipmill:plan-outcome -->` comment with its `Holds:` and `Still missing:` lists; the goal's next plan writes `Follows: #P` after `Measure:`, which `plans.py check` accepts once there and refuses anywhere else, and answers each missing line (#1712)

### Fixed

- An accepted goal plan whose items are all existing issues no longer stays on the maintainer's list: product intake links each existing item of the repository as a sub-issue of the plan (one with another parent is named instead) and posts the filed line, so the plan waits on its items and closes with its outcome once they close (#1706)
- `shipmill status --item`, `shipmill queue` and `status --summary` read a goal plan the maintainer accepted, with items still to file (`PLAN_ACCEPTED`), as product intake's: it waits on an agent to file its items, not on the maintainer's answer (#1707)

## [0.181.0] - 2026-11-26

### Changed

- Specs 096 and 097 name their build issues: #1708 and #1709 for accepting part of a plan (#1681), and #1710 to #1712 for a finished plan's outcome (#1682)

## [0.180.0] - 2026-11-26

### Changed

- Specs 099 and 102 name their build issues: #1698, #1699, #1700 for finding a spec's contradictions (#1146), and #1701 to #1704 for claiming an issue (#1511)

## [0.179.3] - 2026-11-26

### Fixed

- `shipmill status` now reads WAITS ON YOU for a goal plan waiting on the maintainer's answer: each plan `intake_state.py --plans` reads PLAN_OPEN, opened by the App or by an owner, member, or collaborator, is a reason naming its link with the fix `fleet.py queue` gives, "answer the goal plan", on a new goal plan line, so a repo whose only open work is such a plan no longer reads IDLE or WORKING. The watch reports these plans in a new report-only PLAN_OPEN row, never an action, an agent's row, or a tier's or the sweep's, so the gate starts no session for a plan only the maintainer answers; `intake_state.py --json`'s plan lines also name the opener's author association (#1680)

## [0.179.2] - 2026-11-26

### Fixed

- A shipmill command run while the host's directory service fails to resolve the account's uid now stops with one `shipmill:` line naming the uid and saying to retry, and exits 2, instead of a `KeyError` traceback; the private file's home still never falls back to `$HOME` (#1673)
- github-issue-triage's `triage_state.py` now links a pull request to an issue as covering part of it only by a "Part of #N" in its title outside code spans, or at the start of a line or a sentence of its body outside code spans and fences; a "Part of #N" quoted mid-sentence, in backticks, or in a fence no longer makes a merged pull request the issue's own work, so an issue with a `## Check` no longer reads VERIFY_DUE dated against a pull request that only mentions it (#1678)

## [0.179.1] - 2026-11-26

### Fixed

- Triage: an open issue with a `## Check` and no sub-issue reads by its check once its own pull request merged, as a parent does: VERIFY_DUE, CHECK_FAILED after a trusted check-failed comment, or WITH_PERSON after a trusted check-waiting one, when a merged pull request links it (a closer, or `Part of #N`, not reverted); it read UNBLOCKED, DONE_NOT_CLOSED, NEEDS_PR, TRIAGED, or NEW. Without such a pull request, its holds all closed, it still reads UNBLOCKED, work to build (a feature issue whose spec pull request merged is split first), and a `postponed` one reads POSTPONED (#1671)

## [0.179.0] - 2026-11-26

### Fixed

- `shipmill queue`, `status --item`, and `status --summary` no longer hold a user's request triaged as an opportunity as the maintainer's: one no open opportunity issue names yet is the agent's, waiting for product intake to group it, and one an open opportunity issue's Evidence section names waits on that opportunity (`waits_on`), so it counts once, through its opportunity; only issues labelled `opportunity` or `goal-plan` keep holder `maintainer` and `accept`, from triage_state.py's new `proposal` and `grouped` keys, read with no new query (S-094-6 and S-088-8 amended) (#1643)

### Changed

- The hand-off of a `role:maintainer` (or `human`) item names `claude "/shipmill:github-issue-resolve <owner>/<repo>#<n>"`, the command that opens an interactive session on it in the repo's checkout, since the gate hands such an item to no headless session to work it (#1651)

### Added

- App: the gate tick's read token, an installation token asking only reads over the gate's repo and its product's repos of the same owner, scope-checked and cached apart in `app-token-tick.json` with mode 0600; a dry run caches none (#1653)

## [0.178.0] - 2026-11-25

### Changed

- A gate session that ended `ok` although an outside cause stopped its tool calls no longer turns its subject idle (spec 095): the tick reads the session's failed tool results first and records `github_limit` (GitHub's rate limit), `disk` (`No space left on device`), or `error` (a network failure). The first two drop their hand and count no attempt; `github_limit` and `disk` pause every gate on the host through `$XDG_STATE_HOME/shipmill/host/<cause>.json` until `gh api rate_limit` shows room (else its reset, or an hour on) or the checkout's file system has 2 GiB free, shown as `GATE_PAUSED` in `shipmill status` and the watch; a tool a headless session was denied sends one notification per tool, its command's first line cut at 120 characters, recorded in the gate's `denied.json`, and changes neither the session's end nor the gate's launches (#1644)

## [0.177.0] - 2026-11-25

### Fixed

- `shipmill queue` and `status --summary` put a person's item assigned to the maintainer (spec 036's `maintainer` role: its listed users and teams, else the host's `gh` login) under `waits on you`, with why `assigned to you: ...`, instead of `waits on people` and `waits on nobody` (#1641)

### Added

- `shipmill link` and `shipmill unlink` record and remove a hold between issues and pull requests: on an issue GitHub's native relation and a strict `Depends on` line, on a pull request the line in its body (spec 041 amended). The gate doesn't hand a pull request whose `Depends on` names an open item, `queue` and `status --item` hold it by its target, and triage reads HOLD_UNLINKED for an agent comment that names a wait with no link (#1645)

## [0.176.0] - 2026-11-25

### Changed

- Spec 087 widens the headless sandbox per item: a narrow grant (`[agents.sandbox.grant]`, switched on by a `sandbox:<kind>` label a trusted person set, never the App) opens a domain, a path, local ports or a tunnel for one launch and is named on the tick; tunnels reach their port through `local_ports` (`allowLocalBinding`), since one `127.0.0.1:<port>` serves only a proxy-aware HTTP client (#1588); full access (ssh with a key, Docker) never runs headless and goes to its people as a `role:maintainer` item with the command that opens an interactive session (#1610)

### Fixed

- `shipmill status --item` and `status --summary` read an opportunity the maintainer accepted (labelled `planned`, named on the watch's SPEC_DUE row) as waiting on triage's spec gate, an agent's, no longer on the maintainer's accept (#1611)

### Added

- Each record of `shipmill queue --json` carries `blocks`, the open issues that wait on the item, in the shape `status --item --json` gives them (`ref`, `bucket`, `waits_on`), and `parent`, the open issue it is a sub-issue of as `owner/name#N` or `null`; `queue --fleet` adds the waiters of every repo it read, `status --item --json` carries `parent` too, `triage_state.py --json` gives an issue's open `parent`, and the schema stays 1 (#1639)

## [0.175.0] - 2026-11-25

### Added

- `.github/shipmill.toml` takes `[agents.sandbox]`, the hosts, paths, and tunnels a repo declares for spec 087's sandboxed headless sessions: `domains`, `read`, `write`, and `[[agents.sandbox.tunnels]]` are read and checked now, and a malformed key is dropped, so sessions run without it, with a `refused` row in `shipmill doctor`, a `refused:` note on the gate's tick line and in `tick.json` (its record gaining a `why`), and a stderr line from every command that loads the config; `shipmill decide classify --pr` reports a pull request that adds an entry under `[agents.sandbox]` as `security` at `ask`, whatever `[decisions] security` sets and whatever level `[decisions.earned]` would earn (D-110) (#1528)
- `shipmill gate --sandbox` runs each headless session in Claude Code's sandbox (spec 087), and `shipmill launchd --sandbox` writes the flag into the job: the launch's one inline `--settings` JSON gains `sandbox` and `permissions.deny`, so a session's commands and file tools can't read the host's keys and logins (`~/.ssh`, `~/.aws`, `~/.config/gh/hosts.yml`, other Apps' keys, other projects' transcripts, and the rest of the spec's list, less each `[agents.sandbox] read` entry), write only its checkout, the git common dir, the main working tree's `.claude/worktrees`, its own uv cache at `~/.cache/shipmill/<owner>-<repo>/uv` and each `[agents.sandbox] write` entry (never git's `config` or `hooks`, the gate's records, or a settings file), and reach only GitHub, PyPI, astral.sh, and each `[agents.sandbox] domains` entry read from origin's default branch; its env sets `UV_CACHE_DIR` and `GH_CONFIG_DIR`, the allowlist's `Edit` and `Write` are narrowed to the write scope, and a `--claude-arg` of `--settings` or `--add-dir` exits 2. Without `--sandbox` a launch is as before (#1531)

## [0.174.0] - 2026-11-25

### Changed

- `docs/design/agent-modes.md` records the Linux half of spec 087's sandbox probe, run on Claude Code 2.1.332 on Ubuntu 24.04, beside the macOS half, with where Linux differs: a refused path reads `No such file or directory` or `Read-only file system` instead of `Operation not permitted`, `gh api` ran, and git warns it can't read `.gitmodules` (#1524)
- `shipmill status --item --json` carries `"schema": 1`, a `holder` on each condition, and the same `holder`, `via`, `accept`, `why`, `clears`, and `waits_on` as `shipmill queue`'s record of the item; `status --summary` reads the open pull requests' checks in one read rather than one per pull request (spec 094) (#1620)

### Added

- `shipmill queue [--json] [--fleet]` says who holds each open issue and pull request of a gated repo, why, what clears it, what it waits on, and whether it is an opportunity or plan to accept, built from one read of the repo's facts by the same code as `status --item`; holders are finer than `status --summary`'s four lines (waits on people, waits elsewhere, postponed), the JSON carries `"schema": 1`, and `--fleet` reads every gate job on this host one repo at a time, stopping once GitHub's rate limit is reached (spec 094) (#1620)

### Fixed

- The triage skill drops the `postponed` label whenever a postponed issue is decided again as anything but a postpone, not only as implement, so one re-decided as opportunity or feature no longer reads POSTPONED in triage and stays out of product intake (#1630)
- `shipmill doctor` says when the checkout it reads is behind origin's default branch: a new `checkout` row, after the policy row and before the rows read from the working tree, WARNs with the branch or detached HEAD, how many commits it is behind `origin/<default>`, and the fix, since the workflows, `.github/shipmill.toml`, and `pyproject.toml` rows describe that older commit (#1632)

## [0.173.1] - 2026-11-25

### Fixed

- product-intake's `intake_state.py` no longer reads an issue labelled `postponed`, `human`, or `role:<name>` as NEW_FEEDBACK, whatever its comments say, matching how `triage_state.py` reads it (POSTPONED, or a person's item), so github-ship-watch's FEEDBACK_DUE stops launching intake on it (#1628)

## [0.173.0] - 2026-11-25

### Added

- `shipmill review record` ends the review it posts with a `## Landing` section: the landing level and one line per piece of evidence (`checks`, `size`, `record`, `kind`) that `decide classify --pr N` gives at the recorded head, by origin/HEAD's levels; the verdict's marker stays the body's first line, and when that classify fails, or reads the pull request at another head, `review record` exits 2 and posts nothing. The "Who decides" docs name the `area-record` zone, `[decisions.earned]`, the four pieces of evidence, and the three ceiling kinds (spec 083) (#1549)

### Changed

- `pr_gate.py` carries the maintainer's answer over a rebase that only brought main's changes: when every approved spec the pull request edits passes `specs.py same-approval` between the answered and the judged head, and the change between those heads is exactly main's change between their merge-bases, file by file on the lines `git diff` removes and adds, the answer covers the judged head and the gate prints `accepted: answer carried over from <sha7>: only main's changes since`, lifting every ask but an agent's `files:` lines (D-109); any other difference asks again (S-055-20, D-108) (#1587)
- The decisions log records D-107 to D-109 from the maintainer's answers: the private terms file names private repositories for the leak check, superseding D-102 (#1595); an answer on a pull request carries over a rebase that only brought main's changes (#1587); an answer given before an agent's pull request opened never widens its files (#1604)

### Fixed

- `shipmill gh` now refuses a write to a public repo that names a private repo listed under the new `repos` key of `~/.config/shipmill/private.toml` (`owner/name`, or `owner/*` for a whole owner, in any case), whatever any token reads: a gate session writes with the App's installation token, which reads another installation's private repo as a 404, so the `private-repo` detector caught nothing there; the token's read still adds what it can see, a malformed entry fails every write naming its place, never its text, and `shipmill doctor` warns while the file lists no repos (D-107, S-081-20) (#1595)
- `pr_gate.py` no longer lifts an agent's `files:` lines on the maintainer's answer on an issue given before the pull request opened; that answer still lifts the other asks, and only an answer whose question names the judged head, or a head with the same change, lifts a `files:` line (S-085-14, D-109) (#1604)
- `shipmill spec open` no longer commits a `--with` file, or the spec itself, over a change the default branch gained since the working tree was made: it exits 2 naming the file and asking to rebase first, before anything is written (#1623)

## [0.172.0] - 2026-11-25

### Added

- `shipmill decide classify --pr N` lowers `protected` or `security` to the bound the base's `[decisions.earned]` sets when every piece of evidence holds: the default branch requires a check that proves (a rules read that fails holds nothing), the pull request's added plus deleted lines are at most `max_lines`, it touches no raised area, and it changes no path of a ceiling kind (shipmill's controls, workflows and actions, infrastructure, dependency manifests and lockfiles); a lowered zone gains `"earned": {"from", "to"}` and its reason ends `(earned <to> from <from> by [decisions.earned])`, and the output gains a `landing` object with the level, `earned`, and the four evidence entries (`landing:` and one line each in text); a `never` path, a level below the zone's floor, and `--files` never earn, and the required checks are read only when the base has the table (spec 083) (#1548)
- Spec 087's sandbox probe records how a sandboxed command reaches one local port: `"127.0.0.1:<port>"` in `sandbox.network.allowedDomains` opens that port alone, only through the sandbox's proxy, and `allowLocalBinding` opens every local port (Claude Code 2.1.330, macOS) (#1588)

## [0.171.0] - 2026-11-25

### Added

- `shipmill status --summary [--json]` says in a few lines whether the gate works (its last tick, the session running now, the last result, the last landed pull request) and who holds the open work: you, the agent, needs attention (a session that ended in error, a paused credential, an idle hand), or nobody, each item counted once from the conditions `status --item` gives it (spec 091) (#1522)
- `fleet.py queue --order impact` lists what waits on the maintainer by how many open issues each item holds back, most first, then oldest first: one `chains.py impact` walk over every fleet repo gives each row its `holds`, printed on its line and in `--json` with the object's `order`; a walk that fails keeps the oldest-first order, prints `IMPACT_ERROR`, and exits 2. Without `--order` the queue is unchanged. github-ship-watch's Fleet section documents it, and github-issue-triage's Chains section documents `chains.py impact`, `stalled`, and `path` (spec 086) (#1533)
- `shipmill decide classify` reports the `area-record` zone for a changed path whose area a failed release raised, with the reason `<area> is raised: <tag> failed in <env> (#N), K of M clean releases since`, at the base's `[decisions] area-record` level; it reads the production record only when the base sets `area-record` above `act` or has `[decisions.earned]`, so a repo that sets neither makes no new GitHub read, and a record read that fails exits 2 naming what couldn't be read, so `pr_gate.py` fails closed; `decide record` names the issues or deployments read that failed (spec 083) (#1546)

### Fixed

- `pr_gate.py` reads a `Proposed plan:` written under its `<!-- shipmill:needs-decision -->` and zone lines, as `fix = "propose"` writes it, as the issue's allowed files: the leading `<!-- shipmill:... -->` lines are skipped, so an agent's pull request changing a file outside the plan's `Files:` line is held instead of reading READY (#1594)
- `shipmill gate` drops a hand whose session ended `limit` or `auth` on every tick, not only on the tick that records the end, so the hands 0.167.0 saved with their end after a capped run of usage limits no longer hold their pull requests until `retry_hours` (#1602)

## [0.170.0] - 2026-11-25

### Fixed

- `shipmill gh` no longer lets every write to a public repo through on a machine without `~/.config/shipmill/private.toml`: a write naming an `owner/name` repo the token at hand reads as private exits 2 (`private-repo`), with or without the file, and in a checkout with `[agents]` a write to a public repo exits 2 until the file exists, an empty one being enough; doctor's `terms` row names the `touch` step (D-102, S-081-18, S-081-19) (#1480)
- `pr_gate.py` stops with exit 2 when it can't read the permission of the maintainer a relayed veto names (no `[agents.roles]` maintainer listed), instead of dropping the veto and letting the pull request land; a 404 still reads as no maintainer, and an answer's failed read keeps its safe side (#1569)
- `pr_gate.py` no longer lets an issue's allowed files widen after an agent's pull request opened: a `Triage: **implement**` or `Proposed plan:` comment edited since holds the pull request with `files: the allowance on #N changed after this pull request opened` until the maintainer's answer lifts it (#1570)
- Spec 090's S-090-7 names S-085-13 (D-106) as the one read of a comment's `lastEditedAt`, the allowed-files hold in `pr_gate.py`, so the two specs agree and `main` is green again (#1597)

### Changed

- A person's item links each precondition of its step as a hold (`chains.py link <item> --blocked-by <precondition>`, filing the precondition first when it has no issue) and never states one in prose, so it is handed off only once every precondition holds (#1487)
- Spec 087 follows the macOS sandbox probe (D-105): a sandboxed session gets its own `GH_CONFIG_DIR` while `~/.config/gh/hosts.yml` stays denied, its uv cache moves outside the git dir, a `permissions.allow` entry widening Edit or Write fails the launch (S-087-13), and tunnels (S-087-10, #1589) wait for a probe of local ports (#1588) (#1524)
- The skills write and keep to an issue's allowed files: triage's Implement verdict carries a `- Files:` line with paths in backticks (a spec's build issue lists its spec file), a `Proposed plan:` writes its `Files:` paths in backticks, the implementer brief passes the allowed files and calls a file outside them a decision for you, github-issue-resolve's plan stays within them, landing asks a `files:` hold with the needs-decision question naming each file outside, and `pr_gate.py`'s docstring names the `files:` lines, their exit 5, and how the answer lifts them (#1527)

### Added

- The maintainer's accepting answer lifts `pr_gate.py`'s `files:` lines under spec 055's rules for the head it covers, so CI decides; a head whose own change differs since keeps them, a new verdict on the issue after the pull request opened doesn't widen them, and `shipmill gh pr merge` on a pull request they hold exits 2 before gh runs, now proven by tests (#1525)
- `chains.py impact`, `stalled`, and `path`, three read-only views of `show`'s one walk: `impact` prints the items open work waits on, most held first; `stalled` prints the heads of chains idle for `--days N` or more (7 by default) and exits 1 when it prints one; `path --repo R --milestone T` prints a milestone's open issues and every open item they wait on, `decision` and `maintainer` items first. `impact` and `stalled` take `--repo OWNER/NAME` to start from every open issue of a repo, paged past 100, and each view takes `--json`, `--trusted-only`, and `--bot-login` (spec 086) (#1529)
- The watch's full report gives each chain's head idle 7 days or more (an open issue that holds 1 or more and waits for neither `items` nor `cycle`) a report-only `CHAIN_STALLED` row, `holds K open issue(s), no event for D day(s), waits for <waiting_for>`, with `chains.py show` on it as its fix, from the walk it already makes; no `--tier` or `--sweep` read prints it, it changes no exit code, and `shipmill status` lists it on a `stalled chains` line without changing the verdict (spec 086) (#1530)
- `shipmill decide record [--json]` prints the production record of each area (a changed path's parent directory) that a failed release touched: an incident `shipmill operate` opened, by a bot or a trusted author, raises the areas of the failed tag's diff from its rollback's tag (or, for `to=-`, the newest earlier tag by version), and the area reads `RAISED` until `[decisions] clean_releases` later tags that reached `success` in the same environment, had no incident, and touched it clear it; a read that fails, a tag the checkout lacks, or a trusted incident whose hidden line doesn't read exits 2 and prints no area (spec 083) (#1545)
- `src/shipmill/earned.py` holds spec 083's earned landing level as a pure function: a path that puts `protected` or `security` in takes the zone's `[decisions.earned]` bound when the four pieces of evidence (a required check that proves, at most `max_lines` changed, no raised area, no path of a ceiling kind: `controls`, `infrastructure`, `dependencies`) hold, never for a path at `never` or below the zone's floor; `tests/landing/seeded.toml` holds 18 seeded cases the rule is scored on, and a miss fails CI naming `MISS L-n: expected <level>, got <level>`; nothing calls the rule yet (spec 083) (#1547)
- `shipmill gh issue comment <n> --status` and `pr comment <n> --status` write a session's progress into the item's one status comment, creating it once and editing it after, so a maintainer a question subscribed gets no email per step; `triage_state.py` reads no hold from a status comment, and the four skills post their progress this way (spec 090) (#1591)

## [0.169.0] - 2026-11-25

### Added

- Spec 087's sandbox probe, macOS half: `docs/design/probe-087/` starts a real `claude -p` with the spec's `sandbox` and `permissions` settings and a canary in `~/.ssh`, and `docs/design/agent-modes.md` records on Claude Code 2.1.330 what it refused, the refusal text the tick reads, and four departures from the spec that wait on a decision (`gh` and a denied `hosts.yml`, user `permissions.allow` widening Edit and Write, no local port, the uv cache under the git dir) (S-087-1) (#1524)

## [0.168.0] - 2026-11-25

### Fixed

- `pr_gate.py` no longer lands an agent's docs-only pull request that sets a spec's `status:` to `built` without a review: that line claims a feature finished, so the PR reads UNREVIEWED until a review of its head is recorded, read from the patches of the files API call the docs-only check already makes; every other docs-only change keeps its verdict (#1486)
- An `upstream` report with no link to an issue in another repo and no assignee no longer waits on nobody: without a coordinator, `triage_state.py` reads it `UPSTREAM_UNOWNED` (not an action), `fleet.py queue` lists it as an `UPSTREAM` row for the maintainer to report it where it belongs until it is linked or assigned, and `shipmill status --item` says so; the queue now passes the clone's `[product] home` to `triage_state.py` as `--home`, as the watch does, and in the home repo (its config has `[product] repos`) both pass the repo itself, whose coordinator routes its reports (#1487)
- The watch's `GATE_PAUSED` reads the gate's token file as the gate does: a `--claude-token` file that is missing, or a token file the gate refuses (not a regular file, another user's, readable by group or others, not a token), prints no row instead of the login's pause and its `claude auth login` fix; a `gate.json` that isn't a JSON object stops with exit 2, as the gate refuses it (#1583)

### Added

- The gate takes what holds the most first: `watch_state.py --tier 4` and `--tier 6` run one `chains.py show` over the repo's open issues and give each ISSUES row `"impact": [[number, held], ...]` (its issues other open issues wait on, most held first), the walk orders the rows of tiers 4 and 6 by their highest `held` after the expedite rows and before the kind's place, and a LAUNCH of such an item names its issue of highest `held` and its count in the decision's reason and the prompt; `impact` joins no fingerprint, a malformed one fails the read, and a failed walk adds its CHAIN_UNREADABLE row and leaves the tier in its old order (spec 086) (#1532)
- Gate: a headless session that ended on a usage limit (`limit`) or a refused credential (`auth`) pauses the credential it ran with, in `$XDG_STATE_HOME/shipmill/claude/<credential>.json` (`~/.local/state` without `XDG_STATE_HOME`), `<credential>` the first 16 hex digits of the token file content's SHA-256, or `login`, never the token. Every gate on the host reads its credential's pause before it launches and, while it holds, starts no session and reads `PAUSED`, naming the cause and when it ends; neither end counts toward `DEAD_STREAK`. A `limit` pause lifts at the log's newest `resetsAt`, or after `retry_hours` without one; an `auth` pause lifts once the token file's content changes, or, without a token file, once `claude auth status` reports a login, and sends one notification. `gate.json` records the credential each launch ran with (#1552)
- Gate: while a usage limit pauses the sessions' credential, each tick runs `claude -p "/usage"`, which calls no model, with that credential (the token file's token as `CLAUDE_CODE_OAUTH_TOKEN`, never the host login), and lifts the pause on the first tick whose output shows every window under 100% used; one showing a window full holds it. When the probe exits non-zero, doesn't answer in 60 s, or its output names no window, the pause lifts at the log's `resetsAt`, or after `retry_hours` without one (#1553)
- Gate: a subject a session left unchanged because it waits on another item is handed again once that item changes. The session names the item in a comment on the subject whose first line is `<!-- shipmill:waits-on owner/repo#N -->`, posted as the App; a walk that would mark the subject idle reads its newest such marker by the `--bot-login` and, when the named item's `updatedAt` is later than the hand, hands it again. A marker by anyone else counts for nothing. github-issue-triage's and github-pr-triage's hold comments now start with the marker (#1555)
- `shipmill status` and the watch name why the gate waits: `GATE_PAUSED <limit|auth> until <when>` while the credential its sessions use is paused, with the token's fix for `auth`, and `GATE_RETRY <item> after <time>: <n> error ends in a row` for each item in backoff; `shipmill status --item N` says the pause or the backoff for an item the gate would take up, instead of "the gate takes it up on a coming tick". Spec 089 is built (#1556)

### Changed

- Gate: an item whose headless session ended `error` is handed again 15 minutes after the death, then 1 hour after the next, then 4 hours after the third; the fourth `error` end in a row holds it for `retry_hours` and reads SESSION_DEAD, where three dead sessions in a row held it before. The run is kept on the item's hand in `handed.json` (`errors`, and `until` while it waits), so it survives another item's session in between, an `ok` end resets it, and a hand whose session ended `error` never turns idle (#1554)

## [0.167.0] - 2026-11-24

### Changed

- D-102 to D-104 record the maintainer's answers: a public write is checked for private repositories by name and an `[agents]` repo refuses public writes while the private terms file is missing (#1480), a relayed veto counts as the maintainer's own (#1482), and an agent never decides on its own on an item naming a CVE or GHSA id (#1483)
- Gate: a headless session is dead when its log's end is anything but `ok` (a usage limit, an authentication failure, or no result without an error), however long it ran, instead of when it ended within 60 s of its launch; a session a STALLED tick stopped is dead too. A hand whose session ended `limit`, `auth`, or `error` drops from `handed.json` on the tick that records the end, whichever session `gate.json` names by then, so its item is handed again, and only a hand whose session ended `ok` turns idle: hands already stuck idle behind sessions a usage limit stopped return to the queue on the first tick after the upgrade. A capped dead session's hands still hold its item for `retry_hours` until spec 089's backoff replaces that hold (#1551)

### Fixed

- A maintainer's veto relayed by a session through the App now stops a merge: the App's relay after an item's decided marker, in the relay grammar, naming the maintainer, whose answer line is `own: veto [<text>]` or starts with `veto`, reads as that maintainer's veto, so `triage_state.py` reads the item VETOED (naming the maintainer, read from the `--role maintainer` flag) and `pr_gate.py` holds the pull request until a veto-handled comment follows it; a relay naming anyone else, out of the grammar, or answering an option is no veto (#1482)

### Security

- `shipmill gh` refuses with exit 2 a comment holding the `shipmill:decided` marker on an issue or pull request whose body or comments name a CVE or GHSA id, or whose thread can't be read, and points to the needs-decision question instead, so a decision on a known vulnerability is asked whatever its zone's level (D-104, S-030-25) (#1483)

### Added

- `pr_gate.py` holds an agent's pull request that changes a file outside what its issues allow: the `Files:` lines of each named issue's newest `Triage: **implement**` or `Proposed plan:` comment by the `--bot-login` or a trusted person, written before the pull request opened, read with spec 061's grammar, the default branch's `[changelog] fragments` folder always allowed; such a pull request reads NEEDS_DECISION, exit 5, with `files: <path> is outside what #<n> allows` lines, and fails closed on a `Files:` line it can't read or a thread cut off at 100 comments (#1523)
- `chains.py show --json` says, on each row, how much open work waits on the item and what it waits for itself: `held` (every open issue that waits on it, directly or through others, across repos, each once, never itself), `held_direct`, `milestones` (the waiters' `owner/repo title`, sorted, each once), `waiting_for` (the first that applies of `decision`, `cycle`, `items`, `upstream`, `postponed`, `maintainer`, `person`, `pull request`, `no gate`, `agent`), and `idle_days` (whole days since the newer of the issue's `updatedAt` and its open closing pull request's); an untrusted, unreadable, or closed issue adds nothing to any count, and the table lines and exit codes are unchanged (spec 086) (#1526)
- `.github/shipmill.toml` takes an optional `[decisions.earned]` table (the lowest level a pull request may earn in `protected` and `security`, never below the zone's floor, and `max_lines`, 1 to 10000, default 200) and `[decisions] clean_releases` (1 to 20, default 3), and the zone table gains `area-record` after `protected`, defaulting to `act` with no floor; `shipmill decide levels` shows each zone's bound (`"earned"` in each JSON row, `null` without one), and a config without either key reads as before; nothing earns a level or reads an area's record yet (spec 083) (#1544)
- Gate: once a headless session is gone, each of its hands in `handed.json` records how it ended as `ended`, read from its stream-json log: `ok` (its last `result` has `is_error: false`), `limit` (an `api_error_status` of 429 or a rejected `rate_limit_event`), `auth` (an `api_error_status` of 401 or an authentication failure), or `error` (anything else, a session that ran past 60 s with no result included); a log whose events don't have the types Claude Code writes fails the tick instead of guessing, and a `handed.json` written before keeps loading; the watch reads the new field too. The end changes nothing yet: spec 089's later issues act on it (#1550)

## [0.166.0] - 2026-11-24

### Changed

- Specs 083 and 089 list their build issues, and D-101 records that a pull request in `protected` or `security` may earn a lower level within `[decisions.earned]` (#1305, #1512)

## [0.165.0] - 2026-11-24

### Changed

- Specs and tests describe their cases without naming private repos (#1480)

### Fixed

- Merge gate: a failed run of a lane's `dispatch` or `after_publish` workflow, dispatched on the default branch for a tag, no longer reads the branch red in `pr_gate.py` and `base_red.py`; every other failed run on the head still does (#1485)

## [0.164.1] - 2026-11-24

### Fixed

- The delivery hook's leak check no longer claims a leak when it refuses a `git push` of a branch the same Bash command creates, such as `git switch -c new && git commit -m x && git push -u origin new`: `shipmill leaks push` refuses a source ref that doesn't exist with an error naming it, and the hook, which reads the whole command before any part of it runs, says the ref doesn't exist yet and to run the commands before the push first; only a refusal with findings says to rewrite the unpushed commits, any other check that can't read the push says why, and the push stays refused with exit 2 either way (#1542)

## [0.164.0] - 2026-11-24

### Added

- A merge that completes an expedite outcome (the pull request that closed the last open sub-issue of an accepted opportunity whose `expedite` label a person added) makes the stable lane due at once with the reason `expedite #N complete`, or the rc lane when stable promotes, without waiting for `quiet_minutes` or a schedule window; every gate still applies, an outcome a release already shipped makes nothing due again, and a config without `[agents]` reads nothing new (spec 070) (#1253)

### Changed

- `shipmill decide classify --pr` puts a pull request that raises an `[autonomy]` stage's level (observe < propose < act, resolved as `shipmill autonomy` resolves it) in `decision-policy`, so it is `never` and the maintainer merges it by hand, whatever `security` is set to; a change that only lowers or keeps the levels stays `security` (D-99) (#1457)

### Fixed

- `move-major-tag.yml` no longer fails a release whose version PyPI's index lists a few minutes after the upload, with an error blaming `SHIPMILL_LAND_KEY`: before the App's token check it resolves the release's shipmill past uv's cache every 20 s for up to 10 minutes, and out of time fails naming PyPI's index, with nothing pushed; the token check's helper refreshes uv's cache too, and its error no longer names PyPI (#1470)
- `shipmill gh`: three posts the gate would discard exit 2 before anything reaches GitHub, each naming the fix: adding `needs-decision` to a pull request whose newest question doesn't name its current head on its `<!-- shipmill:head <sha> -->` line, a needs-decision question on a pull request without that line, and a relay out of the relay grammar (D-93), read by `pr_gate.py`'s and `retro.py`'s own readers, so the maintainer no longer answers a question twice (#1484)
- Triage: a hold that closed before an issue's newest triage comment no longer reads the issue UNBLOCKED on every pass; that comment decided it again, so it reads by its verdict and labels, while a sub-issue's close always counts (#1493)

## [0.163.2] - 2026-11-24

### Fixed

- github-pr-triage no longer leaves detached worktrees that `shipmill worktrees --prune` keeps forever: the second-look verifier checks out its own `review-<N>-verify` branch, with the PR's head branch as its upstream when it is in the repo, and a landing worktree, the stacked-branch recipe's included, holds a `land-<N>` branch, so the gate's prune removes them once their PRs land (#1513)

## [0.163.1] - 2026-11-23

### Fixed

- `test_proof.py` reads a plan's `Tests changed: none` (any case, alone or followed by prose such as `none; only new tests`) as naming no file instead of exiting 2; `none` on a line that also holds a backticked path, with or without its reason, still exits 2, and its message now says the line may be `none` (#1507)

## [0.163.0] - 2026-11-23

### Fixed

- A deploy proposal from `operate.yml` reaches the maintainer queue: given the App's private key as its new optional `SHIPMILL_OPERATE_KEY` secret, with `[agents] app_id` set, operate opens and updates the "Ready to promote" issue as the App, with a token limited to the repository and `issues: write`, instead of as `github-actions[bot]`, which the queue leaves out; without the secret nothing changes (#1371)
- An unknown key in `~/.config/shipmill/private.toml` is named by its line and the keys the file takes, never by its text: a table or key named after a private term no longer reaches a refused write's message, a refused push, or `shipmill doctor`'s `leaks` FAIL (spec 081, S-081-4 amended) (#1416)
- The setup checklist and github-ship-watch read the agent identity the owner recorded (D-98): with `[agents] identity = "host"` neither asks for an App any more, and `AGENTS_OK` names the host's login the gate's sessions write as; with `identity = "none"` and a gate prompt, setup reads a new `AGENTS_NO_WRITE` action and the watch's `GATE_NO_APP` says the same, since those sessions stop at their first write, so the agents row no longer contradicts the identity row (#1429)
- The merge gate holds a pull request as `BLOCKED`, naming the incident, while an open incident is on an environment's latest deploy; a revert or a hotfix still reads `READY`, and an incident from an earlier deploy holds nothing (#1481)
- `shipmill gh`: a comment whose first line relays a decision naming its person bare (`Decision by @<login>, relayed by <agent>`) exits 2 before anything reaches GitHub, its error showing the line with the login in a code span, so a relay no longer emails the person who already answered (D-61); readers still take both forms (#1491)
- Triage: a merged closing pull request no longer reads an issue DONE_NOT_CLOSED while one of its holds is still open; it reads BLOCKED, and a parent with a `## Check` reads VERIFY_DUE once its last child closes (#1492)

### Added

- `fleet.py overview` prints the fleet report's rows and the maintainer's queue in one pass: each repo is cloned once and the repos are read concurrently, at most `--jobs N` at once (default 4), in the fleet file's order (#1479)

## [0.162.2] - 2026-11-23

### Fixed

- `shipmill prune` and the gate no longer fail with `Fragment merged was defined, but not used` when a batch of merged pull requests holds only numbers: such a query now leaves out the fragment it does not use, so stale worktrees are cleaned up again

## [0.162.1] - 2026-11-22

### Fixed

- The gate's change check pages its open issues, pull requests, and incidents at 20 instead of 100, so each tick costs GitHub 1 rate-limit point instead of 6: GitHub charges a query by its worst-case requests, its nested labels, assignees, and links times their pages; `issue_updates` keeps its page of 100 (#1458)

## [0.162.0] - 2026-11-22

### Added

- Status: `shipmill status --item REF` prints the holder's step from the item's newest trusted hand-off (`step:`), every open issue that waits on it across repos with its bucket (`blocks:`), and the issues its open pull requests close (`closes:`), read beside the other reads so it is no slower; `--json` carries them as `step`, `blocks`, `blocks_error`, and `closes` (#1473)

## [0.161.2] - 2026-11-22

### Fixed

- `shipmill status --item REF` for an open issue or pull request takes about 13 to 14 s on shipmill/shipmill, from about 14 to 15 s: the App's bot login is read beside the item's own state, the item's own checks and review beside `watch_state.py` and `triage_state.py`, and `triage_state.py` and `watch_state.py` start as soon as the login is in hand; a closed or missing number still exits 2 at once, waiting on none of the other reads, and the output, stderr, and exit codes are unchanged (#1469)

## [0.161.1] - 2026-11-22

### Fixed

- `triage_state.py` takes about 12 s on shipmill/shipmill, from about 21 s, and `shipmill status --item REF` for an open issue or pull request about 14 to 17 s, from about 24 s: each answer's follow-up calls (an issue's older comments and cross-references, the postponed issues' tag compares, the decided pull requests) start on threads while the open issues are still paged, and the run reads every answer in its own order, so its output, stderr, and exit code are unchanged (#1469)

## [0.161.0] - 2026-11-22

### Added

- `watch_state.py --item N` prints only the full report's rows `shipmill status --item N` reads (HOLD, NEEDS_DECISION, PRS_OPEN, PRS_PARKED, and the agent and GATE_IDLE rows naming #N), exactly as the full report prints them, skipping the sections none of them can come from and reading the rest at once (#1469)

### Fixed

- `shipmill status --item REF` for an open issue or pull request takes about a third of the time it did (about 23 s, from about 62 s, on shipmill/shipmill): it passes `--item` to `watch_state.py`, so the chains, the deployments, the active runs, the work branches, the tags, and the other sections no row of the item comes from are no longer read; its output is unchanged (#1469)

## [0.160.1] - 2026-11-22

### Fixed

- `shipmill status --item REF` answers a closed or missing number at once from the item's own state, and for an open item reads only what its explanation uses: no launchd job, App check, gate CLI, prune or tick record, host sections, or agent-as-person search, with triage_state.py, the open pull requests, and the upgrades read beside watch_state.py; its output is unchanged (#1469)

## [0.160.0] - 2026-11-22

### Added

- Status: `shipmill status --item REF` says why one open issue or pull request is not closed, given by number or by its GitHub URL: the bucket the picture lists it on and every condition that keeps it open, each with who clears it (the maintainer, an agent, a person, or an event) and how; `--json` prints one object. A triaged issue on the `parked` line now shows what it was triaged as, such as `triaged: opportunity` (spec 088) (#1461)

### Fixed

- `land` on a lane with `after_publish` no longer exits 2 when GitHub answers 404 for the publish run it named on dispatch seconds before: it reads the run again every poll until the publish deadline, then fails naming the run GitHub never served, with the after_publish workflows left unstarted and the commands that start them; any other error reading the run still stops it at once (#1467)

## [0.159.0] - 2026-11-22

### Changed

- Product intake's `intake_state.py` reads its issues 70 to a page, its discussions, open pull requests, and comments 100 to a page, so a run on shipmill/shipmill costs GitHub 5 rate-limit points instead of 8, each query still 1: GitHub charges a query by its worst-case requests, one per connection times the nodes of the connections it sits in, so a smaller page only adds queries; every item, closed discussions and declined opportunities among them, is still read (#1459)
- `triage_state.py` reads open issues 20 a page instead of 100 on the first page and 50 on later ones, and the first query's closed decided issues 20 instead of 50, so its first query costs GitHub 2 rate-limit points instead of 8 and each later page 1 instead of 3: GitHub charges a query by its worst-case requests, an open issue's six nested connections times the page; every issue is still read, over more pages (#1459)

## [0.158.1] - 2026-11-21

### Fixed

- `setup_state.py`'s Identity row no longer stops setup with exit 2 when one sibling's config read fails with anything but 404 (a 5xx, a rate limit, SAML): it names that repo as `owner/name (unread: <reason>)` and the run goes on; the Product row, read with `[agents] app_id`, still exits 2 on such a failure (#1375)

## [0.158.0] - 2026-11-21

### Added

- A stable release by a lane with `close_milestone = true` closes the open milestone titled its version once tagged and published, first moving its open issues to the open milestone titled the lowest stable version above it; with open issues and no such milestone it writes nothing. A new `milestone` job in `land.yml`, after the land job, does it with `shipmill close-milestone`; it sets no permissions, so it runs with the caller's grant, and a lane without the key calls GitHub for nothing there. The Release run's summary says `milestone 1.5.0 closed; #12, #14 moved to 1.6.0`, and a milestone write that fails fails the `milestone` job after the release, naming the `shipmill gh api` command that does it (spec 068) (#1335)

### Security

- `shipmill gh` checks a write it can't place on a repo (a gh alias, an extension, an `--org`, `--owner` or `--user` form) as public, so a private checkout no longer lets a private term through to it (#1372)

## [0.157.1] - 2026-11-21

### Fixed

- `shipmill operate` comments a compare incident healthy again in an environment with probes and no `health`: once the environment's newest successful deployment runs a tag other than the one that answered differently, the incident reads healthy, where before it stayed open until a person closed it. A deployment still in progress ends nothing, and the incident's body says what ends it there (#1451)
- A compare incident in a repository whose environments declare probes but no `health` URL now holds the lanes in `[gates] blocker_lanes` as a health incident does, and `shipmill doctor` wants the operate caller, with `issues: write`, and a deploy workflow that starts it once an environment declares probes; a repository with neither reads as before (#1453)

## [0.157.0] - 2026-11-21

### Added

- `docs/release-lanes.md` documents comparing a deploy's answers: the `[[environments.<name>.probes]]` table and its limits, the deploy job's `environment: { name, url }` that GitHub Actions records as `environment_url`, the `Changes answers:` line, the three `shipmill compare:` statuses, and that an unexplained difference opens an incident at once and rolls back under `[autonomy] rollback`; `shipmill operate --dry-run` is tested to report the compare outcome it would write (`would mark`, `would open an incident`, the rollback) while writing nothing, and github-issue-resolve tells an implementer to add `Changes answers: <probe names>` to a pull request that alters an answer a declared probe covers (spec 084) (#1437)

## [0.156.0] - 2026-11-21

### Added

- A difference `shipmill operate`'s compare finds now counts: a `Changes answers: <probe>, <probe>` line in the body of a pull request merged between the two tags (named by its first-parent commit subject, read only when a difference holds) explains it with a `shipmill compare: differs from <tag> on <names>, explained by #N` success status; an unexplained one opens the environment's incident at once (`Incident: <env> answers differently on <tag> than <previous tag>`, naming each probe, its path without the query, both HTTP statuses, and at most ten differing JSON pointers, never a value), rolls back under `[autonomy] rollback` as a failed health check does, and writes a `failure` compare status that keeps the deployment from promotion and from being a rollback's target, while leaving the health count and the bake as they were; the incident reads healthy again only once another tag passes (spec 084) (#1436)

## [0.155.0] - 2026-11-21

### Added

- An environment in `[environments]` may declare up to 20 `[[environments.<name>.probes]]` (`name`, `path`, `ignore` JSON pointers); after a deploy passes its health check, `shipmill operate` sends each probe as a plain GET twice to the previous release's address and once to the new one's (each the newest `environment_url` its deployment statuses carry), compares the answers with the ignored pointers and the previous release's own noise removed, sends a difference once more, and writes one `shipmill compare: same answers as <tag> on <n> probes` success status when every counted probe reads the same; an environment without probes makes no request beyond its health check (spec 084) (#1435)

## [0.154.1] - 2026-11-20

### Fixed

- `shipmill gate`: a `needs-decision` question a session asked on a pull request and the maintainer answered while that session still ran is handed on the first tick after the session ends, instead of waiting out `retry_hours`; the tick drops the ended session's hand of each pull request the change check reads labelled `needs-decision` and updated since the hand, and leaves every other hand as it was, so a labelled pull request the session left untouched still waits (#1447)

## [0.154.0] - 2026-11-20

### Added

- A session handed the watch's BASE_RED row under `[autonomy] revert` propose or act follows four steps in github-pr-triage's `ci-failures.md`: re-run the failed run once, re-run the unjudged candidates' cancelled runs, `shipmill revert open` for a culprit or at most three revertable candidates, and otherwise ask on one `<!-- shipmill:base-red <branch> -->` issue per branch, closed once the branch reads green; under observe it only reports (spec 079) (#1296)

## [0.153.0] - 2026-11-20

### Added

- The watch reports a red default branch: a `BASE_RED <branch>@<sha7>` row, first in tier 2, for every reading of `base_red.py` but GREEN, and `green again, close #Q` while its question is open, each with a fix and an agent's row only under `[autonomy] revert` propose or act; the gate's change check reads the default head's check rollup in its one query, so a check failing on an unchanged head makes the tick walk (spec 079) (#1292)
- `shipmill revert open <PR>... --run <URL>` backs out the merges that turned the default branch red (spec 079): it checks first and writes nothing when `[autonomy] revert` is `observe`, the App isn't available, `--run` names no failed check of the default head, a pull request isn't the App's untagged merge, or an open pull request already repairs the run; then, as the App, it pushes `revert/<N>-<sha7>` with one revert per pull request, newest first, opens its pull request labelled `revert` with `Reverts #N`, `Repairs:`, and a plan, and reopens each issue a reverted pull request closed with one `<!-- shipmill:reverted #N by #R -->` comment (#1294)

## [0.152.0] - 2026-11-20

### Added

- An expedite outcome is taken first (spec 070): with `[agents]`, `watch_state.py --tier 3` and `--tier 6` mark as expedite the rows naming an accepted opportunity whose `expedite` label a person added, one of its sub-issues, or a pull request closing one, and the gate's walk takes them before every standard row of the tier; `triage_state.py --wip N` lists those issues first among the ready ones and counts them in progress like any other (#1250)
- Merge gate: `skills/github-pr-triage/scripts/base_red.py` reads a red default branch from GitHub and the merges that may have turned it red: GREEN, RERUN_DUE with each first-attempt run to re-run, CULPRIT or CANDIDATES from each failed check's last green and first red on the first-parent history (each candidate's pull request and whether it is revertable: merged by the `--bot-login` and in no tag), or NO_GREEN, then the open repair pull requests and the question issue; a check rerunning after a failure reads PENDING, never GREEN, as `pr_gate.py` reads it (#1288)

## [0.151.0] - 2026-11-19

### Changed

- Docs: spec 082 (whom agents write to GitHub as is chosen once per repo, at setup) is built, each criterion verified on the default branch (#1235)

## [0.150.0] - 2026-11-19

### Added

- `fleet.py queue` lists an open spec pull request that nothing lands by itself as a `SPEC_TO_MERGE` row, read with `pr_gate.py`'s readers: no question waiting, no trusted answer taking every recommendation, and no App decided comment at `accepted-spec`, or one that edits the product's direction; github-ship-watch's Fleet section documents the queue, its rows, and a `/schedule` routine for it; spec 069 is built (#1246)
- In a component (`[product] home`), triage, product intake, and the PR reviewer treat a non-goal of the product as the component's own: a request that hits one is **won't fix** citing `<owner/home> N-n`, an opportunity says `hits <owner/home> N-n` on its `Serves` line and is never proposed on demand, and a change that hits one is a review finding; while `shipmill product show` can't read the home's direction, none of them gives a verdict, opportunity, or finding on new behaviour (#1256)
- A PR reviewer's REFUSE gets a second look before it is recorded or handed back: the reviewer lists each unfixed finding as `F-n`, `blocking` or nit; a fresh agent, given the blocking findings and not the verdict, marks each `confirmed` with a failure scenario, `rejected` with the code that handles it, or `minor`; the PR is refused only on a confirmed finding, the record carries a "Second look" part and `--findings` counts, and the weekly retro passes `--reviews` (#1279)
- `shipmill doctor` prints one `identity` row in every repo: with `[agents] app_id`, a PASS naming the App's id, `<slug>[bot]`, and the repo when the token minted for the repo reads it, a FAIL naming the installation page and `shipmill app-install <owner/repo>` when it can't, and a WARN when the key isn't on this host; without it, a PASS for `identity = "host"` or `"none"`, a WARN naming the three choices and the setup line when nothing is recorded in an `[agents]` section, and a PASS without one. Doctor writes nothing (#1281)
- The weekly retro proposes a review finding that recurs across two or more pull requests once, as a rule or check in the strongest place the repo's CI can hold it, shown failing in a throwaway worktree and checked with `retro.py proposal`, filed as the App with the `rule-proposal` and `needs-decision` labels (new `skills/github-ship-watch/references/rule-proposal.md`); triage takes up the answer as a person's item or a decline, shipmill writes none of the rule, and `setup_state.py --fix` creates the `rule-proposal` label for a repo with `[agents]` (S-077-10 to S-077-14) (#1284)
- The watch's full report, for a config with `[trends]`, runs `trends.py` and adds a DRIFT row for each series at the `report` tier, with its diagnosis and the `trends.py` command as its fix; the row is reported and never acted on: it leaves the exit code as it was, no `--tier` or `--sweep` read prints it or runs `trends.py`, and `--no-trends` leaves the read out. `fleet.py report` lists it among a repo's report-only rows, and github-ship-watch's skill documents the four agent quality measures and a new Trends section (S-078-16 to S-078-18) (#1295)
- `shipmill doctor` prints the `merge-checks` lines as a row in a repo with `[agents]`, judged at the configured `[autonomy] land`: the status checks a merge to the default branch requires and what each one's jobs prove, a WARN under `act` when none proves anything, which never changes doctor's exit code; shipmill-setup's Autonomy step shows `merge-checks --land act` beside the `land` choice and its warning beside every option that sets `land = "act"` (spec 080) (#1299)
- Leak check: `shipmill leaks check [--repo DIR] [--to owner/name] [--field NAME] [FILE]` runs the detectors over a file or stdin and exits 2 with the findings, 0 with any warnings otherwise; `shipmill spec open` and `shipmill review record` check their `--body-file` before their first write, and `spec open` checks the commit it pushes, which no hook sees (#1318)

### Fixed

- `fleet.py report` and `queue` read a `PRS_OPEN` row that carries its pull requests' heads instead of refusing it as not a row (#1246)

### Changed

- shipmill-setup asks "Whom do agents write to GitHub as in this repo?" once, only while the Identity row reads `IDENTITY_UNCHOSEN`: the App (recommended, the row's App or `shipmill app-create`, written as `app_id` only after `shipmill app-install <owner/repo> --app-id <id> --check` exits 0), the owner's login with its warning, or nobody, and installs no gate for `host` or `none`. The "Write as the App" rule of the six skills now runs every write as `shipmill gh` and `shipmill app-token --check` before the first write in every repo, whatever the config sets; on the owner's choice (`identity = "none"`) a skill stops, says so, and hands over each write's text with its target, never passing `--as-host`; no instruction file's prose decides the identity. `docs/install.md` documents the three values, the setup question, that `identity = "none"` refuses `--as-host` too, and what an App on All repositories reaches and grants (#1282)

## [0.149.2] - 2026-11-19

### Fixed

- A component whose product home can't be read no longer stops the weekly retro or product intake's plans: `retro.py --goals` and `intake_state.py --plans` read the repo's own goals with `shipmill product show --local`, as they only ever used those, and every failure of `product show` still exits 2 (#1417)

## [0.149.1] - 2026-11-19

### Fixed

- In a headless gate session the delivery hook's uv-run rule also refuses a `test_proof.py` call whose command after `--` runs a program the headless allowlist doesn't (`gh`, `git`, `uv`, `uvx`, as written), so `-- sh -c ls`, `-- env X=1 uv run pytest`, and `-- npm test` no longer start a program past the allowlist; `-- uv run pytest tests/test_a.py` and `-- git status` still pass, and an interactive session is unchanged (S-076-11) (#1406)
- A `~/.config/shipmill/private.toml` that isn't valid TOML no longer prints a private term: the error every refused write, push, and `shipmill doctor`'s `leaks` FAIL show names the file's line and column instead of the parser's message, which quoted the file's keys, and a file that isn't UTF-8 names only the byte offset (#1407)
- The watch checks a component's direction with `shipmill product check --local`, its own `docs/product.md` only, so a product home it can't read no longer stops the whole watch (#1408)
- `fleet.py queue` passes each clone's roles, as `shipmill roles --flags` prints them, to `triage_state.py` and `intake_state.py --plans`, so a goal plan the maintainer answered through a relayed decision (D-68) leaves the queue; a failed roles read is that repo's REPO_ERROR line (#1409)
- github-pr-triage's reviewer brief rebases a pull request onto its own base branch (`{base}`, its `baseRefName`) and runs `test_proof.py` with `--base origin/{base}`, so a pull request stacked on another is read from its own commits and its base pull request's first commit is no longer taken for its test commit; an unstacked pull request's base is the default branch, as before (#1410)

## [0.149.0] - 2026-11-19

### Added

- `fleet.py queue` lists a person's item handed to the reader (`--login`, else `gh api user`'s login) as a `YOUR_ITEM` row from `triage_state.py`, and an opportunity waiting for accept or decline, an open goal plan, and an opportunity declined with no reason as `OPPORTUNITY`, `PLAN`, and `NO_REASON` rows from `intake_state.py` (with `--plans` when the repo has `docs/product.md`), each with how long it has waited; the kind column is one character wider to fit `OPPORTUNITY` (#1245)
- In a component (`[product] home`), `shipmill product show` adds the product's goals and non-goals from the home's `docs/product.md` on its default branch, under `## Product goals (<owner/home>)` and `## Product non-goals (<owner/home>)` and as a `product` key in `--json`, and `shipmill product check` refuses a serves line naming a goal the home's Goals don't list; both read the home through spec 065's read token and exit 2 naming the home and the fix when they can't, `--local` reads only the checkout as before, the delivery hooks run `product check --local`, and shipmill-setup asks which product goal each component goal serves (spec 071) (#1251)
- `shipmill review history <N>` lists settled decisions and incidents too: the needs-decision questions answered by a trusted person (the answer cut at 600 characters) and the decided comments, with whether a veto followed, on the pull requests that touched a touched file, and the issues labelled `[operate] incident_label` and the postmortems under `docs/postmortems/` changed in the window that name a touched file or its directory (#1254)
- The PR reviewer's brief carries the touched area's history from `shipmill review history <N>`: for each `H-n` the reviewer says `contradicts`, `consistent`, or `unrelated`, reports a `contradicts` the PR doesn't explain as a finding citing it, and adds a History part to its final report; a pack with nothing in it drops all three (#1257)
- github-ship-watch runs `intake_state.py --json` once per repo, with `--plans` only when the checkout has `docs/product.md`, and reports two new rows (spec 074): SPEC_DUE names every accepted opportunity for triage's spec gate, and FEEDBACK_DUE names the requests triage handed to product intake at least 24 hours ago, for one intake pass. Both are in the gate's tier 7 and its sweep, so `shipmill gate` starts those sessions; FEEDBACK_DUE is report-only under `[autonomy] intake = "observe"`, an outsider's request or opportunity goes to UNTRUSTED under `--trusted-only`, and `shipmill status` lists both rows with their fix (#1258)
- `retro.py gather --reviews` counts the `--bot` logins' review records of the window, read from GitHub alone: the refusals `verified` by a second look (a findings line right after the marker) or `unverified` (with their pull requests), the merges with a findings line as `overturned`, the confirmed, rejected, and minor totals, and `first_reviewer_wrong`, the percent rejected, rounded down, or `no data`; `--json` holds them under `reviews` (#1275)
- `retro.py proposal <body-file> --repo <owner/repo>` checks a rule proposal's body before the retro files it: exit 2 naming the first fault of its format (the marker, the Rule, Raised in, and Place sections, and for a check place the check, its failing run, and the default branch; for prose, Why prose), exit 1 with `DUPLICATE #N (<state>)` when the rule was proposed before in any state, declined included, or `FULL: K proposals wait on an answer` when `--max-open` (3) proposals wait on the maintainer, exit 0 printing the title (#1280)
- In a headless gate session the delivery hook reads the command after a `test_proof.py` call's `--` (run directly, through `python`, or through `uv run`) as a call of its own and refuses the whole call when the uv-run rule (D-82) would refuse that command, so `test_proof.py fix ... -- uv run sh` is refused and `-- uv run pytest tests/test_a.py` passes; an interactive session is unchanged (S-076-11) (#1285)
- A pull request's `## Plan` may say `Kind: fix` or `Kind: refactor` and name the existing test files it had to edit on a `Tests changed:` line; github-issue-resolve commits a `Kind: fix` change's test first and alone and leaves existing test files alone in a `Kind: refactor` change, and github-pr-triage's reviewer runs `test_proof.py <kind>` on a plan with a `Kind:` line, reporting `UNPROVEN` and a `NO_TEST` fix as findings, `BASELINE_RED` as the base's failure, and a "Test proof" line in its report; `pr_gate.py` reads neither line (spec 076) (#1286)
- A goal can be measured by the agent quality measures: `first_pass_merge_rate` and `plan_match` with a `%` target, `review_time_median` and `review_time_p90` with an `h` or `d` target; `shipmill product check` refuses each in another unit, the weekly retro reads them from `metrics.py`, and shipmill-setup offers them (#1291)
- A drift report for CI and review (spec 078): the github-ship-watch skill's new `trends.py <owner/repo> --repo-dir <dir> [--until TIME] [--json]` compares the newest bucket of each series in a new `[trends]` section of `.github/shipmill.toml` (`ci_pass_rate`, `flaky_reruns`, `review_time`, `lead_time`) with the buckets before it, and reads `no data`, `ok`, `log`, or `report` by its distance from their mean in sample standard deviations, naming the workflows or pull requests behind a drift; the config reads `[trends]` strictly and `shipmill doctor` prints one line for it. Off without the section (#1293)
- `shipmill merge-checks [--land observe|propose|act] [--json]` prints the status checks a merge to the default branch waits for, from its rulesets (by name) and classic protection, each matched to the pull-request workflow jobs that report it and with what their commands prove (tests, type check, lint, import boundaries, or only a build); under `land = "act"` its last line warns when no check is required or none that is required proves anything, naming the unrequired jobs that would, and a rules or protection read that fails is a warning at every level; a step under `continue-on-error` or in a shell other than bash or sh proves nothing (spec 080) (#1298)
- `shipmill gh`'s leak check also runs the outgoing text through `gitleaks stdin` when gitleaks 8.19 or newer is on PATH, with its default rules alone, in an empty folder of its own and with `--ignore-gitleaks-allow`, so a `gitleaks:allow` comment, the checked repo's `.gitleaks.toml`, or a `GITLEAKS_CONFIG` variable passes nothing, and refuses each of its findings as `secret-format`; without it the built-in formats alone decide. A string of 32 or more characters that looks random (a letter and a digit, not hex only, 4.0 bits per character or more) outside a lock file prints a `shipmill leaks: warning:` line, at most 5 and then `and N more`, and the write goes on (#1316)
- `shipmill leaks push --repo <dir> [--all|--branches|--tags|--mirror] [<remote> [<refspec>...]]` exits 2 naming each finding in what a `git push` would send: each commit reachable from the pushed refs and from no remote-tracking ref of the remote, read by itself against its first parent (its message, the paths it adds, changes, or renames to, and its added lines, binary files left out), and the destination ref names; a private term counts only when the remote's repo is public, and a secret's value or a known format is still refused when a later unpushed commit removes its line. The plugin's delivery hook gains the `leaks` rule: a `git push` in a repo with `[agents]` that the other rules allow runs the pinned `uvx shipmill==<version> leaks push` with the push's remote, refspecs, and flags, and is refused with its findings when it exits 2, and also when it can't run or doesn't finish in 45 seconds; no other command starts it, and the Bash PreToolUse hook's timeout rises from 10 to 60 seconds (#1317)
- `shipmill doctor` prints a `leaks` block in a repo with `[agents]`: `terms` with how many private terms `~/.config/shipmill/private.toml` lists (never a term), or off, a WARN when the repo is public; `secrets` with each secret file and how many values it gave (never a name or a value); `scanner` with gitleaks' version or its absence; and a FAIL naming the fix for a private file that doesn't load. `docs/leaks.md`, linked from `docs/install.md`, documents the private file, the four detectors, and both refusals (spec 081) (#1319)
- `shipmill doctor` prints a `merge` row in a repo with `[agents]`, naming the method a pull request lands with and where it comes from (`default` or `[agents] merge`), and warns naming the repo setting when GitHub doesn't allow that method, when merge commits are off under `"squash"`, or when the settings can't be read; its `hooks` block gains a `merge-method` line and its `rebase-merge` line names D-96. github-pr-triage's landing rules, `docs/flow.md`, and `docs/release-lanes.md` name `[agents] merge` and D-96, and a method the repo doesn't allow is reported, never swapped for the other (spec 072) (#1345)

### Changed

- `pr_gate.py` says which refusal it reads: a refuse record whose line right after its marker is `<!-- shipmill:findings confirmed=N rejected=N minor=N -->` reads `unreviewed: ... refuses it on N confirmed finding(s)`, and one without that line, or with one it can't read, reads `refuses it on findings no second reviewer checked`; both stay UNREVIEWED with exit 9, and a merge record reads READY with or without the line (#1274)
- `shipmill gh`, `shipmill spec open`, and `shipmill app-token --check` read `[agents] identity = "none"`: a write exits 2 saying the repo's owner chose that agents don't write to GitHub here and to hand the text to a person, `--as-host` included, while a read still runs as the host's `gh` login; a write in a repo that chose no identity names the three choices (`app_id` from `shipmill app-create`, `identity = "host"`, `identity = "none"`) and `/shipmill:shipmill-setup <owner/name>`; and `app-token --check` without `app_id` exits 0 for `identity = "host"` (spec 082) (#1278)

## [0.148.2] - 2026-11-19

### Security

- `intake_state.py` reads a `Triage:` comment only from an OWNER, MEMBER, or COLLABORATOR or the `--bot-login` in its other readers too, so anyone else's `Triage: **feature**` no longer makes an accepted opportunity read HANDED_OFF, their `Triage: ... Serves: G-n` no longer marks a goal served and holds back its PLAN_DUE, and a decline reason skips only a trusted triage comment (#1384)

## [0.148.1] - 2026-11-19

### Fixed

- Delivery hooks: a `gh api graphql` `mergePullRequest` or `enablePullRequestAutoMerge` mutation is held to the merge method too, its `mergeMethod` read from the query, a `-f`/`-F` variable, an `-F @file`, or an `--input` body: `REBASE` is refused always, `SQUASH` under `[agents] merge = "merge"`, and a mutation or query the hook can't read, such as one on stdin, is refused (#1373)
- `retro.py findings` reads the reviews, review threads, and conversation of up to 50 closed pull requests per GraphQL query instead of two or three REST reads per pull request, paging on alone only a connection longer than its page, so a 28-day window over hundreds of pull requests takes a handful of queries, not hours; the findings it lists are unchanged (#1376)
- `watch_state.py --sweep` and `--tier 5` or `--tier 7` no longer read the accepted opportunities' classes of service, whose rows none of them prints; the full report and `--no-host` still read them once (#1377)

### Security

- `intake_state.py` counts a `Triage:` comment only from an OWNER, MEMBER, or COLLABORATOR or the `--bot-login`, which it now takes without `--plans` too, so anyone else's `Triage: **postponed**` no longer hides a request from intake and their `Triage: **opportunity**` no longer marks one `handed` (#1374)

## [0.148.0] - 2026-11-19

### Added

- github-ship-watch's `fleet.py queue --fleet <file>` lists what waits on the maintainer across the fleet in one list, oldest first: unanswered `needs-decision` questions (`QUESTION`), pull requests labelled `shipmill-ready` to merge (`TO_MERGE`), and "Ready to promote" proposals (`PROMOTION`), each with its repo, `#N`, what is asked, and how long it has waited, with the watch's trust (`--bot-login`), `--json`, a REPO_ERROR line for a repo it can't read, and exit 0 when empty, 1 with a row, 2 on a failed read; it reads only (spec 069) (#1244)
- An accepted opportunity has a class of service, read from the `expedite` or `fixed-date` label a person added to it (one the App added counts as none), and with `[agents]` `watch_state.py` reports `CLASS_CONFLICT` for one labelled both, `FIXED_DATE_AT_RISK` for a fixed date due in 2 days or less with work open, and `FIXED_DATE_NO_DATE` for one whose milestone has no due date; `shipmill status` lists them as waiting on you, and the gate starts no session for them (#1247)
- A component's goal names the product goals it serves on a `  serves: G-n[, G-n ...]` line under its item or measure line: `shipmill product check` refuses a misplaced or malformed one, and any in a repo whose config sets no `[product] home`; `product show --json` gives each goal a `serves` list; `shipmill product serves G-n <ids>` writes it and `--clear` removes it; `product check` and `product show` take `--local`; and the skill scripts read a direction holding the line as before (spec 071) (#1248)
- `shipmill review history <N>` prints the history of the files a pull request touches: reverts on the default branch within `--days` (commits that revert a commit, and merged pull requests with a `Reverts #M` line) and the other open pull requests sharing a file, each with an id `H-n`, at most `--limit` per kind, `--before <sha>` to read it as it stood at a commit, `--json`, and an untrusted author's text left out (#1249)
- With `[agents]`, shipmill-setup's `setup_state.py` wants the `expedite` and `fixed-date` labels, the classes of service the maintainer adds to an accepted opportunity, so `LABELS_MISSING` names them until they exist and `--fix` creates them; product intake's opportunity comment names them beside `planned`, and the spec gate files build issues with no class label (#1255)
- `shipmill review record --findings confirmed=N,rejected=N,minor=N` writes the second look's finding counts on the line after the verdict's marker, and refuses a refusal with nothing confirmed or a merge with a confirmed finding; without the flag the record is as before (#1272)
- `[agents] identity` takes a third value, `"none"`: agents don't write to GitHub in this repo, refused beside `app_id` as `"host"` is; shipmill-setup's `setup_state.py` reads the same three values and prints one Identity row (`IDENTITY_APP`, `IDENTITY_HOST`, `IDENTITY_NONE`, or `IDENTITY_UNCHOSEN`, which names the Apps the host already has: a key file in `~/.config/shipmill/`, never opened, and the owner's other repos' `app_id`), an action only with an `[agents]` section (#1273)
- `shipmill app-install <owner/repo> --app-id <id> --check` opens no page and waits for nothing: it mints the token the gate's preflight mints for the repo and reads the repo with it, exiting 0 with `App <id> (<slug>[bot]) can read <owner/repo>`, 1 naming the repo, the App's installation settings page, and `shipmill app-install <owner/repo>` when the App isn't installed or can't read it, and 2 for a missing or open key or GitHub out of reach; the token is neither printed nor cached, and `--json` prints `app_id`, `slug`, `repo`, `reads`, and `page` (#1276)
- `retro.py findings <owner/repo>` lists what reviews raised on the pull requests closed in the last `--days` (28 by default): the App's review records, trusted people's change requests and inline comments, and the comment that closed an unmerged pull request, each with an `F-n` id, its head, and the rule ids it cites, then every `rule-proposal` issue as open, accepted, or declined; outsiders' and agent-marked text is left out (#1277)
- github-pr-triage's `test_proof.py` reads a fix's or a refactor's proof from its pull request's history: a fix's test committed first and alone fails on its own commit and passes on the head with its lines kept, and a refactor leaves the base's test files as they were on a green base; it runs only git and the test command given after `--`, in a temporary detached worktree it removes on every outcome (spec 076) (#1283)
- Autonomy: `[autonomy] revert` (`observe` by default, `propose`, or `act`) sets how far shipmill backs out a merge that turned the default branch red; `shipmill autonomy`, `shipmill doctor`, and `shipmill status` print it, an open `shipmill-hold` reads `act` as `propose`, setup's checklist wants the `revert` label once it isn't `observe`, and `pr_gate.py` holds the App's revert pull request (a `Reverts #N` and a `Repairs:` line) as BLOCKED for a person to merge below `act` (#1287)
- `metrics.py` measures how agent pull requests land: Rework cycles, First-pass merge rate, Review time, and Plan match follow Agent share, over the agent pull requests merged in the window, each "no data" when there is nothing to measure (#1289)
- `triage_state.py` reads an issue a revert reopened as work again: with the `--bot-login`'s `<!-- shipmill:reverted #N by #R -->` comment, the merged #N no longer makes it DONE_NOT_CLOSED while #R stands; it reads BLOCKED while #R is open and its other state, with `#N:reverted` in its note, once #R merged (#1290)
- A workflow job's `run:` commands are read and sorted into tests, type check, lint, import boundaries, build, or unknown, past `uv run`, `npx`, and the other wrappers and through a `package.json` script, the reading `shipmill merge-checks` builds on (spec 080) (#1297)
- `shipmill gh` refuses a write, with exit 2 before gh runs, whose title, body, field, or file names a private term from `~/.config/shipmill/private.toml` and goes to a public repo, or holds a secret's exact value from the checkout's untracked `.env` files or the file's `secret_files`, or a GitHub, Anthropic, AWS, or Slack token, a PEM private key, or a URL with a password, in any repo; the refusal names a term, but a secret only by its variable and file or its format and first 4 characters, and nothing turns the check off. A text gh would read from stdin is read and checked first, then fed to gh's stdin with its arguments as given, per spec 081 (#1315)
- A lane with `milestone = true` may set `close_milestone = true` in `.github/shipmill.toml`, `false` when absent; a value that isn't a boolean, or `true` on a lane without `milestone = true`, stops the config naming the key and the lane, and `shipmill doctor` warns when a lane sets it and the caller's land job grants no `issues: write` (spec 068) (#1332)
- `shipmill milestones` reports MILESTONE_RELEASED for an open milestone its tagged release shipped, with the command that closes it, and MILESTONE_MISSING when no open milestone is above the newest stable tag, naming the next version and the command that creates its milestone; a milestone whose open issues each carry `shipmill-hold` or `needs-decision` reads MILESTONE_WAITING with one reason per issue, and `shipmill plan` names them (spec 068) (#1333)
- shipmill-setup's `setup_state.py` wants the `opportunity` and `planned` labels for a repo with `[agents]`: LABELS_MISSING names them and `--fix` creates them, and the setup skill's Milestones row offers `close_milestone = true` with `milestone = true` (#1334)
- github-ship-watch reads spec 068's milestone rows from `shipmill milestones`: MILESTONE_RELEASED, an action whose close a watch pass runs once as the App, and MILESTONE_MISSING, reported with the create for the maintainer and never run (D-32); `shipmill status` waits on the close and lists both on its milestone line (#1336)
- `[agents] merge` in `.github/shipmill.toml` picks the method a pull request lands with, `"squash"` (the default, and with no key) or `"merge"`; any other value fails to load. `shipmill gh pr merge` (and the merge API through it) reads the repo's `allow_squash_merge` and `allow_merge_commit` before a merge that names `--squash` or `--merge`, and exits 2 naming the repo setting, and the key when it names that method, rather than landing with the other method; under a trailer setting, the refusals that name a merge command name the setting's method, and `--merge` writes the body of GitHub's `merge_commit_message` before the Co-authored-by trailers (spec 072, D-96) (#1343)
- The plugin's delivery hook reads `[agents] merge` and gains the `merge-method` rule: under `"merge"` it refuses `gh pr merge --squash` (or `-s`, bundled too, through `shipmill gh` as well) and a `gh api` merge with `merge_method=squash`, naming D-96 with the `--merge` command to run instead; under `"squash"` or no key both methods pass, so a stack's base still takes `--merge`. The `rebase-merge` rule cites D-96 and its `Instead:` line takes the setting's method, and a malformed `[agents] merge` refuses every guarded command with the config's error (spec 072) (#1344)

### Changed

- product-intake's `intake_state.py` no longer reads an issue triage postponed as a request to group, until a newer triage verdict hands it over, and each NEW_FEEDBACK and ACCEPTED line of its `--json` output now carries the opener's `author` and `association` and `handed`, when triage handed the issue over (#1252)

## [0.147.2] - 2026-11-19

### Fixed

- `shipmill gh issue|pr edit` reads the App's relay against the needs-decision question it guards, a person's when an OWNER, MEMBER, or COLLABORATOR asked after the App, so a counted relay to that question lets `--remove-label needs-decision` run and refuses `--add-label`, and an uncounted one is refused with its `Relay not counted` reason (#1340)

## [0.147.1] - 2026-11-19

### Fixed

- Merge gate: a thread cut off at its newest 100 comments no longer reads READY when they hold a trusted veto whose decided marker is older than them; the pull request reads BLOCKED with a `decided: the thread of #N is cut off at 100 comments: a veto in it can't be ruled out handled or not, so a person looks` line, while a complete thread, or a cut-off one with no unanswered veto in the window, reads as before (#1330)
- `shipmill gh issue edit` and `shipmill gh pr edit`, as the App, refuse with exit 2 to add the `needs-decision` label when a person's reply, a relay by the App (counted or not), or a `<!-- shipmill:withdrawn -->` comment already follows the item's newest needs-decision question, naming what came and asking for a new question first, so after a relay that isn't counted the label goes back on only with the re-ask D-93 requires (#1331)

## [0.147.0] - 2026-11-19

### Fixed

- Merge gate: a trusted veto of a decision taken at notify, on the pull request or on an issue it closes, reads BLOCKED with a `decided: vetoed by @<login> at <time>, not handled` line until a veto-handled comment answers it, read as triage_state.py reads VETOED (#1309)
- Merge gate: a base check rerunning after it failed on the base's head reads PENDING with a `base: pending: <check> rerunning on <base>@<sha7>` line instead of letting a pull request read READY, so landing resumes only once the rerun is green (D-75); the base's check runs are read with every attempt, in the same one read (#1310)
- `pr_gate.py` compares every `approved` or `built` spec a pull request modifies with `specs.py same-approval`, base against head, so a code pull request that changes an approved spec's Behaviour reads NEEDS_DECISION with `spec: <file> changes approved Behaviour` until the maintainer's answer; a change to its format, `status:` line, Issues, or Verification alone keeps the verdict (#1311)
- `shipmill roles` and `shipmill status` work in a gate session on a repo whose `[agents.roles]` lists no maintainer: they read the gate's `SHIPMILL_MAINTAINER` before `gh api user`, which answers 403 under the App's installation token, and a malformed value exits 2 naming the variable; outside the gate the host's `gh` login is read as before (#1314)

### Changed

- `shipmill gh issue edit` and `shipmill gh pr edit`, as the App, refuse with exit 2 to add the `needs-decision` label to an item carrying no needs-decision question, and to remove it before a person's reply, a relay the relay grammar counts, or a `<!-- shipmill:withdrawn -->` comment follows the newest question, each naming the comment that would satisfy it; a maintainer's "not now" is a postpone with the `postponed` label (#1312)
- `pr_gate.py` refuses a pull request whose title, commit, or body has a closing keyword naming another open pull request (`closes #N, an open pull request`), or whose title or a commit writes a Dependabot alert as `#N` (`writes Dependabot alert #N: write alert N or its URL`), since GitHub reads that `#N` as the repo's own issue or pull request and its merge closed unrelated ones; github-issue-resolve and the implementer brief tell agents to write `alert N` or the alert's URL (#1321)

### Added

- `triage_state.py` reads an open person's item (labelled `role:<name>` or `human`) whose sub-issue parent closed as STALE_HANDOFF, an action noted `parent owner/repo#N closed`, until a trusted `<!-- shipmill:still-waits -->` comment after the close; `watch_state.py` lists it in an ISSUES row whose fix is "close it or say why it still waits on the maintainer"; and `shipmill gh issue close`, as the App, refuses with exit 2 to close an issue with an open person's sub-issue, naming it (#1313)

## [0.146.2] - 2026-11-18

### Fixed

- Triage: a relayed answer out of its grammar on an item with the `needs-decision` label off reads RELAY_REFUSED, an action the gate hands in tier 6, so a session asks again; the watch's upgrade and direction rows say `relay not counted: <reason>; ask again` instead of taking it as answered (#1302)

## [0.146.1] - 2026-11-18

### Fixed

- Every reader of a relayed answer now follows the relay grammar: triage reads a relay out of its grammar as NEEDS_DECISION with the note `relay not counted: format` instead of DECIDED, product intake stops reading a plan relay at its `Note:` line, and the format check compares the words after an option's number with punctuation stripped, so `1. <option>: more` and `1. <option> and more` get the same reason (#1261)
- The github-pr-triage gate's `pr_gate.py` keeps a maintainer's answer, and the decided comment of an accepted spec, on a spec pull request rebased with the `D-n` it claims renumbered: it reads the decisions log by entry against each head's own merge-base, with the claimed ids mapped old to new as `specs.py same-approval` maps them, and the lines in the PR's other files citing them too, so it no longer asks `answered at <sha7>, and the change differs since` again; a changed entry, an edit to an existing one, a second new entry, or a line citing another decision still differs (#1265)

## [0.146.0] - 2026-11-18

### Changed

- A relayed answer is read by one relay grammar: lines after a `Note:` line are not read, a `Basis:` line is recorded only, and `own: <text>` is the maintainer's own words; a relay with any other line past its answer is no longer read as the maintainer's own words but refused with `needs-decision: relay not counted: format`, and the session that asks again says why under the question's zone line. A direct reply and a one-line relay take the same options as before (#1222)

## [0.145.0] - 2026-11-16

### Changed

- Spec 054, landing as the App on a protected default branch, is built: shipmill's own v0.144.0 landed, tagged, and published as the App past a ruleset requiring a pull request and the `check` status, and a test pins the ruleset `shipmill ruleset` prints for this repository (#1082)
- github-issue-triage holds an issue on another issue with `chains.py link --blocked-by` before it posts the hold sentence, for an accepted opportunity's request, a hold "decided in" an issue, a postpone that waits on an issue (in place of a hand-written `Depends on` line), and a DECIDED reply that says the item waits on an issue, so the blocked-by relation and the body's `Depends on` line show the hold in GitHub's dependency view and to tools outside the gate; a hold on or naming a pull request stays the sentence alone, a link refused for closing a cycle (a part held on its own parent) posts no hold line either, and in a component a wait on another repo's item still goes through a local stand-in (#1205)

## [0.144.0] - 2026-11-16

### Changed

- shipmill's own releases land through the `shipmill-land` environment as the App, so `main` can be protected by a ruleset whose only bypass actor is the App (spec 054, #1180)

### Fixed

- A release workflow opted in to landing as the App now passes its `land` job `secrets: inherit`, so `land.yml` reads the `shipmill-land` environment's `SHIPMILL_LAND_KEY`: without it a called workflow saw the secret empty and no stable release landed. `shipmill init --caller --land-as-app --force` writes it; a caller written before needs the line added (#1180)
- `shipmill worktrees --prune` no longer keeps a merged pull request's worktree forever when its branch is a local `review-<N>`, `push-<N>`, or `land-<N>` with no upstream, or when its commits are a local rebase of the pull request's that was never pushed: it finds #N by the number in the name and matches each commit by patch id against the pull request's commits, so a commit with a change the pull request never had still keeps the worktree, per D-91 (#1207)
- `shipmill worktrees --prune` and the gate's prune no longer remove a worktree whose unpushed commit differs from a landed one only in whitespace, such as re-indented Python lines: patch ids are computed with `git patch-id --verbatim`, and on a git older than 2.40, which lacks it, no commit counts as landed by patch id, so those worktrees are kept (#1213)
- github-pr-triage's `landed.py` no longer reads a commit as landed when it differs from a landed one only in whitespace, such as re-indented Python lines: patch ids are computed with `git patch-id --verbatim`, and on a git older than 2.40, which lacks it, no commit counts as landed by patch id, so such commits read NOT LANDED and their worktrees and branches are kept (#1215)

## [0.143.0] - 2026-11-15

### Fixed

- `move-major-tag.yml` with `land-environment` set proves the App's token with a dry-run push to the default branch before the major tag moves, so a bad `SHIPMILL_LAND_KEY` or an App that can't push fails with nothing pushed instead of leaving the major tag on the new release and the marketplace on the old one; a missing `.github/shipmill.toml` fails with an error naming the fix, not a traceback, the App's credential helper quotes the key's path so one with a space works, and a release that isn't the newest stable one no longer reads the key at all (#1188)
- The merge gate reads the newest trusted answer to a needs-decision question, not the first: a bare `1` after a reply with words takes the recommended option, and a reply with words after a bare `1` holds the item again; the retro's answer count keeps reading the first answer (#1199)

### Added

- `shipmill app-token <owner/name>` takes a repeatable `--permission <name>=<read|write>`: given, the token asks GitHub for exactly those permissions (metadata read comes with every token), each one the App's table has at no more than its access there, else it exits 2 before any request; the narrowed token is cached apart in `app-token-<permissions>.json`, never in the session's `app-token.json`, and the flag goes with `--git-credential` but not `--check` or `--product`. `move-major-tag.yml`'s marketplace push now mints its token with `--permission contents=write`, so it no longer carries issues and pull requests write it never used; without the flag nothing changes (D-90) (#1189)

## [0.142.0] - 2026-11-15

### Added

- `shipmill decide classify --pr N` reports `accepted-spec` in place of `scope` for a spec whose status line becomes `approved` when every `Spec for #N` issue of the pull request's body is open and either an accepted opportunity (`opportunity` and `planned`) or filed by an OWNER, MEMBER, or COLLABORATOR with no agent marker in its body; the reason names the issues, and anything else, an issue that can't be read included, stays `scope` (#1191)
- `triage_state.py` reads a build issue of a spec approved at `notify` (zone `accepted-spec`, spec 067) BLOCKED, noted `veto window of #<spec PR> until <time>`, until `veto_hours` after the spec pull request's merge, and noted `#<spec PR> vetoed by @<login>` while a trusted veto of it is unanswered; then as before. The skills take up such a veto by reverting the spec to `draft` in a pull request, closing its build issues as not planned, and asking on the feature issue in `scope` (#1192)
- `pr_gate.py` lands a spec pull request in `accepted-spec` at `notify` (the base's `[decisions]`, never the PR's) on the `--bot-login`'s newest decided comment naming the zone and the judged head, or a head whose spec change `specs.py same-approval` reads as format only; until then it reads NEEDS_DECISION with a `needs-decision: accepted-spec: <why>` line, which the maintainer's answer also lifts. The skills say how a session decides such a spec pull request: take every recommendation and post the decided comment with its `<!-- shipmill:head <sha> -->` line. Spec 067 is built (#1193)

## [0.141.0] - 2026-11-15

### Fixed

- `move-major-tag.yml` takes a `land-environment` input, as `land.yml` does: set, it pushes the marketplace commit to the default branch as the App, with the environment's `SHIPMILL_LAND_KEY`, so a ruleset whose only bypass actor is the App no longer leaves the marketplace on the previous release; the major tag's force-push stays with the workflow token, as land's tags do (spec 054); empty, the default, both push with the workflow token as before (#1179)

### Added

- The decision policy gains the zone `accepted-spec`, right after `scope`: approving the spec of work the maintainer already accepted, default `ask` and floor `notify`, so `[decisions] accepted-spec = "notify"` is accepted while `"act"` exits 2 naming the floor, and `[decisions.paths.accepted-spec]` exits 2 as the zone takes no paths; `shipmill decide levels` lists it and `retro.py gather --decisions` counts its questions and decided comments in its own row; the default stays `ask`, so no repository changes behaviour on upgrade (spec 067) (#1190)

## [0.140.0] - 2026-11-15

### Removed

- github-pr-triage: `pr_gate.py --maintainer-accepted` exits 2 before any GitHub read, saying the maintainer's acceptance is read from their answer on GitHub; an `ask` zone, a Protected areas glob, or a direction edit is lifted only by an accepting answer to the needs-decision question that covers the judged head, and a `never` zone stays MAINTAINER_ONLY (#1095)

## [0.139.0] - 2026-11-15

### Added

- github-pr-triage: `pr_gate.py` reads a pull request whose body carries the agent marker on a line of its own as an agent's, whoever opened it, and an agent's pull request that changes code and would read READY reads UNREVIEWED, exit 9, until a review record covers its head: the App's review whose first line is `<!-- shipmill:review merge -->`, or a trusted person's approval, at that head or one with the same own change; `shipmill review record <n> --head <sha> --verdict merge|refuse --body-file <file>` posts that record as the App, and the skills record the reviewed head with it, read the maintainer's answer instead of passing `--maintainer-accepted`, and open a pull request with its plan in the body (#1090)

## [0.138.0] - 2026-11-15

### Added

- github-ship-watch's `watch_state.py` lists each issue or pull request the gate keeps idle as a GATE_IDLE row, read from `handed.json` in the gate folder's state directory: `idle since <time> UTC (<age> ago): session <id> wrote nothing on it; waits for a change`, oldest first, in the full report and `--no-host`, never an action or an agent's row, and a malformed `handed.json` exits 2 naming its path; the postpone templates carry a `Revisit on:` line, and the triage, setup, and watch docs say how the gate hands subjects one by one (spec 061 is built) (#1167)

## [0.137.0] - 2026-11-15

### Added

- `docs/release-lanes.md` has a Protected default branch section: how to land as the App on a protected default branch (`[agents] app_id`, the `shipmill-land` environment limited to the default branch with its `SHIPMILL_LAND_KEY` secret, `land-environment` on the land job, and `shipmill ruleset`), the workflows an App push starts, doctor's `landing` row, and its limits; its Limits, `docs/install.md`'s prerequisites, and shipmill-setup's Branch protection check name the opt-in (#1082)
- `shipmill doctor`'s hooks self-test, and the headless gate's before a session, run the install's Stop hook too: on a final message asking the maintainer with no request on GitHub it must refuse (exit 2), and with `stop_hook_active` true let the session end (exit 0); either failing, or an install with no Stop hook, is a FAIL naming the plugin update, and a headless gate starts no session (#1097)
- Each optional permission of the App now says which config needs it: Deployments: read is needed by a config that declares `[environments]` (spec 060). `shipmill doctor`'s `app` row and the gate's `warning:` line still name every optional permission the installation lacks, needed or not, and `setup_state.py` wants the `shipmill-permission` label in a repo whose config sets `[agents] app_id` (#1160)
- `triage_state.py`: a postpone comment's `` Revisit on: `<path>` `` line keeps its issue POSTPONED (`waits on <paths>`) until a file a path matches changes between the newest stable tag before the comment and the newest one, then reads REVISIT naming the file, instead of REVISIT on every stable tag; one compare per base tag, and no base tag, a compare at GitHub's 300-file cap, or no line read REVISIT as before, an unreadable line at once (spec 061) (#1163)
- The `deploy-step` zone (default `ask`, no floor): `shipmill decide classify --pr N` names each changed job of a deploy workflow (one an `[environments]` table names, or with an `environment:` key) that no run on the pull request's `Proof:` line ran at the head's content of the file, and `--files` names each deploy workflow, so `pr_gate.py` reads such a pull request as NEEDS_DECISION until the maintainer accepts it; classify only reads the runs, with GETs (spec 063) (#1164)
- `shipmill doctor` warns, in a `deploy runner` row, of a job whose `actions/checkout` sets no `path:` and runs on a self-hosted runner a deploy job deploys from, since its checkout cleans the workspace the deploy left; a PASS row names the deploy jobs checked, and a repo with no deploy job on a self-hosted runner sees no row (#1165)
- The gate tells the App's owner when a release adds a permission to grant (spec 060): on a sweep, when a repo of the App's installation needs an optional permission the installation lacks (Deployments: read, for a config with `[environments]`), the gate of one repo of it, the carrier (a product's home first, else the first by name), files one `shipmill-permission` issue labelled `role:maintainer` and assigned to the maintainer, with the two steps and their links. No second one is filed while one exists in any repo of the installation, so closing it as not planned declines it; once the installation grants the permission, the gate of the repo holding it closes it as completed. It reads the installation with a token of its own asking only metadata, contents, and issues read, writes only in its own repo with its own token, and its decision line and `sweep.json` say what it did (`permissions: ...`) (#1166)

### Changed

- The decision retro (`retro.py gather --decisions`) proposes a zone from `ask` to `notify` on a rate: at least `--lower-rate` (90) percent of at least `--lower-min` (10) answered questions over the `--lower-after` windows took the recommended option, so one departure no longer resets it and a question still open no longer blocks it; it counts the questions with no zone line under `unzoned` and every question under `all`, and per zone what became of each decided item, vetoed, reverted (its issue reopened, or its merged pull request reverted, within `--revert-days`, 14), or held, which no proposal reads (spec 058) (#1159)
- Gate: a tick hands an item of tier 3, 4, or 6 by its subjects, one hand per `#N` in `handed.json` (a pull request's with its head and check rollup), cuts the item and its prompt to the subjects not taken, keeps a subject whose session wrote nothing on it idle past `retry_hours` until GitHub shows it changed (UNCHANGED names it), and reads an `ISSUES HANDOFF_DUE` item again before its session starts, QUIET when none is still due (spec 061) (#1161)
- Under `[autonomy] land = "propose"`, `watch_state.py` lists an open pull request labelled `shipmill-ready` in PRS_PARKED as `TO_MERGE #N` (`WITH_PERSON #4 (@a); TO_MERGE #12`), not in PRS_OPEN, in `--tier 3` and the full report, so the gate starts no more sessions on a pull request that waits on the maintainer's merge; under `act` and `observe` nothing changes, and `shipmill status` reports it to merge as before (#1162)

## [0.136.0] - 2026-11-15

### Added

- `land.yml` takes a `land-environment` input: set, its `land` job runs in that environment, writes the environment's `SHIPMILL_LAND_KEY` secret, masked, to a mode 0600 file, and runs `shipmill land --app-key` with it, failing before land when the secret is empty; empty, it lands as before. `shipmill init --land-as-app` writes `land-environment: shipmill-land` on the release workflow's `land` job, and exits 2 when the config sets no `[agents] app_id` (#1079)
- Delivery hooks: a `Stop` hook refuses, once per session, a headless gate session's end whose final message asks the maintainer for something while the session filed no issue and labelled nothing `needs-decision` (spec 062) (#1094)

## [0.135.0] - 2026-11-15

### Changed

- shipmill-setup and `docs/install.md` put a gate's checkout at `~/.local/share/shipmill/gates/<owner>/<repo>`, a detached worktree outside the repo, so a cleanup of the repo's `tmp/` no longer deletes it. A gate under `tmp/shipmill-gate` keeps working and reading as before; setup_state.py warns about it as `GATE_IN_TMP` and shipmill-setup offers to move it once you agree. github-ship-watch reads a gate checkout at the new place as the gate's, and its `GATE_CHECKOUT_MISSING` fix adds one there back as a worktree of your checkout (#1156)

## [0.134.2] - 2026-11-15

### Fixed

- github-ship-watch reports a gate job on this Mac whose checkout is gone as `GATE_CHECKOUT_MISSING`, an action for a person with the fix that adds the folder back and restarts the job: launchd stops such a job before `shipmill gate` runs, so it had stopped unreported. Every watch on the host reads every gate job, and `shipmill factory`'s sessions check fails on it (#1155)

## [0.134.1] - 2026-11-14

### Fixed

- An answer that names the recommended option as listed, its number and its text together (`1. Take every recommendation`), now takes it, so `shipmill gh pr merge` lands a spec pull request the maintainer approved that way and the retro counts it as recommended (#1150)

## [0.134.0] - 2026-11-14

### Changed

- `pr_gate.py` binds the maintainer's answer to the full head SHA its question names on a hidden `<!-- shipmill:head <sha> -->` line under `CI on <sha7>`, never to a commit's date, a force-push's `beforeCommit`, or a 7-character prefix, and asks again when the question has no such line; it reads the whole reply, so `1` followed by a request is the person's own words; and an answer on a linked issue counts only for a pull request the App or an OWNER, MEMBER, or COLLABORATOR opened (spec 055, S-055-5, S-055-7, S-055-8 revised) (#1122)

## [0.133.0] - 2026-11-14

### Changed

- The reviewer brief names a service's risks too: charges and refunds, status transitions, several writes without a transaction, repeated requests and retried jobs, and access to other users' records and migrations; and it asks the reviewer to find where the code holds each invariant the plan or issue lists (#1143)

## [0.132.0] - 2026-11-14

### Added

- `docs/software-factory.md` maps shipmill to the terms of the in-progress `software-factory` skill at commit `5863806` (each slot and example task to the part that fills it, the stages after the merge, the terms it has no word for, and the three brakes), linked from the README and the site (#1141)

## [0.131.0] - 2026-11-13

### Added

- `shipmill doctor`'s decisions block prints one PASS line per `[decisions.paths.<zone>]` part, naming its zone, glob, and level, and WARNs for a part set below its zone's default; the "Who decides" docs say which zones take parts and that the strictest level among a change's paths wins (#1076)
- `shipmill doctor` prints one `verify command` row per `[agents] verify` command from the gate's last check: PASS for `ok`, FAIL with its result, detail, and fix (a missing program's fix is installing it on the gate's PATH, never an allow rule), and WARN `not checked yet` until the gate checks the current list (#1077)
- `docs/release-lanes.md` documents `[gates] veto_lanes`: what a release ships, the wait for each `notify` decision's veto window, a person's hand start that releases anyway, and the hourly tick it needs; the needs-decision protocol says such a lane holds a `notify` decision's release until its window ends (#1086)
- `shipmill gh pr merge` of a pull request `pr_gate.py` reads QUEUED adds the land window's `queued_label` to it as the App and exits 2 without merging, and a merge that exits 0 removes that label from the pull request carrying it (S-056-8) (#1102)
- The skills name the land window: github-pr-triage's hard rule 1 and landing reference say what a QUEUED pull request (`pr_gate.py` exit 10) means and that the gate lands the queue as LAND_DUE once the window opens, github-ship-watch lists the LAND_DUE and LAND_QUEUED rows, and shipmill-setup writes `[land.window]` to hold merges of labelled classes to hours, with its `queued_label` label; spec 056 is built (S-056-14) (#1104)

## [0.130.0] - 2026-11-13

### Added

- `shipmill decide classify` sets each changed path's level from the strictest `[decisions.paths.<zone>]` part on the base whose glob matches it, else its zone's level, and takes a zone's level as the strictest among its paths'; its JSON lists them in a new `paths` key per zone (`path`, `level`, `source`, `glob`), and a text reason names the part that set a level, so `pr_gate.py` holds or notifies by the part (spec 057) (#1071)
- `shipmill gate` checks `[agents] verify` on a real headless launch, after the hook self-test and the preflight, when the state directory's `verify.json` holds no result for the fingerprint of the list, the tool flags, the settings files, the PATH, and the plugin's version, or holds a failing one `retry_hours` old; the decision line ends with `; verify: ...`, the session starts whatever the result, and with `notify = true` a failing result sends one desktop notification per fingerprint (#1074)
- A lane in `[gates] veto_lanes` now waits for the veto windows it would ship: `shipmill plan` reads the merged pull requests in the candidate's base and not in the lane's newest tag (the last 168 hours with no tag yet; the newest stable tag to the rc's base for a promotion) and the issues they close, and skips the lane while a trusted decided marker's `until` is ahead or a veto of it is unhandled, naming each item, its zone, and when its window ends; a person's hand start (`--actor <person>`) releases anyway, a bot's or an unnamed one waits, and a trusted marker whose `until` isn't a UTC time or lies more than 168 hours after its comment exits 2 naming the item (spec 059) (#1084)
- A component's triage reads a hold on its product's other repos (spec 065, D-84): `triage_state.py --home OWNER/NAME` in a component reads again, through `shipmill gh --product`, one call per owner, each hold on another repo's item that plain gh couldn't read, so a hold on a home item it reads is BLOCKED or UNBLOCKED like any other; a read that fails leaves the hold unknown with D-60's note, as before; without `--home`, or in the home, no `shipmill gh` runs. github-issue-resolve says a component reads a spec or item of its product's other repos with `shipmill gh --product`, writes nothing there, and asks through needs-decision, writing no substitute, when a reference it builds from can't be read (#1087)
- Goals: the twelve stage metrics (`issue_to_agent_comment_*`, `issue_to_pr_*`, `issue_to_pr_person_*`, `issue_to_pr_agent_*`, `pr_to_merge_*`, `merge_to_release_*`, each `_median` and `_p90`) join the goal-measure registry with `<n>h` or `<n>d` targets, and the weekly retro reads their status; a missed `issue_to_release_*` or `lead_time_*` goal gains `grew_most`, the stage that grew most from the week before, shown as `grew most:` on its Goals row (#1092)
- `pr_gate.py` reads the land window on a base whose config has `[land.window]`: a green pull request carrying a held label and no bypass label reads QUEUED, exit 10, with a `queued:` line naming the next opening while the window is closed, or the spacing while the next held merge is still to come; a red, pending, refused, or held-for-a-decision one keeps its verdict, and a `shipmill window` that fails exits 2 (spec 056) (#1101)
- The land window's queue drains when the window opens: `watch_state.py` reports the oldest open pull request carrying `[land.window]`'s `queued_label` as `LAND_DUE` while the window is open and the spacing allows a held merge (an action whose fix is `/shipmill:github-pr-triage <repo>`), and every other one as `LAND_QUEUED` with why it waits, outside `PRS_OPEN`; the gate hands `LAND_DUE` in tier 3 before `PRS_OPEN` where `[autonomy] land` isn't `observe`, and its change check reads the window opening, or the spacing passing, as a change while a pull request is queued (spec 056) (#1103)

### Changed

- `shipmill gh pr merge <n>` and `shipmill gh api -X PUT repos/<o>/<r>/pulls/<n>/merge`, as the App, run the wheel's `pr_gate.py` on the pull request (the checkout's repo, the checkout, and the App's bot login) after the never-zone and needs-decision holds, and exit 2 without running gh unless it reads READY, printing `is refused: pr_gate.py reads #<n> <VERDICT>` with the gate's verdict and reason lines; a READY merge runs pinned to the head the gate judged (`--match-head-commit H`, or `sha=H` for the API), a merge pinned to another head exits 2 naming both, and a gate that exits 2, can't start, or prints no verdict refuses the merge, as do an unreadable bot login and the merge API's `--input`, as spec 055 says (#1093)

## [0.129.0] - 2026-11-13

### Added

- Decisions: `.github/shipmill.toml` accepts `[decisions.paths.<zone>]`, a level by glob for part of the `direction`, `security`, or `protected` zone, refused with exit 2 below the zone's floor or outside its paths, and `shipmill decide levels` lists each part under its zone (`"paths"` in `--json`); `decide classify` doesn't read parts yet, spec 057 (#1070)
- `[agents] verify` lists the commands a headless session relies on for verification, and `shipmill.verify` checks each one as such a session would meet it: the allowlist, the delivery hook, and a run through `$SHELL -c` with the gate's PATH, in a worktree at `origin/<default>` that it removes when it ends; the gate and doctor read the result in later changes (#1072)
- Decisions: `decisions.py`'s `policy()`, which `retro.py gather --decisions` and `decisions.py add --zone` read, accepts `[decisions.paths.<zone>]` with the package's refusals and leaves every zone's level as it is; on Python 3.10 it refuses the table with its "use 3.11+" message, spec 057 (#1073)
- `shipmill land --app-key <path>` pushes the release commit to the default branch, a hotfix to `release/X.Y`, and the sync commit as the App in `[agents] app_id`, with one token limited to the repository and `contents` and `workflows` write, minted before any push; the tag and the work branch keep the workflow token, and a push a branch's rules refuse (`GH013`, `protected branch`) names `shipmill doctor` and the docs as the fix (#1075)
- Doctor: a `landing` row reads the default branch's rulesets and classic protection (and `release/<series>` with a hotfix lane) and reports a rule that refuses land's push, naming the ruleset, its rules, the landing identity, and the App opt-in as the fix; a tag ruleset that would refuse the release tag is a warning (#1080)
- `shipmill ruleset` prints a branch ruleset for `gh api -X POST repos/<repo>/rulesets --input -`: the default branch (and `release/*` with a hotfix lane) needs a pull request and a check per job of the CI workflow the release workflow calls, with `[agents] app_id` as its one bypass actor; it exits 2 without `[agents] app_id` (#1081)
- `[gates] veto_lanes` in `.github/shipmill.toml` names the lanes whose release will wait for the veto window of each notify decision it ships (spec 059, empty by default; `hotfix` is refused); a lane it names gets the hourly tick, so `shipmill doctor`'s `schedule` check warns when `release.yml` lacks it, and doctor prints a `gates` line naming the lanes, a warning without `[agents] app_id` (#1083)
- A component's session reads its product's other repos (spec 065, D-84): in a checkout whose config sets `[product] home`, `shipmill gh --product OWNER/NAME` runs gh with a read-only App token (`READ_PERMISSIONS`: contents, issues, pull requests, and metadata read) over the home and every repo of OWNER the home's `[product] repos` lists, save the component, read from the home's `.github/shipmill.toml` with a token over the home alone; it exits 2 naming D-84 and the fix when the home doesn't list the component, refuses a token GitHub scopes otherwise, caches it in `app-token-read-<owner>.json`, and refuses every command that writes before gh runs; `shipmill gh -R` and `shipmill app-token` for another repo still exit 2, now naming D-84 (#1085)
- github-pr-triage: `pr_gate.py` reads the maintainer's answer to the needs-decision question from GitHub, on the pull request or, without one there, on the issue it closes or is part of, and lifts an `ask` zone or a Protected areas match to CI alone only for a head the answer covers: the head it was given at, or one whose own change is the same (`specs.py same-approval` for a spec pull request); otherwise it prints why the question stays open (#1088)
- Metrics: issue to release by stage. Right after Issue to release, `metrics.py` measures Issue to first agent comment, Issue to PR opened (also split person-filed and agent-filed), PR opened to merged, and Merged to release, each a median and p90 in hours over the same issues, the last three summing to Issue to release per issue (#1089)
- `shipmill gh pr create`, with `[agents] app_id` set and `docs/product.md` on the default branch, checks the body it would send with `pr_gate.py`'s plan rule and exits 2 without running gh when the plan doesn't hold, printing each problem; a body with a `Spec for #N` line needs no plan, a repo without `docs/product.md` on its default branch isn't checked, the default branch is `origin/HEAD` or, where that is unset, the branch `git ls-remote --symref origin HEAD` names, and `--fill`, `--fill-first`, `--fill-verbose`, `--template`, and `--recover` are refused there, as spec 055 says (#1091)
- Gate: a headless session's `--settings` env holds `SHIPMILL_MAINTAINER`, the login its prompt names, beside `SHIPMILL_GATE=1`, and the headless paragraph ends asking that every request to that login in the final message is an issue or a needs-decision question on GitHub (spec 062) (#1096)
- `[land.window]` in `.github/shipmill.toml` sets the hours, in one time zone, when pull requests of held label classes may merge, read strictly (a malformed section exits 2 naming the key, and `doctor` fails on it); `shipmill window --json` prints whether the window is open, when it opens or closes next, the last held merge and when the spacing allows the next; shipmill-setup's checklist wants the section's `queued_label` (spec 056) (#1100)

### Changed

- needs-decision: a headless session's question about a failed command tells a denial, a delivery hook refusal, and a not-found (exit 127) apart, each with its own fix; a not-found's question names the program missing from the gate host's PATH and never proposes widening the allowlist (#1078)

### Fixed

- `shipmill gh api repos/<owner>/<repo>/pulls` as a POST, named with `-X`/`--method` or implied by a field, checks the pull request's body for its plan as `shipmill gh pr create` does and exits 2 without running gh when the plan doesn't hold, a body read from `-F body=@<file>` or stdin and a create with no body included; a GET listing pull requests and an edit of one run as before (#1121)
- `shipmill.verify` now meets a verification command as a headless session does: the commands inside `$(...)` and backticks are judged against the allowlist too (one it can't read is denied, never run), `settings.local.json` is read from the checkout the sessions start in, the wrappers `timeout`, `nohup`, `nice`, `command`, and `xargs` are stripped before a rule matches, the delivery hook gets each part in the directory a `cd` before it set, and a run never waits on a child holding stderr and leaves no child behind (#1123)

## [0.128.4] - 2026-11-13

### Fixed

- Docs: `docs/release-lanes.md` (Limits), `docs/install.md` and shipmill-setup no longer tell an organization repository to let `github-actions[bot]` bypass the branch rules, which GitHub refuses there (a ruleset rejects it as a bypass actor, classic protection drops it); they say a rule requiring a pull request or a status check on main blocks landing, that the release commit's CI reports as `ci / checks` rather than `checks`, and to protect main there only against force pushes and deletion for now (#1038)

## [0.128.3] - 2026-11-11

### Fixed

- The gate's App check no longer reads the App's bot account anonymously on every tick, which spent the host's shared 60-an-hour limit: it keeps the bot's id in its state folder's `bot-ids.json`, by App id and slug, and reads GitHub only on a miss; a dry run, `shipmill status`, and `shipmill factory` read that file but never write it, and a malformed one exits 2 naming it (#1034)

## [0.128.2] - 2026-11-11

### Fixed

- `shipmill gate` no longer tells you to rerun `app-install` when GitHub rate-limits it: a 403 or 429 saying a rate limit was exceeded, to the App check, the token mint, or the repo read, is `GITHUB_AUTH` with `GitHub rate-limited the call (<method> <path> answered <status>)` and the fix to wait for the limit to reset, since the next tick tries again; the tick still exits 2, and a 403 without a rate limit reads as before. A merge's Co-authored-by now reads the App's bot account with the App's token, not anonymously under the host's shared per-IP limit (#1034)

## [0.128.1] - 2026-11-11

### Fixed

- `chains.py link --product` can make a listed repo's issue a sub-issue of a report in the product's home repo: the coordinator's product token now also covers the home repo when it has the listed repos' owner, with the same permissions (D-83), and such a link writes through `shipmill gh --product <the child's repo>`, so GitHub's `addSubIssue` sees both issues instead of failing with `Could not resolve to a node with the global id`; a product token cached without the home is minted again on its next use, and a home of another owner keeps today's token (#1032)

## [0.128.0] - 2026-11-10

### Changed

- github-issue-triage links a check issue's parts as its sub-issues, so it reads VERIFY_DUE once they close, and asks the maintainer when GitHub refuses the sub-issue instead of holding the check on a `Depends on` line, which reads UNBLOCKED as work to build (#1027)

## [0.127.2] - 2026-11-10

### Fixed

- A gate session no longer asks the maintainer to decide on a pull request while its CI is failing or still running: `pr_gate.py --wait` keeps polling while a NEEDS_DECISION pull request has a pending check on its head (its exit codes and verdict ranking unchanged), the needs-decision protocol asks only once the head's checks finished and handles a failed one as red CI first, and the question states the head's CI state (#1028)

## [0.127.1] - 2026-11-10

### Fixed

- D-82's stated known limit names `uv tool run`, the long form of `uvx`, which a headless gate session's delivery hook lets start any program, and a test keeps the gate's `SHIPMILL_GATE` name and the hook's the same, so a rename on one side can't silently turn the rule off (#1025)

## [0.127.0] - 2026-11-10

### Changed

- `pr_gate.py`'s verdict line prints the pull request's full 40-character head in `head=`, the head it judged, instead of its first seven characters, so the lander passes it to `shipmill gh pr merge --match-head-commit` as it is, which refuses a short SHA, instead of reading the head again or guessing the rest of it (#1017)

### Security

- A headless gate session's `uv run` starts only `python`, `pytest`, `ruff`, `mypy`, the checkout's `[project.scripts]`, a path to a `.py` file, or a program `[hooks] uv_run` adds: the delivery hook refuses `uv run env`, `uv run sh`, any other program, and a `NAME=value` word where the program goes, in a session whose `--settings` env sets `SHIPMILL_GATE=1`, which the gate now gives every headless session; a person's own session is unaffected, the skills and briefs now set a variable through `uv run --env-file tmp/<name>.env <command>`, and `uv run python -c` and `uvx` still start any program, a known limit (D-82) (#1018)

## [0.126.0] - 2026-11-10

### Added

- A busy self-hosted runner no longer reads as a stalled one: each RUNS_ACTIVE row of github-ship-watch's report ends with what the run's jobs do (`running: <job> since HH:MM UTC`, `no job started`, `no job running`, or `jobs unreadable` when GitHub refuses the read), and each `pending:` line of github-pr-triage's gate says `(queued)`, `(running since HH:MM UTC)`, or `(pending)` (#1014)
- An agent's pull request plan may name the quality-bar ids it serves: `pr_gate.py` accepts `Serves: Q-6` and `Serves: quality bar (Q-4, Q-6)` when docs/product.md's Quality bar lists them, refuses an unlisted one like an unlisted goal id, and the weekly retro counts such a pull request under the quality bar (#1016)

### Fixed

- The session's gh helper runs gh at the path PATH names, such as `/opt/homebrew/bin/gh`, not its symlink's versioned target, so a `brew upgrade` during a session no longer breaks every gh call with exit 126 (#1015)

## [0.125.0] - 2026-11-10

### Added

- `specs.py same-approval SPEC ANSWERED_HEAD HEAD [--base REF]` compares a spec pull request's own change to its spec at the head a trusted answer was given at and at its head now, leaving out only format (rewrapped text and whitespace, the `status:` line, an empty or placeholder section, the same `D-n` ids in another shape, a claimed `D-n` renumbered): it exits 0 when the answer still covers the spec and 1 listing each other difference by section, so a format-only fix no longer asks the maintainer again, and github-pr-triage quotes that output when it does (#1007)

## [0.124.1] - 2026-11-09

### Fixed

- A hold sentence in an issue's own comment that names the issue itself ("#126 keeps waiting on #125" on #125), as `#N`, `owner/repo#N` or its URL in any case, no longer holds it: triage read such an issue BLOCKED on itself forever, and ship-watch held an agent's draft on its own number the same way (#1005)

## [0.124.0] - 2026-11-09

### Changed

- The reusable workflows pin uv to one exact version, 0.13.7, in every `astral-sh/setup-uv` step instead of installing the newest uv on each run, so a broken uv release no longer stops every connected repo's release at once; a test keeps every step on the same version, and `@v0` and the `tool` input keep floating on purpose (D-80) (#1001)

## [0.123.2] - 2026-11-09

### Fixed

- The weekly retro now learns whether a zoned question was answered with its recommended option when the question's zone line has no `answer=`: it reads the first answer after the question, a person's reply or the App's relay for the maintainer (pass `retro.py gather --decisions` the `--role` flags), and counts it only when it takes the recommended option as it stands, so the "ask to notify" proposal no longer starves (#997)

## [0.123.1] - 2026-11-09

### Fixed

- On a runner without GitHub's CLI, `plan`, `prepare`, `land`, `operate`, and every other command that reads GitHub exit 2 with `gh not found on PATH; install GitHub's CLI, https://cli.github.com` instead of a `FileNotFoundError` traceback, and the self-hosted runner docs list `gh` (#1000)

## [0.123.0] - 2026-11-09

### Changed

- shipmill's own config sets `[autonomy] upgrade = "act"`, so its config upgrades land on green CI without a needs-decision question (#995)

## [0.122.2] - 2026-11-08

### Fixed

- `pr_gate.py` reads a commit message's closing keyword followed by an issue's URL, `https://github.com/<owner>/<repo>/issues/N` of the pull request's own repo, as GitHub closes by it, so a commit naming a `Part of` issue or one whose `## Check` hasn't run by its URL is refused like one naming it by `#N`; a `/pull/N` URL and another repo's URL name nothing (#993)

## [0.122.1] - 2026-11-08

### Fixed

- `pr_gate.py` reads a commit message's closing keyword wherever GitHub closes by it, mid-line, in backticks, and in a fence too, with `#N` or the repo's own `owner/repo#N`, so a commit saying `... and fixes #N` no longer slips past the gate and closes a `Part of` issue or one whose `## Check` hasn't run; the title and the body keep their reading (#988)

## [0.122.0] - 2026-11-08

### Changed

- `pr_gate.py` reads the checks on the base branch's head commit and reads FAILED, with a `base: red:` line, while one failed there, save for the pull request whose body has a `Repairs: <URL>` line naming that run; a failure from outside the code clears by re-running it on the default branch (D-75) (#963)
- `pr_gate.py` refuses a pull request whose commit's closing keyword names an issue its body lists as `Part of #N`, or whose commit's or body's closing keyword names an open issue with a `## Check`; `triage_state.py` reads VERIFY_CLOSED for any issue with a `## Check` a pull request or a commit closed before its check ran, not only a parent (D-76) (#965)
- github-pr-triage: `changelog_guard.py check` refuses an entry marked Breaking (`**Breaking**`, `**Breaking:**`, or `Breaking:` at its start) under a `###` heading that `[bump] major` doesn't list, in a fragment or under Unreleased, naming the heading to move it to, so a breaking change no longer releases as a minor (D-78) (#971)

### Added

- The gate's App asks for Deployments: read as an optional permission, so the report reads the environments' deployments; a new App asks for it at creation, and an existing installation accepts it once on the App's installation page (after it is added to the App's permissions). Until then sessions still start, the token never asks for it, and `shipmill doctor` and the gate's GitHub preflight warn naming what to accept (D-77) (#968)

### Fixed

- CI lints the workflows with the official actionlint release, pinned and checked by sha256 and cached, instead of an unpinned actionlint-py whose sdist build downloaded the binary from GitHub releases and failed release runs when that answered 504 (#977)
- `shipmill gate` no longer tells you to rerun `app-install` during a GitHub outage: a 5xx answer to the App check, the token mint, or the repo read is `GITHUB_AUTH` with `GitHub is unavailable (<method> <path> answered <status>)` and the fix to wait for GitHub (https://www.githubstatus.com), since the next tick tries again; the tick still exits 2 (#981)
- `pr_gate.py` reads the pull request's title for closing keywords too: under a squash merge it is the landed commit's subject, so a title naming an issue the body lists as `Part of #N`, or an open issue with a `## Check`, is refused as a commit's keyword is (#987)

## [0.121.0] - 2026-11-08

### Fixed

- `shipmill gh pr merge` written as a person passes no `--author-email`, which GitHub refuses with a user access token; the token's user is the merge's author (#870)
- The merge gate counts each check once, by its newest run: a pull request closed and reopened lists two runs of a check on one head, and an older failure no longer fails it after a newer pass, while a newer run still in flight keeps it pending; the `checks=`, `green=`, `pending=` and `failed=` counts now count the deduplicated checks (#962)
- The watch no longer ends on a repo with `[environments]` when the gate's GitHub App has no `deployments: read`: GitHub's `Resource not accessible by integration (HTTP 403)` on a deployments or deployment-statuses read is one `DEPLOYMENTS_FORBIDDEN` notice row naming the environments not read and the permission to accept, and the rest of the report (issues, pull requests, every other section) stands; any other failure of those reads still exits 2 (#973)

### Changed

- The evals of the agents' instructions stopped (D-74, superseding D-72): `evals.yml` stays `workflow_dispatch` only, no pull request needs an `evals` check, D-37's gate is retired with no baseline that brings it back, and github-pr-triage and spec 025 say so; every skill's "Improve the skill" section and the postmortem template now put a rule that must hold into code instead of asking for a case under `evals/`; the suite and `shipmill evals` stay in the tree (#972)

## [0.120.0] - 2026-11-08

### Changed

- `shipmill gh pr merge` and the merge API `PUT` now refuse, as the App, a pull request still labelled `needs-decision`, and in every mode a `--match-head-commit` or `sha` field that isn't the full 40-character SHA, naming `gh pr view <n> --json headRefOid -q .headRefOid` (#960)

## [0.119.2] - 2026-11-08

### Fixed

- The gate no longer exits 2 on every tick when an untracked file in its checkout sits where origin's new head adds a file: in its own linked worktree it moves the file aside, keeping its path, under the worktree's git dir (`shipmill-displaced/<UTC stamp>/`) and says so in one line; in a person's main working tree it moves nothing and names the files and the fix instead of git's raw message (#956)

## [0.119.1] - 2026-11-07

### Fixed

- Evals: a dispatched run keeps its session traces and each case's `.eval/gh.jsonl` (the eval run's `TMPDIR` is under the job's temp, which the breakdown step reads), `shipmill evals explain` reads a session that stopped within a quarter of its case's `max_turns` with no gh write as **harness**, `the session stopped early after N turns`, reading each failed case's limits from the suite at `--repo`, and the run's budget is 25 USD instead of 15, so a full run of the suite fits (#954)

## [0.119.0] - 2026-11-07

### Added

- The evals suite holds its first 25 cases from shipmill's own history, adding 11: six triage verdicts (implement twice, a maintainer's feature as a proposal, an agent's opportunity, a postpone, and a question before a contract change), four post-merge reviews that must raise the bug a later issue named, and a fix that opens its pull request as the App with its plan; with them `shipmill evals check --gate` passes, so the `evals` check now gates pull requests that change the agents' instructions (#449)

### Changed

- Evals: `evals.yml` runs only by hand (no weekly schedule) until the baseline passes 60%, and every run's summary explains each case that did not pass with `shipmill evals explain` (error, failed graders, turns, cost, last message, and a harness or agent verdict), its artifact holding the session traces and each case's `.eval/gh.jsonl` (#950)

## [0.118.0] - 2026-11-07

### Changed

- The agents' evals no longer run on a pull request: `evals.yml` runs weekly and when the maintainer dispatches it, until the default branch's baseline passes 60% of its runs (D-71), and github-pr-triage waits on no `evals` check meanwhile unless one was dispatched for the head (#947)

## [0.117.5] - 2026-11-07

### Fixed

- github-pr-triage merges an accepted upgrade pull request when the maintainer answered in a session: the App's relayed `Decision by` answer naming a maintainer now counts as the upgrade's acceptance, as github-ship-watch already read it to open the pull request (D-70, S-014-16) (#932)
- Evals: the gh stub reaches the case's session. The session's sandbox can't read the checkout, and the `env.PATH` in the workspace's `.claude/settings.local.json` isn't applied to its shell, so the real `gh` still answered; the workflow now puts the workspace's copy of the stub first on `PATH` as the relative entries `.eval/bin:../.eval/bin:../../.eval/bin`. `shipmill evals check` refuses a case whose prompt opens with a slash command and that grades a `Skill` call, which can't happen there (#933)

## [0.117.4] - 2026-11-07

### Fixed

- Evals: every case records `shipmill autonomy --json` in `fixture/autonomy.json`, so an offline run answers the levels from the recording instead of reaching PyPI and reading the App as missing (#938)
- Evals: the eval shim answers `shipmill product show` from the case's `fixture/product-show/` recordings, and `product-intake/no-goal-not-proposed` records the forms intake runs, so an offline run reads the direction's goals instead of failing to reach PyPI (#941)

## [0.117.3] - 2026-11-07

### Fixed

- Evals: the 12 cases whose prompt opens with a `/shipmill:<skill>` slash command no longer fail every run on a `skill-loaded` grader, since the slash command puts the skill's text in the prompt and the session never calls the Skill tool; the grader stays in the cases that reach their skill by its description (#933)
- Evals: a case's session runs the offline `gh` stub and its `shipmill` and `uvx` shims, not the real ones, and its git works: the sandbox hid the checkout holding `evals/bin` and the shared clone's objects, so `.eval/gh.jsonl` stayed empty. `evals/scaffold.sh` now copies every object into the workspace, copies `evals/bin/` to `.eval/bin/`, and writes the workspace's `.claude/settings.local.json`, excluded from git, putting `.eval/bin` first on the session's `PATH` and its uv cache at `.eval/uv-cache` (#936)

## [0.117.2] - 2026-11-07

### Fixed

- Evals: every case runs its own `scaffold.sh`, which calls the shared `evals/scaffold.sh`, since `claude plugin eval` now refuses a `scaffold_script` outside the case's directory and ran no case; `shipmill evals check` refuses such a path, and a default-branch run where no case ran is never kept as the baseline, nor compared against when one was (#929)
- Evals: the workflow keeps the project's virtualenv under `$RUNNER_TEMP`, out of the checkout `claude plugin eval` scans as the plugin, which refused every case for the hard links uv made into `.venv` (#929)
- Evals: the workflow installs `bubblewrap` and `socat`, so Claude Code can confine a case's shell tool instead of refusing every case before a turn, and lifts Ubuntu's AppArmor limit on user namespaces only when `bwrap` can't create one (#929)

## [0.117.1] - 2026-11-06

### Fixed

- Gate: a handed item a full walk no longer finds loses its hand, so a pull request whose needs-decision question was answered goes to a session on the next tick instead of waiting out `retry_hours` (#926)

## [0.117.0] - 2026-11-06

### Changed

- Evals: `evals.yml` authenticates through Anthropic's Workload Identity Federation, trading the job's GitHub OIDC token for a short-lived Anthropic one, and reads no `ANTHROPIC_API_KEY` secret (#442)

## [0.116.0] - 2026-11-04

### Deprecated

- `[notices]` in `.github/shipmill.toml`: a config that sets it still loads, nothing reads it, and `shipmill doctor` warns naming D-69 and spec 021 until it is deleted (#921)

### Removed

- shipmill posts no notice on a fixed issue (D-69): `shipped.py` drops `--post`, `--install`, and the deployment notice, and reports which closed issues a release or a deployment fixed, with `--json` printing one object per issue (`number`, `tag`, `stage`, `source`); the watch reports no UNANNOUNCED or REQUESTER_CONFIRMED, the gate walks seven tiers without the notices tier, a stable promotion's plan reason counts no confirmed requesters, and metrics' issue to release runs from the issue to the stable release that shipped the pull request closing it; comments already posted stay (#921)

## [0.115.0] - 2026-11-03

### Changed

- product-intake's `intake_state.py --plans` reads a comment by the `--bot-login` whose first line is the needs-decision relay (``Decision by `@<login>`, relayed by Claude Code``) as the maintainer's answer to a goal plan when the login is a maintainer given with the new `--role` flags, newer than the plan's newest revision, its accept, decline, or edit read from the next line; `watch_state.py` passes its `--role` flags through, and the skill relays an answer given in the session (D-68) (#917)

## [0.114.0] - 2026-11-03

### Changed

- An agent never parks a pull request as a draft, and a draft the App opened no longer stalls once its session ends (D-67): `watch_state.py` reports it as AGENT_DRAFT, a session's item in the gate's pull-request tier, once its needs-decision question is answered and no hold comment on it names an open item (AGENT_DRAFT_HELD until then), `triage_state.py` reads its issue as AGENT_DRAFT or AGENT_DRAFT_HELD instead of IN_PROGRESS, `pr_gate.py`'s `draft:` line tells the App's own draft from a person's (still exit 8), and a quiet gate tick lists open drafts instead of reading "no open pull request" (#914)

## [0.113.0] - 2026-11-03

### Added

- Two config upgrades retire deprecated keys (spec 047): `drop-agents-prs` deletes `[agents] prs`, which the gate ignores, and adds nothing; `drop-roadmap` deletes the `[roadmap]` table and, when `[agents]` exists and sets no `wip`, moves `[roadmap]`'s `wip` there, which turns that limit on. Each keeps every other line of `.github/shipmill.toml`, is the migrating upgrade of its entry in `shipmill deprecations`, and so is proposed by the gate's sweep in every repo that relies on the key. `shipmill upgrade --apply`, `--json`, and the upgrade's issue show the lines an edit takes out (`removed_lines`, with `dropped` and `into` in `--apply --json`, and `drops` and `into` in `upgrade --json`) (#911)

## [0.112.0] - 2026-11-02

### Added

- `shipmill deprecations [<id>]` lists, for each deprecated config key or reading, the connected repos whose config on the default branch still relies on it, each with its migrating upgrade's state (`issue #N open`, `asked, waiting`, `not now`, `declined`, `pull request #N open`, or `not proposed`), or `none of N repos`; it reads the repos of this host's gate jobs, or `--repo owner/name` and `--fleet <file>`, with `--host` adding the gate jobs' back, and `--json` prints one object. It exits 1 when a repo relies on one and 2 when a repo can't be read, and `docs/release-lanes.md` gives the steps to retire a key on its output (spec 047, D-63) (#906)

## [0.111.0] - 2026-11-02

### Added

- `shipmill gate`'s sweep proposes config upgrades as the App (spec 047), every `[agents] sweep_hours`, before its own read, so a repo that releases rarely still hears of one: it runs `shipmill upgrade --propose` in-process for the config at the default branch's head and its `[autonomy] upgrade` level, writing the same one issue per upgrade the release workflow's `upgrade` job does. Without `[agents] app_id` it writes nothing, and `shipmill status` lists the pending upgrades with their `--apply` command. The swept tick's decision line names the outcome (`upgrades: 1 opened`), `sweep.json` keeps it under `upgrades`, and a failed proposal fails no tick: `shipmill factory`'s `gate` line reports it with its fix, the App's `issues: write`. `--dry-run` says what it would propose and writes nothing (#904)

## [0.110.0] - 2026-11-02

### Changed

- `shipmill upgrade --propose` never moves an upgrade issue backwards when two shipmill releases propose on one repo (spec 047): it leaves the title, body, and labels of an issue whose marker records a version newer than its own catalogue's version of that upgrade, compared in version order (0.9.0 before 0.10.0), and reports it `unchanged`; an open issue whose marker names an id it neither offers nor has withdrawn stays open and unchanged and is not listed. A marker whose version shipmill can't read counts as not newer, and the run rewrites it as before (#903)
- Deprecated config keys and readings are catalogued in `src/shipmill/deprecations.py`: `[agents] prs`, the `[agents] prompt` reading of `land`, `[roadmap]`, and `[agents] credit`, each with the release that deprecated it, its replacement, its migrating upgrade (`agent-autonomy` for spec 040's two), and a check over the parsed config; `shipmill doctor`'s deprecation warnings come from it, with the same text, row, and WARN as before (spec 047) (#905)

## [0.109.0] - 2026-11-02

### Added

- The ship watch reports an approved spec nobody split (spec 053): an ISSUES row `SPEC_UNSPLIT S-NNN <title> (docs/specs/NNN-<slug>.md): approved, no build issues, no open issue follows it`, with `/shipmill:github-issue-triage <owner/repo>` as its fix, for a spec on the default branch that is `approved`, lists no build issue, and that no open issue follows (none links its file in its body, none reads BLOCKED or UNBLOCKED on the pull request that added it); `shipmill gate` takes it up in tier 6, `shipmill status` lists it as `to split`, `triage_state.py --json` prints the spec files an open issue's body links as `specs`, and the spec gate opens a spec pull request with `shipmill spec open` and says how triage finds or files the feature issue and splits such a spec (#897)

## [0.108.0] - 2026-11-02

### Added

- `shipmill spec open docs/specs/NNN-<slug>.md --issue N [--with PATH]... [--body-file FILE]` opens a spec's pull request that the spec gate can follow (spec 053): it checks first, and on any failure exits 2 and writes nothing. The checks: the path's shape, `specs.py check`, status `approved`, `--issue` an open issue of the repo and not a pull request, no `spec/NNN-<slug>` on origin, and the App available as `shipmill gh` reads it. It then pushes `spec/NNN-<slug>` from origin's default branch with one commit of the spec and each `--with` path, without touching the working tree. It opens the pull request `Spec NNN: <title>`, whose body starts with `Spec for #N`, and comments the feature verdict on #N with the hold line `On hold: the build waits on <owner/repo>#<PR>, the spec PR.`. Every GitHub call goes through `shipmill gh`. Without `--issue` it exits 2 asking for the feature issue, which it never files itself (#895)
- A spec pull request names its feature issue (spec 053): `pr_gate.py` reads a ready pull request that adds `docs/specs/NNN-<slug>.md` as REFUSED, exit 6, with a `spec: names no feature issue` line, when no line of its body starts `Spec for #N` naming an open issue of the repo, whoever opened it and even with `--maintainer-accepted`; a pull request that only edits, renames, or copies a spec isn't checked (#896)

## [0.107.1] - 2026-11-02

### Security

- The config's `branch` must be a name git's branch-name rules accept (no leading `-`, `..`, spaces, control characters, `~ ^ : ? * [ \`, `@{`, and so on): one they refuse stops the config from loading, naming `branch`, and the gate's refresh passes the branch to git only inside a `refs/heads/` refspec, so a branch such as `--upload-pack=...` is never read as a git option (#889)
- The ship watch's state script passes the landing branch to `git fetch` only inside a `refs/heads/` refspec, and refuses a config `branch` that git's branch-name rules refuse, so a `branch` such as `--upload-pack=...` is no longer read as a git option (#892)

## [0.107.0] - 2026-11-02

### Added

- Each `shipmill gate` tick catches the local default branch up to `origin/<default>` by fast-forward only, so the maintainer's checkout no longer stays behind until someone pulls (D-66): `git fetch origin <default>:<default>` when no worktree has it checked out, and `git pull --ff-only` in the main checkout when it has it checked out, its tree is clean, and the branch is only behind. A dirty tree, a branch checked out in another worktree, or one ahead or diverged changes nothing and stays in `shipmill status`. The tick prints `catch-up: main 3 commits → origin/main` (a dry run: `would catch up: ...`), `--json` adds `"catch_up"`, a failure prints `catch-up failed: <first line>` and never fails the tick, and `[agents] catch_up = false` turns it off (#886)

## [0.106.0] - 2026-11-02

### Changed

- The shipmill-setup skill, `docs/flow.md`, and the README describe the three authoring modes (autonomous, assisted, operator), `[agents] author`, and `shipmill app-login`, each person's own opt-in, and who the decider is; the setup skill reads `[agents] credit` as deprecated in favour of `author = "app"`, and spec 051 is built (#869)

## [0.105.0] - 2026-11-02

### Added

- With `[agents] author = "decider"`, an issue or pull request `shipmill gh` writes as the decider keeps the agent marker `<!-- shipmill:agent -->` as its last line and ends its text with ``Opened by an agent through shipmill, on `@<login>`'s decision.``, from `--body` or `--body-file` alike and never twice; a merge written as the decider passes `--author-email <id>+<login>@users.noreply.github.com`, the id from the GET /user that already checks their token, and ends its body with spec 049's trailers for every other decider and then one `Co-authored-by` for the App's bot. A write that goes as the App gets neither, and `triage_state.py`, `watch_state.py`, and the credit read such a record as an agent's, never as that person's decision, filing, or answer (#868)

### Fixed

- With `author = "decider"`, two `shipmill gh` runs that refresh the same expired token at once no longer log the person out: GitHub refuses the second refresh because refresh tokens are single-use, so that run re-reads the stored file and writes with the token the first run saved, deleting the file only when it still holds the refused refresh token; a file deleted meanwhile (by `app-logout`, or the other run) writes as the App instead of crashing on the missing file (#882)

## [0.104.0] - 2026-11-02

### Added

- With `[agents] author = "decider"`, `shipmill gh issue create`, `pr create`, and `pr merge` run with the decider's user access token stored by `shipmill app-login`, refreshed first when it has expired, and as the App after one stderr line saying why when there is no decider, no stored token, or a token GitHub refuses; a refused refresh deletes the stored file, and every other command stays the App's. The refresh sends the App's client secret from `~/.config/shipmill/app-<app_id>-client-secret`, which you put beside the App's key with mode `0600`; without that file it refreshes without the secret, and a file wider than `0600` or empty makes the write go as the App, keeping the stored token. `shipmill doctor`'s `author` row says in assisted mode whether that file is there and its mode, a WARN when it is missing, too open, or empty, never reading it. `shipmill gh issue create --decided-in <n>` names the issue or pull request that decided it, and the flag never reaches gh (#866)

## [0.103.0] - 2026-11-01

### Changed

- Docs: spec 052 (a refused config key stops only its feature) is built, each criterion verified on the default branch (#575)
- Gate: a tick that reads a config whose `[agents]` sets a refused key runs as it would without it; its decision line ends with `; refused: <key> (spec NNN)` for each, `tick.json` and `shipmill gate --json` list them under `"refused"`, and the tick is never an ERROR tick (spec 052) (#861)
- Docs: `docs/release-lanes.md` says how shipmill retires a config key: a refused key turns off only its feature, refusing one is the maintainer's decision under D-63 no sooner than 14 days after its deprecating release (D-64), and a refusal is an entry in `src/shipmill/refused.py`; the `min_soak_days` and `plugin_update` paragraphs no longer describe an exit 2 (spec 052) (#862)

### Added

- A refused config key now shows where you look: `shipmill doctor` prints a FAIL row named `refused` with its message, beside a PASS `policy` row, and runs every other check; `shipmill status` prints a FAIL row with the key's fix; and every `--json` that prints an object (`decide levels`, `decide classify`, `autonomy`, `roles`, `milestones`, `factory`, `gate`, `app-install`, `upgrade --apply`) carries a `"refused"` list of `{"key", "spec", "off", "fix"}`, empty without one (spec 052) (#860)
- `shipmill doctor` prints an `author` row naming the mode of `[agents] author` (spec 051): `app`, `decider` with the logins that stored a token through `shipmill app-login` on this host, or `unset` with the deprecated `credit` reading (#867)

## [0.102.0] - 2026-11-01

### Changed

- A refused config key stops only the feature it configures (spec 052, D-64): a config that sets `[lanes.stable] min_soak_days` or `[agents] plugin_update`, whatever its value, now loads with the key dropped instead of exiting 2, and every command that loads the config prints `shipmill: refused: <message>` once on stderr, its stdout and exit code otherwise unchanged. While `min_soak_days` is set the stable lane is off: `shipmill plan` says `stable: off: <message>` and plans no stable release, and `shipmill plan --lane stable` exits 2 with the message; the dev and rc lanes plan as before. `plugin_update` turns nothing off. A key shipmill never knew still exits 2 (#859)
- `AGENT_AS_PERSON` in `shipmill doctor` and `shipmill status` skips an agent-marked record a person authored through the repo's App, whose `performed_via_github_app` id is `[agents] app_id` (spec 051's assisted mode), and still flags one a person's own token or another App made; GraphQL doesn't expose the field, so each record the search would flag is read once more with `gh api`, and one that can't be read that way stays flagged (#865)

### Added

- `[agents] author` in `.github/shipmill.toml` takes `"app"` or `"decider"` and needs `[agents] app_id`; with it set, `shipmill gh pr merge` names who decided the pull request in `Co-authored-by` whatever `[agents] credit` says, and `shipmill doctor` warns that `author` replaces `credit`. `credit` alone keeps its reading with a deprecation warning naming `author = "app"`, and a config with neither merges as before. Both values write as the App for now (spec 051) (#863)
- `shipmill app-login` lets the repo's App write as you (spec 051): it runs GitHub's device flow for the App in `[agents] app_id`, prints the verification URL and the one-time code you enter on github.com, and stores your user access token and refresh token in `~/.config/shipmill/user-<app_id>-<login>.json` with mode `0600`, printing the login it stored; an App with device flow off exits 2 naming its "Enable Device Flow" setting. `shipmill app-logout <login>` deletes that file and revokes the token when `SHIPMILL_APP_CLIENT_SECRET` is set, and otherwise, or when GitHub refuses, says to revoke the App under your GitHub settings (Applications, Authorized GitHub Apps). Nothing writes with the stored token yet (#864)

## [0.101.0] - 2026-10-31

### Changed

- With `mode = "off"`, `.github/shipmill.toml` may leave out `[changelog]`, `[bump]`, `version_files`, and `[lanes]`, so a repo that uses only the agent side loads in `shipmill doctor` and the gate; a table that is there is checked as before, a command that releases exits 2 naming the table it needs, and doctor notes each one left out, such as `releases off (mode = "off"): no [changelog]`; under `mode = "release"` or `"dry-run"` they stay required with the same messages (#856)

## [0.100.2] - 2026-10-31

### Fixed

- Gate: an answer relayed from a session (`Decision by @<login>, relayed by ...`, the label removed) reads as answered, so the gate takes it up rather than asking again, on an upgrade issue, a direction issue, and any other issue (#849)
- A repo that uses only the agent side (`mode = "off"` and no release workflow) runs a gate: the ship watch reads it as having no release bot (`BOT_NONE`, `releases off`) instead of stopping with `neither release.yml nor release-bot.yml calls a bot`, and `shipmill doctor`'s `workflow` check passes with a note that no release workflow is needed; a missing release workflow under `mode = "release"` or `"dry-run"` still stops the watch and fails doctor (#852)
- A pull request that is a person's item (labelled `role:<name>` or `human`, with an assignee), such as one the maintainer holds for their own merge, now waits on that person: `watch_state.py` lists it as `WITH_PERSON #N (@login)` in a new PRS_PARKED row instead of PRS_OPEN, so the gate's tier 3 starts no session for it every `retry_hours`; the gate's in-flight line says `1 waits on @login (#N)` instead of `waits to land`, and `shipmill status` lists it on the parked line. Taking up a "hold: I merge it by hand" answer on a pull request labels it `role:maintainer` and assigns the maintainer. `watch_state.py`'s error line for a failed command names the whole command, its endpoint included, with gh field and header values left out (#853)

## [0.100.1] - 2026-10-31

### Fixed

- The gate's launchd job gives uv 8 HTTP retries (`UV_HTTP_RETRIES`, about a minute), so the first tick after a FileVault login still reaches PyPI, and a run whose uvx found no network (uv's `Failed to fetch` on a DNS or connect error) reads `offline at last tick, next in N min` with `launchctl kickstart` as its fix instead of STUCK `failed: exit 2`; run `shipmill launchd <repo>` again to give an existing job the retries (#848)

## [0.100.0] - 2026-10-30

### Changed

- `github-issue-resolve` and `github-pr-triage`'s reviewers prove a fix with the cheapest check that fails on the old code, by a new test gate (`references/test-gate.md`): an existing test that fails on the revert, the repo's type checker, or a strict model at the boundary, and a new regression test only when none of them catches the bug; the PR's Test plan names the proof and shows it failing (#838)
- A headless gate session's rule of one allowlisted command per Bash call names the form that passes: set a variable with `uv run env VAR=value <command>`, never a `VAR=value uv run` or `env VAR=value` prefix, and import the package through `uv run pytest`, not `PYTHONPATH=.`; the implementer and reviewer briefs, `github-issue-resolve`, and the needs-decision reference carry it (#842)
- `watch_state.py`'s full report makes fewer `gh` calls: the comments of the pull requests labelled needs-decision or decided, open and closed, are one GraphQL query per 50 items instead of one REST read each, and the postmortems folder and its files' texts are one query instead of a listing and a read per file; on shipmill's own repo a run went from 45 calls in 54 s to 37 in 46 s, with the same rows (#842)

## [0.99.0] - 2026-10-30

### Fixed

- The `shipmill status` tests run git without the host's config, so S-008-3's origin check passes under the gate, whose agents rewrite SSH remotes to https (#833)

### Changed

- Tests: the schedule check's reading of a workflow's crons is pinned at its boundaries (minute 60, hour 24, weekday 7 as Sunday), `needed` at the 366 days after the given date, and a policy window at `24:00` or `07:60` at its `is not a time of day` error (#835)

## [0.98.1] - 2026-10-30

### Fixed

- `shipmill gate` no longer reads a headless session as dead from an authentication failure when only a tool's result or an assistant message in its stream-json log quotes one, such as a session that read `src/shipmill/gate.py`: the check reads only the log's lines that aren't events and its `result` events' text; a text log written before spec 048 is read as before (#822)

## [0.98.0] - 2026-10-29

### Changed

- `shipmill factory`'s gate line reads the gate's `tick.json`: a failing tick shows `failing since <since> (<count> ticks): <action>: <reason>` with the gate's own fix in place of `failed: exit 2` and `tail -n 50 <log>`, a STALLED tick is a problem with its fix, and a RUNNING tick names its session's item, how long it ran, and when its log last grew; `shipmill status`'s factory line shows the cause first, waiting on you for CLAUDE_AUTH, GITHUB_AUTH, and HOOKS_FAILED and STUCK for an error or STALLED. A `tick.json` the log's last line isn't from is ignored, and one that can't be read is the gate check's error (#817)

### Added

- `shipmill gate`'s QUIET line ends with what is in flight: the open pull requests waiting on CI, waiting to land, and failing CI, the last landed pull request, and the last session that ended with a result (`last-result.json`), all from the change check's one query, which now also reads the default branch's last 10 commits' merged pull requests; `--json` and `tick.json` carry it as `in_flight` (#818)
- `shipmill factory`'s gate line reads `quiet: <the in-flight summary>` from a current QUIET `tick.json`: the open pull requests waiting on CI, waiting to land, and failing CI, the last landed pull request, and the last session that ended with a result, aged to now, with no problem (#828)

## [0.97.0] - 2026-10-29

### Added

- `shipmill gate` says why a tick failed where status can read it: every real tick writes `tick.json` beside `gate.json` with its decision, or `ERROR` and a shipmill error's first line, its fix, and since when and how many ticks in a row failed; a failing tick (`CLAUDE_AUTH`, now the login's too, `GITHUB_AUTH`, `HOOKS_FAILED`, or a shipmill error) exits 2, every other tick 0 (#816)

## [0.96.0] - 2026-10-29

### Added

- `shipmill gate` checks the GitHub identity a session writes as before it starts one: on a LAUNCH, after the Claude Code preflight, it mints the App's installation token and reads the repo with it (never cached), or reads `gh api repos/<repo>` as the host's login without an App. A failure, or a failing App check before the state read, is the new `GITHUB_AUTH` decision with the reason and fix spec 048 gives, starts and stops no session, and exits 2 as the bare App check error did (#813)
- `shipmill gate` stops a hung headless session: one whose log hasn't grown for the new `[agents] stall_minutes` (30 by default, 0..1440, 0 never) reads `STALLED`, gets SIGTERM to its process group while its start time still matches `gate.json`, starts nothing, and its item is retried after `retry_hours`; `shipmill gate --json` adds `running` (session, item, minutes, `log_grew`) on RUNNING and STALLED (#815)

### Changed

- A RUNNING tick names the session's item, how long it has run, and, for a headless session, how many minutes ago its log last grew; `gate.json` records the launch's item, and one written before reads `item not recorded`. Headless sessions start with `--output-format stream-json --verbose`, so their log grows while they work, and a session ended with a result only when its log's `result` event has `is_error` false; a log written before is read as before (S-048-14, S-048-15, S-048-17) (#814)

## [0.95.0] - 2026-10-29

### Changed

- Config deprecations no longer end on a release count (D-63): `[agents] prs` and `[roadmap]` keep loading with a `doctor` warning, and a config that sets none of `triage`, `fix`, and `land` keeps reading `land` from `[agents] prompt` ("merge when green" or "land"), so a connected repo that never took the `agent-autonomy` upgrade keeps landing. The warnings name the replacement instead of a release that refuses (#735)
- The relayed answer's first line, ``Decision by `@<login>`, relayed by <agent>``, and the direction pull request's ``Direction from `@<login>` in #<issue>`` line name the login in a code span, so they no longer email the person (D-61); spec 012's S-012-6 and spec 034's S-034-9 say so, and a `Decision by` line with the login bare still reads as the answer (#771)

## [0.94.0] - 2026-10-29

### Changed

- `shipmill gh` ends every body it creates with the agent marker `<!-- shipmill:agent -->`, after a blank line, as the App and as the host's login: `issue create`, `issue comment`, `pr create`, `pr comment`, `pr review` (an `--approve` alone gets the marker as its body), `issue|pr close|reopen --comment`, and `gh api` creates of issues, pull requests, comments, review comments, replies, and reviews (their `body` field, or one holding the marker alone); a body that carries the marker already gets no second one. Those creates with no `--body` or `--body-file`, with `--web`, `--editor`, or `--edit-last`, a `gh api` create with `--input`, a `gh api graphql` mutation that writes a body (a create or an edit, such as `updateIssue`, naming the REST form), and a marked body over 65,536 characters exit 2 before gh runs; the release and operate workflows' issues and comments end with the marker too, a cut body included (spec 050) (#797)
- The github-issue-triage skill's `chains.py link` appends its `Depends on` line through REST, `gh api -X PATCH repos/<owner>/<repo>/issues/<n> -F body=@<file>`, instead of GraphQL's `updateIssue`, which `shipmill gh` now refuses; the body stays byte for byte, and `--no-text` and the `text only:` fallback are unchanged (spec 050) (#797)
- `shipmill gh` keeps the origin of every body it edits: `issue edit` and `pr edit` with `--body` or `--body-file`, and `gh api -X PATCH` on an issue, pull request, comment, review comment, or review with a `body` field, first read the record's current body with the same identity (the App's token, the host's login, or the `--product` token), then hand gh the new body ending with the agent marker when the current one carries it and with any marker removed when it doesn't, so an edit never marks a person's record nor unmarks an agent's. An edit whose current body can't be read, one that names no single issue or pull request by number or URL, and a `gh api -X PATCH` edit with `--input` exit 2 and the edit doesn't run; an edit without a body flag reaches gh as given, with no read (spec 050) (#798)
- The skills' scripts (`chains.py link`, `shipped.py --post`, `setup_state.py --fix`) write through `shipmill gh` in every repo whose `.github/shipmill.toml` has an `[agents]` section, with or without `app_id`, so a write without an App goes out as the host's login with the agent marker under `identity = "host"` and exits 2 otherwise; plain `gh` is left for a repo with no config or no `[agents]` (#799)
- `triage_state.py` and `watch_state.py` no longer read a comment carrying the agent marker `<!-- shipmill:agent -->` on any line, or a deleted account's comment, as a reply to a needs-decision question or as a veto, so without the App an agent's comment after the question no longer reads as the maintainer's decision (spec 050) (#800)
- Credit: with `credit = "decider"`, an issue, reply, or approving review whose body carries the agent marker `<!-- shipmill:agent -->`, or isn't a string, names no decider, while the App's `Decision by @<login>` relay still names `<login>`, as spec 050 has it (#801)
- `shipmill doctor` and `shipmill status` flag, under AGENT_AS_PERSON, a person's issue, pull request, or comment whose body carries the agent marker `<!-- shipmill:agent -->` on any line, and the needs-decision protocol, the spec gate, the triage rubric, and `docs/flow.md` say a record carrying the marker is never a reply, a veto, or the maintainer's filing; a decision answered in the session is relayed with its `Decision by` line with or without the App (#802)

## [0.93.0] - 2026-10-29

### Added

- `[agents] credit = "decider"` also credits, after the approvers: the trusted answerer of a needs-decision question on the pull request, an issue it closes, or that issue's parent (a reply after the question's marker, or the login an App comment's `Decision by @<login>` line names), the trusted author of an issue it closes or of that issue's parent, and whoever with write, maintain, or admin permission added `planned` to an `opportunity` issue it closes or to that issue's parent; each person once, the first record naming them giving the stderr line's reason (spec 049) (#786)
- `shipmill doctor` prints a `credit` row for a repo with `[agents]`: `decider` when `[agents] credit = "decider"`, `off` otherwise; the shipmill-setup skill and the flow guide name the key, its `"off"` default, and that a `Co-authored-by` trailer it adds means the person decided the change, not that they wrote it (spec 049) (#787)

## [0.92.0] - 2026-10-29

### Added

- `[agents] credit = "decider"` (off by default): `shipmill gh pr merge` names each trusted person whose latest review approved the pull request in a `Co-authored-by: <name> <<id>+<login>@users.noreply.github.com>` trailer after the body the merge would have had (the given `--body` or `--body-file`, else GitHub's default for the repo's merge message setting), so the merge shows on their profile; bots, the App, and the pull request's author never get one, a stderr line names each decider in a code span, and `shipmill gh api -X PUT .../pulls/<n>/merge` exits 2 naming `shipmill gh pr merge <n> --squash` instead (spec 049) (#785)

## [0.91.0] - 2026-10-28

### Changed

- The skills' GitHub text mentions a login bare, which GitHub turns into an email, only in a needs-decision question, a person's hand-off, and a notify decision's decided comment (D-61); every other template names it in a code span (`` `@login` ``): the verified, close, and check-waiting lines, an upstream report's verdict without a coordinator, a login named inside a question, and an upgrade pull request's `Accepted by` line. Each skill that posts states the rule, and the readers (`Decision by`, `triage_state.py`'s check-waiting login) take both forms, so older comments read as before (#771)

### Fixed

- In a product, github-issue-triage's coordinator files a component's part of a home-repo feature only after the spec pull request merges and never holds a component issue on a home-repo item (D-60); a component's `triage_state.py --home <owner/home>` reads a hold on a home item it can't read (`:unknown`) as BLOCKED with the note `the coordinator's hold on the home <owner/home>: waits for the coordinator, ask nobody`, and the skill leaves such an item rather than asking the maintainer whether the home's spec merged (#773)

## [0.90.0] - 2026-10-28

### Changed

- shipmill-setup's `setup_state.py --fix` now removes a committed `shipmill@shipmill` from `.claude/settings.json` in a repo whose `[agents] plugin` is `"host"` (the default): it deletes the `enabledPlugins` entry and, when no other enabled `<name>@shipmill` uses it, the `shipmill` marketplace, keeps every other key and the file's indent, and deletes the file when nothing is left; set `plugin = "repo"` to keep it (D-59) (#778)

## [0.89.1] - 2026-10-28

### Fixed

- The test that doctor asks origin, not the clone's refs, no longer fails under git 2.56, whose push to origin's URL also pruned the stale `origin/shipmill` the test sets up (#770)
- The Feature verdict's hold line in github-issue-triage's comment templates is now a whole sentence that names the spec PR alone, and the templates and the spec gate say that context such as the issue the spec is for goes in a sentence of its own; an agent that finished the old line with the parent issue held a part on its own parent (#772)

## [0.89.0] - 2026-10-28

### Changed

- The gate's change check reads each watched workflow's own 10 newest runs (the release workflow and each `[operate]` workflow), concurrently when there are more than two, instead of the repo's 100 newest runs of every workflow: a quiet tick spends about 2 s less on it, and a release run that finished behind 100 newer CI runs is now seen as a change (#762)
- `shipmill gate --dry-run` follows the prune's schedule, every `prune_hours`: when a prune isn't due it judges no worktree and prints `prune due at <time>`, so a dry run no longer spends most of its time judging worktrees or lists removals a tick wouldn't make; when one is due it lists `would prune` as before, and `--json`'s `"prune"` adds `"due"` and `"at"` on a dry run (#763)
- Plugin: a repo's `PLUGIN_SHADOWING` row in `doctor`, `status`, the setup checklist, and the watch counts only the project- and local-scope installs keyed on the repo's checkout, its linked worktrees, or its gate checkouts; `shipmill factory` still counts every one on the host, so a stray install is reported once, there (#764)

## [0.88.0] - 2026-10-27

### Changed

- shipmill's own config turns on agent-autonomy: `[autonomy]` sets `triage`, `fix`, and `land` to `act`, the levels its gate runs at today, so they no longer come from `[agents] prompt` (#684)

## [0.87.1] - 2026-10-27

### Fixed

- A parent issue or `upstream` report whose `## Check` the maintainer chose to run by hand ("leave it open") no longer starts a gate session every tick: the session posts a `<!-- shipmill:check-waiting -->` comment naming who answered, and `triage_state.py` reads the parent as WITH_PERSON (`check waiting on @login`) and `upstream_state.py` the report as ASKED, neither an action, until a child closes or a check-failed or verified comment follows (#740)

## [0.87.0] - 2026-10-27

### Added

- github-ship-watch: `watch_state.py --tier N` prints one of the gate's eight work tiers and `--sweep` the timed sections, neither with a host or report-only row, and `--known FILE` takes what the gate's change check read already; github-issue-triage's `triage_state.py --label` reads only the open issues carrying a label (spec 046, #756)

### Changed

- Gate: a tick checks GitHub for a change first (one GraphQL query and one read of the newest runs, against the cursor in `cursor.json`) and reads nothing more when nothing changed; on a change it walks the eight work tiers in order and hands a session the first item no session was handed within `retry_hours` (`handed.json`), with its tier and fix line, so one stuck item never holds back the next. The timed sections come from a sweep every `[agents] sweep_hours` (default 6); `--json` adds `walk` and `item`, and `--walk` and `--sweep` force them (spec 046, #757)

## [0.86.0] - 2026-10-27

### Changed

- `shipped.py`, and with it `shipmill status` and the gate's watch tick: the commits' pull requests are read 50 commits per GraphQL query and the closed issues 50 per query, in place of one call each, about 30 s less on a range of 30 commits; the plan, the notices posted, and the note for a number with no issue or pull request are unchanged (#754)

## [0.85.1] - 2026-10-27

### Fixed

- Tests: shipmill's own config can take a config upgrade, `[autonomy]` keys or a raised `requires`, without failing CI (#684)
- Product intake: `plans.py check` reads a direction whose goals carry a `measure:` line (spec 027) instead of refusing every plan body before reading it (#749)

## [0.85.0] - 2026-10-27

### Changed

- Spec 040, the agent stages in `[autonomy]`, is built: its Verification section says how each criterion was checked (#655)

### Fixed

- `shipmill status` no longer exits 2 with no report when one of the host's own reads fails (`claude agents --json`, `claude plugin list`, or the marketplace's latest release): it reads the sessions and shipmill sections on their own, as `shipmill factory` does, so the failure is that check's error on the `factory` line, the verdict reads STUCK, and every other line still prints; `watch_state.py --no-host` leaves those rows out of the full run (#745)

## [0.84.0] - 2026-10-27

### Added

- The skills follow the agent stages' `[autonomy]` levels (spec 040): github-issue-triage, github-issue-resolve, and github-pr-triage read their stage's effective level with `shipmill autonomy --json` before their first write, so under `propose` a verdict is posted as a `Proposed verdict`, a plan as a `Proposed plan`, and a green pull request is labelled `shipmill-ready` for a person to merge, under `observe` they write nothing, and an open `shipmill-hold` issue lowers every `act` to `propose` however the session started; a prompt's "merge when green" never raises `land`. shipmill-setup's Scope step becomes an Autonomy step offering four profiles that write every stage key, and the eval suite gains a case for each, with `shipmill autonomy` answered from a case's fixture (#665)
- `chains.py show` marks each open issue on a dependency cycle `CYCLE (a -> b -> a)`, its shortest loop from the least reference (`"cycle"` in `--json`, null on every other row), ends a row whose issue has a malformed `Depends on` line with `MALFORMED_DEPENDS line <n>: <the line>` (`"malformed"` in `--json`), and exits 1 for either; `chains.py link` refuses, before any write, a link that would close a cycle, with `closes a cycle:` and the loop (spec 041) (#715)
- `triage_state.py` reads CYCLE, an action, for an open issue on a cycle of the repo's open issues whose holds it reads, its note `cycle <loop>`; the others on a loop wait as BLOCKED, `cycle <loop> waits on owner/repo#N`, while one of them reads MALFORMED_DEPENDS or is labelled `needs-decision`. github-ship-watch counts CYCLE and MALFORMED_DEPENDS as triage actions and reports CHAIN_CYCLE, a person's action, once per cycle through another repo's items; `shipmill status` and `fleet.py` count both (spec 041) (#716)
- The coordinator's `upstream_state.py` reads an `upstream` report with a `## Check` whose children all landed as VERIFY_DUE in place of CLOSE_DUE `completed`, and as CHECK_FAILED after a trusted `<!-- shipmill:check-failed -->` comment newer than its newest child close; both exit 1, and the watch's UPSTREAM_DUE row names them, so the report closes when its fix is seen in production (spec 042) (#718)
- github-issue-triage describes a parent's `## Check`: it closes the parent only once the check holds in production, with the verified comment; on a failure it posts the check-failed comment and files the fix as a new child; a check it can't run goes to the maintainer; a check never writes to production. The spec gate asks for a check on a feature issue whose build deploys and then leaves `Fixes #<feature>` out of the last build pull request, and an `upstream` report may carry a check for its coordinator (#719)
- shipmill-setup's `setup_state.py` reads a Product row: with `[agents] app_id` and no `[product]`, it lists the owner's repos whose `.github/shipmill.toml` sets the same `app_id` as `PRODUCT_SIBLINGS`, or `PRODUCT_LISTED` with the `home` line to write when one of them lists this repo in `[product] repos`; `PRODUCT_OK` otherwise, and `--fix` leaves the row (#721)
- shipmill-setup has a Product step under The gate: it asks whether the repo is one of several making up a product, writes this repo's half (`[product] repos` in the home, `[product] home` in a component, `[product] standalone = true` when it stands alone, or the `home` a `PRODUCT_LISTED` row names, with no question), prints the line each other repo needs to run `/shipmill:shipmill-setup <repo>` in its checkout, and relays doctor's product lines with their fixes; its description names connecting several repos as one product, and an eval case covers it (#722)
- `shipmill factory` reports this host's machinery for the repo, one line per check (the gate's launchd job and log, its sessions, the GitHub App, the shipmill installs, the checkout, and the worktrees, with a line and its fix per kept shipmill worktree over 7 days old), each check run on its own, so one that fails prints `ERROR: <its first line>` and the rest still run; exit 1 on a problem, `--json` for one object. `shipmill status` keeps to the pipeline: one `factory` line replaces its gate, github app, and shipmill lines, a factory check that fails makes the verdict STUCK without stopping the report, and github-ship-watch no longer runs `shipmill worktrees` or prints `WORKTREE_STALE` (spec 044, #731)

### Changed

- `shipmill gh` in a repo without `[agents] app_id` now refuses a write with exit 2, naming the repo and the two ways to allow it, and still runs a read as your `gh` login; set `[agents] identity = "host"` to let the repo's writes go as your login, or pass `shipmill gh --as-host` for one call a person approved (spec 037) (#700)
- Specs 002 and 011 say spec 044 moved the kept worktrees' report, `WORKTREE_STALE`, to `shipmill factory` (#731)
- `shipmill gate` prunes landed worktrees after the tick's decision and any launch, only every `[agents] prune_hours` (default 6, 0 for every tick, recorded in the state directory's `prune.json`), and a prune that fails prints `prune failed: <first line>` and leaves the decision, the launch, and the exit code as they are, so one failing `gh` query no longer stops every tick; `--json` gains `"prune": {"ran", "error"}`, `shipmill factory` gains a `prune` line, and a failing prune counts on `shipmill status`'s `factory` line without changing the verdict (spec 045, #741)

## [0.83.0] - 2026-10-27

### Changed

- Plugin: one install of `shipmill@shipmill` at user scope (spec 039). Every fix shipmill prints names `--scope user`, never a per-folder update or reinstall; `doctor`, `status`, the setup checklist, and the gate's tick report every project- and local-scope install on the host as one `PLUGIN_SHADOWING` row; and the new `shipmill plugin-clean` lists them, and with `--apply`, from a person's terminal only, removes them while restoring each folder's `.claude/settings.json` and `settings.local.json` byte for byte (#701)
- A `Depends on` line holds only on the references of its strict shape (`Depends on[:] #1, #2 and owner/repo#3`, issue or pull URLs, `#{B1}` placeholders), never on one in a note after ` (`, `;`, or ` — `, and never inside a code fence; a line that names a reference in any other shape still holds on all of them and reads the new triage state MALFORMED_DEPENDS, an action, until a session rewrites it, and `chains.py link` appends a strict line when the only mention is in a note (spec 041) (#714)

### Fixed

- `suite_lock.py` holds a slot until the suite itself exits, so killing the wrapper no longer lets a second suite start beside one still running, and on Windows every process locks the same byte of a slot's file (#713)

### Added

- A parent issue with a `## Check` section reads VERIFY_DUE, not UNBLOCKED, once its sub-issues close, CHECK_FAILED after a trusted `<!-- shipmill:check-failed -->` comment newer than its last hold's close, and, closed by a pull request, a commit, or the session's bot without a trusted `<!-- shipmill:verified -->` comment, VERIFY_CLOSED instead of SUSPECT_CLOSE, so it closes when its result is seen in production, not when its last child merges (spec 042) (#717)
- `[product] standalone = true` records that a repo stands alone: `shipmill gh`, `shipmill app-token`, the gate, and the skills' scripts read it as no `[product]` table, and `standalone = false`, another value, or `standalone` beside `home` or `repos` exits 2 naming the key (#720)

## [0.82.0] - 2026-10-27

### Changed

- shipmill's own releases publish before they move their references (D-50): the stable and hotfix lanes list `move-major-tag.yml` under `after_publish`, so `@v0` and the plugin marketplace `ref` move only once `publish.yml`'s run passed and PyPI serves the release; the release commit no longer writes the marketplace `ref`, and `.github/shipmill.toml` sets `requires = ">=0.70.0"`. A newest-series hotfix now moves `@v0` and the `ref` too (#617)
- Implementers and reviewers run the fast checks and the touched files' tests and leave the full suite to the PR's CI, so parallel agents no longer starve each other of CPU; in a repo whose CI doesn't run the full suite, they queue it through github-issue-triage's new `suite_lock.py`. shipmill's CI runs its tests with pytest-xdist (#657)
- The shipmill plugin is installed per person by default (spec 033): a new `[agents] plugin` key, `"host"` when absent, says nothing in the repo turns it on; `plugin = "repo"` keeps the plugin committed to `.claude/settings.json` for everyone who opens the repo. Any other value exits 2. The setup checklist reads it: with `host` its Plugin rows read the host's installs, `PLUGIN_OK` naming the install that applies (user scope, or local or project scope for the repo's folder) or `PLUGIN_MISSING` with `claude plugin install shipmill@shipmill --scope user`, and the new `PLUGIN_COMMITTED` (not done) when `.claude/settings.json` still enables the plugin; `--fix` writes that file only with `plugin = "repo"`. A repo connected before reads `PLUGIN_COMMITTED` once and chooses. shipmill's own repo no longer commits the plugin (#698)
- The delivery hook's `app-writes` rule applies only where the App is available to the session: a non-empty `SHIPMILL_APP_KEY` in the hook's environment, or the App's key file at `~/.config/shipmill/app-<app_id>.pem`, checked with one stat and never read (D-54). Where it isn't, such as a contributor's host, a plain `gh` write is theirs and passes; the other rules hold as before, and a command's own `NAME=value` assignments never change the answer (#698)
- `shipmill gate` sets `SHIPMILL_APP_KEY`, the absolute path of the key it used, in every session's `--settings` env, headless and interactive. `shipmill gh` and `shipmill app-token` take the key from it before the default path, a leading `--app-key` still winning; with no key at the path, `shipmill gh` exits 2 before any token, cached or not, with a second line saying the App isn't available here and shipmill writes nothing (#698)
- `shipmill app-token --check` says whether the App is available to the session, by the hook's test and nothing more: exit 0 naming the App and the test that held, else exit 2 naming the missing key path and `SHIPMILL_APP_KEY`, or the missing `[agents] app_id`. It mints, prints, and reads no token or key. The six skills' "Write as the App" rule runs it before their first write to GitHub, a push included, and without the App they stop there and hand over the exact text of each write (target, comment, labels, the pull request's title and body) for the person to post, never writing as the person (#698)
- `shipmill doctor`'s hooks block says which case the host is in: `app-writes: on (the App's key is at <path>)`, `app-writes: on in gate sessions only (no key at <path> on this host; ...)`, or `app-writes: off (no [agents] app_id)`. `shipmill init` writes a commented `# plugin = "host"` line in its `[agents]` example, and `docs/install.md` gains a Contributors section for the maintainer (#698)
- The gate tick's `--json` key `auth` is now the credential's kind, `"token-file"` or `"login"`; the preflight's verdict it held moves to a new `preflight` key, so a reader of `auth` as an object must read `preflight` instead (spec 035) (#699)

### Fixed

- `specs.py coverage` no longer reads the repo's root `tmp/`, where an agent's stray worktree made the coverage test fail locally (#657)
- Tests: every repo template the suite copies turns off git's detached auto-maintenance, whose lock files vanished mid-copy and failed `pytest -n auto` runs in CI at random (#657)
- github-ship-watch: the direction question carries the zone line `<!-- shipmill:zone direction -->` as its second line, so the retro counts it as an ask in the `direction` zone (#672)

### Added

- The gate's sessions authenticate with a long-lived Claude token, the one `claude setup-token` prints, read from `~/.config/shipmill/claude-token` (mode `600`) or the file `shipmill gate --claude-token <path>` names; `shipmill launchd --claude-token <path>` writes the path, never the token, into the job. The token goes only into the environment of the `claude -p` or `claude --bg` that starts a session, and of the preflight's `claude auth status --json`, as `CLAUDE_CODE_OAUTH_TOKEN` with `CLAUDE_CODE_SUBPROCESS_ENV_SCRUB=1` and without `ANTHROPIC_API_KEY` or `ANTHROPIC_AUTH_TOKEN`; a file the gate refuses is `CLAUDE_AUTH` with exit 2, never a fallback to the login. `shipmill status` and `shipmill doctor` print a `claude auth` line (spec 035) (#699)

## [0.81.1] - 2026-10-27

### Fixed

- Worktrees and `shipmill status`: a checkout with more than about 120 worktree branches no longer fails with GitHub's "exceeds the maximum limit of 500,000" nodes; merged pull requests are read 50 branches per GraphQL query (#709)
- Worktrees: GitHub is asked only about the worktrees the local checks leave undecided (not ones kept as young, dirty, in a live session, or not shipmill's), and never about the default branch a work branch tracks (#709)

## [0.81.0] - 2026-10-26

### Fixed

- `chains.py link --product` links a report in the product's home repo: a home-repo parent's link is written through the session's own `shipmill gh`, a listed repo's through `shipmill gh --product <its repo>`, and every read of a listed repo goes through `shipmill gh --product <that repo>`, never plain gh (S-038-29) (#596)
- The gate's prune and `shipmill milestones` read the branch releases land on from the config at origin's default branch, as the gate's refresh does, never from a checkout a session left on a pull request's branch (#697)

### Added

- `shipmill doctor` checks a product across repos: in the home repo (`[product] repos`) it FAILs for a listed repo the App isn't installed on or that lacks a product permission, naming `shipmill app-install <repo>`, reports a malformed or repeated entry as a FAIL row and still runs its other checks, and WARNs when a listed repo's config, read with the product token, has no `[product] home` or names another home; in a component (`[product] home`) it reads only the home's `.github/shipmill.toml` through your gh and WARNs when its `[product] repos` doesn't list this repo or can't be read (#604)

## [0.80.1] - 2026-10-26

### Fixed

- The landing checks compare against the branch releases land on: the `branch` that `.github/shipmill.toml` sets, and origin/HEAD only when the config sets none. In a repo whose GitHub default branch was an older, diverged branch, `shipmill worktrees` read every merged worktree as not landed, so the gate's prune removed none, and `shipmill status` read the repo as stuck, with the fix `fetch origin master:master`. Now `shipmill worktrees` and its prune, the gate's `--refresh`, `shipmill milestones`, the repo line of `shipmill status`, and the github-ship-watch skill's fetch, plan, and reads at `origin/<branch>` all follow the config's branch; the gate's `--refresh` reads it from the config at GitHub's default branch, never from a checkout a session left on a pull request's branch. `shipmill doctor` WARNs when GitHub's default branch isn't the config's branch, with the fix `gh api -X PATCH repos/<repo> -f default_branch=<branch>` (#694)
- The gate's App check and the App's bot login sign their JWT when they run, not with the tick's start time. A tick whose prune ran past the JWT's 9 minutes no longer ends in `GitHub refused the JWT ... 401`, which read like a wrong key (#694)

## [0.80.0] - 2026-10-26

### Added

- product-intake plans a goal: it proposes a `goal-plan` issue from `references/plan.md` (under `observe` it only reports the plan's text), acts on the maintainer's trusted reply alone, and on an accept files each `feature` and `fix` item in Work order with its plan-item marker and `Serves: G-n`, as a sub-issue of the plan (through `chains.py link --child --no-text`, so the accepted plan's body is never edited) with a `Depends on` line and GitHub's relation for each `(after W-k)`, starting no build and writing no spec; the spec gate lists a feature item of an accepted plan as chosen work that still needs its own approved spec (#517)
- `chains.py link --no-text` writes only GitHub's relation (`--blocked-by` or `--child`, with or without `--product`) and no `Depends on` line, and exits 2 when the forge refuses the relation, there being no line to fall back on (#517)

### Changed

- A person's dispatch for a fork's pull request runs only the head SHA they read, so a push after the read never runs with `ANTHROPIC_API_KEY` or a token that dispatches downstream workflows. `evals.yml` takes a `sha` input that a dispatch with `pr` needs; before any checkout or secret the run reads the pull request's head and exits 1 naming both commits when it isn't `sha`, checks `HEAD^2` of `refs/pull/<N>/merge` again after the checkout, starts its summary with `evals: measured <sha> of #<N>`, and records `pr` and `head` in `meta.json`. The downstream caller `shipmill init --downstream` writes has a required `sha` on `workflow_dispatch`; the reusable `downstream.yml` takes it as an optional input, compares it with the head before the App's key reaches the disk, and passes `--sha` to `shipmill downstream start`, which exits 1 for another head before it writes a check, mints a token, or dispatches, and exits 2 naming `shipmill init --downstream --force` for a missing or malformed `--sha`. The fork hold and the fork refusal print `-f pr=<N> -f sha=<head SHA>`, the collect dispatch carries `sha` only to a caller that declares it, so a caller written before it keeps working unpinned while a person's start on it is refused, and `shipmill doctor` WARNs on such a caller; rewrite it with `shipmill init --downstream --force` (spec 025, S-025-18 to S-025-23; spec 032, S-032-17 to S-032-24) (#545)

### Fixed

- The ship watch's `PRS_OPEN` fix follows `[autonomy] land`, as the gate does, instead of the deprecated `[agents] prs`: none under `act`, merging the pull requests labelled `shipmill-ready` under `propose`, `[autonomy] land` named under `observe`, with the legacy prompt reading and the hold applied as `shipmill autonomy` reads them; an invalid `land` exits 2, and `TRIAGE_MODE` no longer echoes `prs` (#691)
- The ship watch's `TRIAGE_MODE` row names the effective `triage`, `fix`, and `land` levels with their source, as `shipmill autonomy` reads them (`triage act (default), fix act (default), land propose (hold)`), instead of the `[agents]` prompt's words, so an `[agents]` table holding only `prs` no longer gives an empty row; an invalid `[autonomy] triage` or `fix` exits 2 as an invalid `land` does (#693)

## [0.79.0] - 2026-10-26

### Changed

- `shipmill gate` counts open pull requests as work when `[autonomy] land` is `propose` or `act`, and not under `observe`, whatever `[agents] prs` says; a config without the agent stage keys reads `land` as the prompt does for this release ("merge when green" lands). Every launch prompt carries an `Autonomy:` line with each agent stage's effective level, naming the hold issue when one is open. `[agents] prs` is deprecated: still accepted, ignored, and `doctor` warns naming `[autonomy] land`. shipmill-setup's checklist drops its `LANDING_OFF` row, which `AUTONOMY_IMPLICIT` replaces (#662)
- Tests: the suite takes about half the CPU; git fixtures are built once and copied per test, and most delivery hook cases call the hook's `main` in process (#667)
- A draft pull request belongs to whoever opened it (D-52): github-pr-triage leaves drafts out of its review and landing and reports each as "draft, left to its author", `pr_gate.py` reads a draft as DRAFT with exit 8 whatever its checks, and github-issue-triage hands over only pull requests marked ready (#673)

### Added

- `shipmill status` prints an `autonomy` line after the repo line with every stage's effective level, `(held)` beside each stage a `shipmill-hold` issue lowers and `(from the prompt)` beside each stage the legacy reading took from `[agents] prompt` (with `shipmill upgrade --apply agent-autonomy` as its fix), and `status --json` adds one `AUTONOMY` line after github-ship-watch's rows whose `autonomy` key holds the stages `shipmill autonomy --json` prints. The open pull requests now follow `[autonomy] land` instead of `[agents] prs`: under `observe` they wait on you with the `[autonomy] land` fix, under `propose` the ones labelled `shipmill-ready` wait on you to merge (a new `to merge` line) and the rest are the gate's work, and under `act` all are the gate's work; the `landing` line names land's level (#663)

## [0.78.0] - 2026-10-26

### Added

- `shipmill autonomy [--ref REF] [--json]` prints every stage's `[autonomy]` level (triage, fix, land, release, each deploy environment, rollback, intake, upgrade), configured and under the `shipmill-hold` stop switch, with its source (`default`, `config`, or `hold`) and the open hold issues, from the config at `origin/HEAD` by default; `shipmill decide levels` lists `triage`, `fix`, and `land` with source `autonomy`; `doctor` names the three agent stages in its autonomy line and warns when one is set in a config without `[agents]` (#660)
- For one minor release, a config with `[agents]` that sets none of `[autonomy]` `triage`, `fix`, and `land` reads `land = "act"` from an `[agents] prompt` that says "merge when green" or "land", shown with source `prompt` by `shipmill autonomy` and warned about by `doctor`; the `agent-autonomy` upgrade (`shipmill upgrade --apply agent-autonomy`) writes the three keys with those levels, keeping the rest of the file byte for byte (#661)
- Setup reads and writes autonomy levels: `setup_state.py` reports `AUTONOMY_IMPLICIT` for a config with `[agents]` whose `[autonomy]` sets none of `triage`, `fix`, and `land`; `shipmill init` writes `[autonomy]` uncommented with `release` at its default, and `init --operate` adds `rollback` and each `deploy.<env>` the policy doesn't set, at their defaults (#664)

## [0.77.0] - 2026-10-26

### Added

- `[autonomy]` takes `triage`, `fix`, and `land`, the stages agent sessions run, each `observe`, `propose`, or `act` (default `act`, `act`, and `propose`); any other value exits 2 naming the key and the levels, and an open `shipmill-hold` issue turns each `act` into `propose`. Nothing reads them yet, so no session changes behaviour (#659)

## [0.76.0] - 2026-10-26

### Fixed

- A `shipmill` on PATH whose `--version` exits 0 with anything but `shipmill X.Y.Z` is now the `SHIPMILL_OUTDATED` `shipmill on PATH` row, quoting the first line it printed with `uv tool upgrade shipmill` as its fix, instead of making `watch_state.py` exit 2 and stopping every gate tick (#628)

### Added

- github-ship-watch's Direction section says what a session does for each DIRECTION_PENDING row: it opens the `shipmill-direction` issue as the App, asks the maintainer for the five sections of `docs/product.md` through the needs-decision protocol, closes the issue as not planned on a decline, and otherwise writes the file from the maintainer's words only and opens a `shipmill/direction` pull request that the maintainer merges (#637)

### Changed

- The skills follow roles (spec 036): github-issue-triage files a step only a person can do labelled `role:<name>` and assigned that role's users at once (`role:maintainer` when none fits, never `human`), assigns an ASSIGN_DUE item with no comment, reads NO_ASSIGNEE as a state read without the `--role` flags instead of asking who does it, and mentions a role's teams in the hand-off; shipmill-setup documents `[agents.roles]` and its `role:<name>` labels (#643)

## [0.75.0] - 2026-10-26

### Added

- The watch asks for a missing direction: for a repo with `[agents]`, `watch_state.py` reports DIRECTION_MISSING (an action for the maintainer) when the default branch has no `docs/product.md` or `shipmill product check --ref` refuses it, and DIRECTION_PENDING (an agent's) with what a session does on the direction question; a closed direction issue is a decline, noted in TRIAGE_MODE, and `triage_state.py` marks a direction issue's `--json` line so the watch keeps it out of the issue rows with no read of its own (#636)
- `shipmill gate` and `shipmill status` pass the resolved `[agents.roles]` to the state scripts as one `--role` flag per role, `maintainer` included; `watch_state.py` takes the flags and passes them to `triage_state.py`, the gate's session prompt tells the session to pass the same flags, and the watch and status list a person's item's teams and read a team-only `WITH_PERSON` line (#640)

## [0.74.0] - 2026-10-25

### Added

- `shipmill product check --ref REF` checks `docs/product.md`, and the files its moved sections link, as committed at a git ref instead of the working tree: exit 1 with `no docs/product.md at <ref>` when the file is absent there, and 2 for a ref git can't resolve (spec 034) (#634)
- Direction issue: `triage_state.py` tells shipmill's question for a missing `docs/product.md` (the `shipmill-direction` label, its marker first, a trusted author or the `--bot-login`), the watch keeps it out of ISSUES and ISSUES_OPEN, triage posts no verdict on it, and setup creates its label with `[agents]` (#635)
- `[agents.roles]` in `.github/shipmill.toml` maps role names to the GitHub logins and `@org/team` entries who receive the steps an agent can't do, with the maintainer defaulting to the host's gh login and an empty role falling back to the maintainer; `shipmill roles` prints them resolved, with `--json` and `--flags`, and a malformed table exits 2 from every reader of the config, `shipmill doctor` included (spec 036) (#638)
- `triage_state.py` reads an issue labelled `role:<name>` as a person's item exactly as a `human` one (which counts as `role:maintainer`), and takes `--role NAME=FILLER[,FILLER...]` flags, one per role with `maintainer` among them, exiting 2 on a malformed or incomplete set: with them, an unassigned person's item whose roles resolve to a user reads ASSIGN_DUE, even while held, with an `assign` list in `--json` (an undefined role falls back to the maintainer, and the note says so), a team-only role's item is handed off to its team with `assignees` and `teams` lists on its HANDOFF_DUE and WITH_PERSON lines, and NO_ASSIGNEE is never read; without them, an unassigned person's item still reads NO_ASSIGNEE (#639)
- `chains.py show` lists an issue labelled `role:<name>` as a person's item, like a `human` one: its executor reads `person: @login,...` from its assignees, or its `role:<name>` labels when it has none (#641)
- shipmill-setup: `setup_state.py` wants `role:maintainer` wherever it wants `needs-decision`, and `role:<name>` for each role `[agents.roles]` defines, and still wants `human` (#642)

## [0.73.1] - 2026-10-25

### Fixed

- The skills list a pull request's files without `gh pr diff --name-only`, which GitHub refuses with HTTP 406 past 300 files: github-issue-resolve checks its pull request's files with `git diff --name-only origin/<default>...HEAD` in its worktree, and github-pr-triage's reviewer brief reads them for the review rubric through the paginated files API (#632)

## [0.73.0] - 2026-10-25

### Added

- github-issue-triage's `needs-decision.md` opens with "Who decides": in a repo whose config has `[agents]`, a session asks `shipmill decide classify` first, then places what code doesn't see in a zone, takes the strictest level among a decision's zones (`unknown` when none fits), and follows it: `act` goes on, `notify` posts a `<!-- shipmill:decided zone=<id> until=<time> -->` comment and the `decided` label and goes on, `ask` asks with the zone on the question's second line, and `never` prepares the change and leaves the step to the maintainer, even after a yes in chat; it also says how a veto is taken up. The design gate, the spec gate, the triage comments, and the resolve, PR triage, and product intake skills point to it, `docs/flow.md` gains a "Who decides" section with the zone table, and four eval cases cover act, notify, ask, and never (spec 030, S-030-21, S-030-22) (#613)

### Changed

- In a repo whose config has `[agents]`, a won't fix, duplicate, postpone, or close verdict, a reading of a spec, and an additive contract change carry a decided comment and the `decided` label at their default `notify` level, where they went on before with only the triage comment (#613)

### Fixed

- The merge gate reads a pull request of more than 100 files through GitHub's files API, so one over 300 files no longer fails it with HTTP 406, and one past the API's 3000-file cap stops it naming the gap instead of being judged on a partial list (#630)

## [0.72.0] - 2026-10-25

### Added

- `shipmill --version` prints `shipmill <version>`. `doctor` (a WARN) and `shipmill status` (waiting on you) report a `shipmill on PATH` whose version differs from the plugin install a session loads: `uv tool upgrade shipmill` when it is older, predates `--version`, or doesn't answer it (a 10 s timeout, or it can't start), the plugin's update when it is newer; `watch_state.py` reads it as one `SHIPMILL_OUTDATED` row, asking the first `shipmill` on PATH outside its own environment with only PATH and HOME (spec 031, S-031-25 to S-031-29) (#583)
- In a repo whose default branch's config has `[agents]`, `pr_gate.py` reads a pull request's zones with `shipmill decide classify`: a `never` zone is the new `MAINTAINER_ONLY` verdict, exit 7, which `--maintainer-accepted` doesn't lift; an `ask` zone waits on the maintainer with exit 5; a `notify` zone keeps the verdict and prints a `notify:` line; and `shipmill gh pr merge` or a `shipmill gh api -X PUT .../pulls/<n>/merge`, as the App, exits 2 for a pull request with a `never` zone, since only the maintainer merges it, by hand (#612)

### Changed

- `README.md` and `docs/install.md` give `uv tool install shipmill` as the one way to get the CLI, with `uv tool upgrade shipmill` after each plugin update, and `uvx shipmill <command>` for a run without the install, in place of the `@v0` git form (S-031-30) (#583)
- In a repo whose default branch's config has `[agents]`, an agent's pull request that edits `docs/product.md` or `docs/product/` is `MAINTAINER_ONLY` (`pr_gate.py` exit 7) instead of `NEEDS_DECISION` (set `direction = "ask"` under `[decisions]` for the old behaviour), and a pull request in the `security` (`.github/**`), `scope` (a spec whose status becomes `approved`), or `contract-change` (an entry under a `[bump] major` heading) zone exits 5 until `--maintainer-accepted` (#612)

## [0.71.0] - 2026-10-25

### Added

- `shipmill decide levels [--ref REF] [--json]` prints every zone of the decision policy (spec 030, D-48) with its level, its floor, and where the level comes from (`default`, `config`, `autonomy`, or `fixed`), the release side's stages mapped from `[autonomy]` beside the agent zones; `shipmill decide classify (--pr N | --files PATH...) [--ref REF] [--json]` prints the zones code detects for a change (`direction`, `decision-policy`, `security`, `protected`, `scope`, `contract-change`), each with its level and reason, the strictest level, and the `D-n` candidates, the levels read at `--ref` (default `origin/HEAD`), never from the change (#610)
- `shipmill doctor`, for a config with `[agents]`, prints a `decisions` block: the veto window and one line per zone with its level and source, and a WARN for each zone `[decisions]` sets below its default, for an unset `[agents] app_id`, and for a repo without the `decided` label; a config with `[decisions]` and no `[agents]` gets one WARN that nothing reads the section. `setup_state.py` wants the `decided` label with `[agents]`, so `LABELS_MISSING` names it and `--fix` creates it (spec 030, S-030-19, S-030-20) (#611)

## [0.70.0] - 2026-10-25

### Fixed

- A release can publish before it moves its references (D-50): a lane's new `after_publish` workflows start only once each `dispatch` run of the release succeeded and PyPI serves the version, and a publish that fails or never ends leaves them unstarted, naming the run; a lane without `after_publish` lands as before. `move-major-tag.yml` also moves the plugin marketplace `ref`, for the newest stable release only. shipmill's own config turns `after_publish` on in a follow-up, once a release with it is on PyPI and the plugin installs have it (#598)
- github-pr-triage lands a spec pull request on a trusted answer only while the spec is the one the maintainer answered on: it compares the pull request's own change to the spec file at the answered head and at the current head, lands through a rebase or a renumbered `D-n`, and asks again with a new needs-decision question after any other change to the spec (#620)

### Added

- `.github/shipmill.toml` takes an optional `[decisions]` section (spec 030, D-48): each key a zone id set to `act`, `notify`, `ask`, or `never`, and `veto_hours` for the notify window (1 to 168, default 24); a zone left out keeps its default, and a level below a zone's floor, a fixed zone, a release-side zone `[autonomy]` sets, or an unknown key stops the run with exit 2. Nothing reads the levels yet (#607)
- `triage_state.py` reads an issue labelled `decided` whose decided marker is followed by a trusted comment starting `veto`, and no newer `<!-- shipmill:veto-handled -->` comment, as `VETOED`, an action read right after `DECIDED`, for closed issues updated in the last 14 days too; `watch_state.py` lists such issues and pull requests, open, closed, or merged, in a `VETOED` row that starts a gate session (spec 030, S-030-14 to S-030-16) (#608)

## [0.69.0] - 2026-10-25

### Changed

- A spec pull request is approved by the maintainer's merge or by a trusted answer to its needs-decision question that takes every recommendation; after such an answer github-pr-triage lands the spec pull request once it is mergeable and green, the maintainer may still merge it by hand, an answer that changes a recommendation revises the spec, and a spec pull request that edits `docs/product.md` stays the maintainer's (D-49) (#547)

### Added

- Zoned decisions in the decisions log and the weekly retro (spec 030): `decisions.py add --zone <id>` records a rule an agent set at notify with a `- Zone: <id> (notify, veto until <time>)` line, the time `--decided-at` (default now) plus `[decisions] veto_hours` (default 24), and `decisions.py check` refuses a `Zone:` naming no zone id; `retro.py gather --decisions` counts per zone the window's decided markers, veto-handled markers, zoned needs-decision questions, and those answered with the recommended option, and proposes `Decision policy: <zone> from notify to ask` at `--raise-at` vetoes (2) and `from ask to notify` when at least 5 questions over `--lower-after` windows (4) were all answered recommended, never below a zone's floor (#609)

## [0.68.0] - 2026-10-25

### Changed

- shipmill's own goals carry measures: G-1 `issue_to_release_p90 < 2d` and G-2 `change_failure_rate <= 5%`; G-3 to G-7 carry none, since the forge can't measure them yet (#484)

## [0.67.0] - 2026-10-24

### Added

- The instructions for work across a product's repos (spec 038, D-47): github-issue-triage's Reports from other repos has the home repo's coordinator route each `upstream` report with `shipmill gh --product` and `chains.py link --product`, ask through needs-decision when it can't tell the owning repo, and close the report with a summary of each child, how it closed, and its pull request, as completed or not planned, never changing files, pushing, branching, opening a pull request, or merging outside the home repo; `comments.md` has an Upstream report template (Reproduce, Touches, Suspected code, a `Guess:` when the cause wasn't traced, and the triage comment with or without a coordinator); github-issue-resolve's Phase 2 has the upstream verdict, which reports in the agent's own repo and holds its issue with `chains.py link --blocked-by`; and triage-rubric.md has a component write a dependency on another repo as a stand-in. A fault in another repo, or a gap in a spec the project implements, is now always reported in the repo's own tracker instead of filed in the other repo, so the Clarify template no longer says "Filed upstream as" (#589)

### Fixed

- A release no longer fails the gate's ticks while PyPI doesn't serve it yet: a skill script's `uvx shipmill==<version>` that uv finds no such version of runs once more as `uvx --refresh-package shipmill ...`, and when that fails too `watch_state.py` prints a report-only `PYPI_WAIT` row (`shipmill==<version> waits for PyPI`, the release's `publish.yml` run as its fix) in place of the rows that read owed, and reads the rest instead of exiting 2; any other uvx failure still exits 2. A launchd job on the floating `git+https://github.com/shipmill/shipmill@v0` source, whose CLI never lags, now gets its rewrite to `shipmill@latest` in `doctor` (a WARN), `status`, and the tick report whether or not its CLI lags (#597)

## [0.66.0] - 2026-10-24

### Added

- `chains.py link` reads the checkout's `[product]` table (spec 038): in a component (`[product] home`) it exits 2 before any write when a reference names another repo than its own, and the coordinator's new `link --product P --child C` writes through `shipmill gh --product <P's repo>`, exiting 2 without `[product] repos` or for a reference outside the listed repos and the home repo (#587)
- The coordinator's view of upstream reports (spec 038, D-47): github-issue-triage's `upstream_state.py <owner/home>`, run in the home repo's checkout, reads every open `upstream` report of the home repo (through gh) and of each repo `[product] repos` lists (through `shipmill gh --product`) as ROUTE_DUE, ASKED, ANSWERED, ROUTED, CLOSE_DUE, or UNTRUSTED, counting a report's sub-issues and `Depends on` lines as its children and never reading an untrusted author's report past its author (D-16); in a checkout with `[product] repos`, github-ship-watch's `watch_state.py` reports UPSTREAM_DUE as an agent's row, so the gate starts the coordinator's session, UPSTREAM_ASKED, UPSTREAM_UNTRUSTED, and a failing run as one UPSTREAM_UNREADABLE row (#588)

## [0.65.0] - 2026-10-24

### Added

- The coordinator's token (spec 038, D-47): in the product's home repo, `shipmill app-token OWNER/NAME --product` and `shipmill gh --product OWNER/NAME` use a second App token over the repos `[product] repos` lists under OWNER, asking contents read, issues write, pull requests read, and metadata read; a token GitHub grants wider than asked is refused, it is cached apart in `app-token-product-<owner>.json`, `gh --product` refuses the commands that write code or pull requests, the home repo's gate checks the App on every listed repo before it starts a session, and a `[product]` naming the checkout's own repo exits 2 (#585)

## [0.64.0] - 2026-10-24

### Added

- Config: an optional `[product]` table (spec 038, D-47), `home = "owner/name"` in a component repo or `repos = [...]` in the product's home repo, read strictly by `shipmill plan` and the gate alike; `repos` needs `[agents] app_id`, and in a component `shipmill gh -R` and `shipmill app-token` for any repo but the checkout's origin exit 2 naming D-47 before a token is minted (#584)
- An open issue labelled `upstream`, a report of a fault another repo owns, reads UPSTREAM in `triage_state.py`, right after UNTRUSTED and before every other state, and is never an action; a new `--home OWNER/NAME` words its note (`routed by OWNER/NAME`, else `no coordinator: waits for the maintainer`, plus `asks the maintainer` while its needs-decision question has no reply), and a closed one never reads SUSPECT_CLOSE. `watch_state.py` passes the config's `[product] home` as `--home` and lists the reports in ISSUES_OPEN as `UPSTREAM #N`, so the gate starts no session for one, and `setup_state.py --fix` creates the `upstream` label wherever it creates `needs-decision` (spec 038) (#586)

## [0.63.0] - 2026-10-24

### Changed

- D-47 supersedes D-45: the role that owns delivery across a product's repos is the coordinator, which routes `upstream` reports, closes stand-ins and builds the queue, and never plans the product; `docs/design/product-layer.md` says so (#580)

## [0.62.0] - 2026-10-24

### Added

- `docs/design/product-layer.md` gains an Across repos section: components stay in their repo while the product's manager owns every cross-repo step, a bug found in another repo's module reported in the agent's own repo, the manager as a role on a home repo rather than a store, the forge's own cross-repo objects, why no external tracker is needed, and decisions D-45 and D-46 (#338)

## [0.61.0] - 2026-10-21

### Removed

- `[agents] plugin_update` (spec 031): a config that sets it, whatever its value, now exits 2 with `[agents] plugin_update was removed (spec 031); delete it`, and `doctor` fails the policy with that line instead of warning; delete the key (#553)

## [0.60.0] - 2026-10-21

### Deprecated

- `[agents] plugin_update` (spec 031): gate sessions load the installed plugin and report its lag, so the gate ignores the key whatever its value and runs no `claude plugin update`; `doctor` warns naming it, and the next minor release refuses it. `shipmill upgrade` no longer offers `plugin-update`, `shipmill init` no longer writes it, and a release closes an open `plugin-update` upgrade issue as withdrawn; `gate --json` drops the `plugin` field of the daily update (#552)

### Changed

- The install guide, the policy reference, and the shipmill-setup and github-ship-watch skills describe the pinned CLI, the marketplace serving release tags, gate sessions loading the installed plugin, `requires`, and the `plugin_update` deprecation, and no longer describe a gate paused on a stale plugin (#552)

## [0.59.1] - 2026-10-21

### Fixed

- A gate held because PyPI doesn't serve the plugin version sessions load no longer reads healthy: `shipmill status` reads the gate's last `PYPI_WAIT` tick as a wait on you (`paused: plugin <version> waits for PyPI`), and `doctor` asks PyPI for that version itself, a WARN on 404 or when PyPI doesn't answer; each names the fix, the release's `publish.yml` run, or a new one with `gh workflow run publish.yml --repo shipmill/shipmill -f tag=v<version>` (#569)
- A gate whose launchd job runs a pinned `--tool` or the pre-org `@v0` source is told to rewrite its job with `uvx shipmill@latest --repo <checkout> launchd <repo>` when its CLI lags, not `uv tool upgrade shipmill`, which never changes the job; a job on `shipmill@latest` is told to run now with `launchctl kickstart` (#570)

## [0.59.0] - 2026-10-21

### Changed

- `shipmill gate` no longer pauses on a lagging plugin: `PLUGIN_STALE` is gone, and the tick starts the session and reports, each on one line with its fix, every install of `shipmill@shipmill` older than the latest release (with `claude plugin marketplace update shipmill && claude plugin update shipmill@shipmill --scope <scope>`), an install keyed on the gate's linked worktree that no session loads (delete its entry in `~/.claude/plugins/installed_plugins.json`; shipmill never writes that file), the gate's own CLI when it lags (`uv tool upgrade shipmill`, or `uvx shipmill@latest --repo <checkout> launchd <repo>` for a launchd job on the old `@v0` source), and a config whose `requires` the version sessions load doesn't meet; with `[agents] notify = true` the first gate on a host to find a lagging install sends one desktop notification per release (marker `~/.cache/shipmill/plugin/<version>.notified`). The one plugin hold left is PyPI answering 404 for the version sessions load: the tick reads `PYPI_WAIT: plugin <version> waits for PyPI` and the next tick tries again. `doctor` and `shipmill status` report the same as WARNs and rows, with no line saying a gate starts no session, and `shipmill launchd` writes jobs that run `shipmill@latest` unless `--tool` names another source (spec 031) (#551)

## [0.58.0] - 2026-10-20

### Added

- `shipmill downstream collect` finds each downstream run `downstream start` dispatched by the `shipmill-id` in its run-name, links it as the check's details URL, and concludes the check: `success`, `failure` naming the run's conclusion, or `timed_out` for a required downstream, always `neutral` with the result in the title for a report-only one, and a failure naming the run-name rule when no run shows within 2 minutes; the summary names the tested SHA, links the run, and lists its failed jobs, never a log line (#511)
- The weekly retro passes `--goals`, adds a Goals section to its tracking comment, and proposes `Direction: G-n met for N weeks` and `Direction: G-n stalled for N weeks` issues, at most one open per goal; it never edits the direction itself (#512)
- `intake_state.py --plans` reads each goal plan issue's state from the maintainer's reply: PLAN_OPEN, PLAN_ANSWERED (`decline` or `edit`), PLAN_ACCEPTED until every `feature` and `fix` item is filed (and in the named milestone), PLAN_FILED, PLAN_MALFORMED naming the line, and PLAN_DECLINED with the reason; only an OWNER, MEMBER, or COLLABORATOR other than the `--bot-login` answers, a `plan-revised` comment makes an earlier answer stale, and an accept older than the body's last edit reads PLAN_OPEN (#514)
- `watch_state.py` reports a PLANS row, from `intake_state.py --plans`, listing the goals whose plan is due and the plan issues that are malformed, answered, or accepted, and `shipmill gate` starts a session for it; with `--trusted-only` a plan issue the `--bot-login` didn't open is UNTRUSTED and starts none. Intake never reads a `goal-plan` issue as feedback, and triage reads a plan carrying intake's `Triage: **plan**` comment as TRIAGED (#515)
- `shipmill doctor` checks downstream tests for a policy with `[downstream]`: a FAIL naming `shipmill init --downstream --force` for a caller workflow missing a trigger, the reusable call, `actions: write`, or `checks: write`, a FAIL for a missing `SHIPMILL_DOWNSTREAM_KEY` secret, a line per downstream on its workflow's inputs and run-name (a WARN when your login can't read it), and, with the App's key on the host (`--app-key`), a FAIL for a downstream the App isn't installed on; `docs/release-lanes.md` gains a "Downstream tests" section, and the setup and landing skills cover them (#516)
- `requires = ">=X.Y"` at the top of `.github/shipmill.toml` names the oldest shipmill the config is written for: an older CLI, `watch_state.py`, or `setup_state.py` exits 2 with the bound, its version, and how to update, before it refuses a key it doesn't know; `shipmill init` writes it, and `shipmill upgrade --apply` raises a lower one (#549)

### Fixed

- `shipmill gate` with `[agents] prs = true` starts a session when a push lands on an open pull request a session already looked at, instead of waiting out `retry_hours`: `watch_state.py --json` adds each listed pull request's head SHA to its `PRS_OPEN` row, and the gate's fingerprint counts it (#546)

### Changed

- The plugin pins its CLI: the skills, their scripts, and the hooks run `uvx shipmill==<the version in the plugin's plugin.json>` from PyPI instead of the `@v0` tag's source or a `shipmill` on PATH, and a missing or malformed `plugin.json` exits 2 naming it; the wheel ships `shipmill/.claude-plugin/plugin.json`. The marketplace entry names the release tag, which each release's stamp moves with `plugin.json` and every pinned line, and the gate, `doctor`, `status`, and `watch_state.py` read the latest release from that ref instead of `gh release view` (spec 031) (#548)

## [0.57.0] - 2026-10-20

### Added

- An `evals` workflow that runs the agents' eval suite with `claude plugin eval` on a pull request touching the skills, the plugin, `evals/`, or the gate's session paragraphs, weekly, and by hand, and compares a pull request's run against the default branch's baseline (or its merge base's when the baseline is missing, stale, or another model's); a fork's pull request fails naming `gh workflow run evals.yml -f pr=<N>`, and `shipmill evals check --gate` names the kinds short of the first suite's counts; until the suite holds them, the pull request job reports and exits 0 (#448)
- `shipmill product measure <G-n> "<metric> <comparison> <target>"` writes or replaces a goal's measure line and `--clear` removes it, leaving every other line as it was, also in a Goals section moved to `docs/product/`; shipmill-setup offers each goal a measure from the registry and writes only the ones the maintainer gives (#506)
- `shipmill downstream start` writes a `downstream: <name>` check per `[downstream]` repository on a pull request's head and dispatches each one's workflow with a token minted for the App and limited to that repository, then dispatches the collect run; a fork's pull request waits for a person's `workflow_dispatch`, and the reusable `.github/workflows/downstream.yml` runs it from the default branch's checkout, never the pull request's code (#508)
- `retro.py gather --goals` reports per goal of `docs/product.md`: the issues and pull requests that served it this week and the week before (by the latest trusted verdict's `Serves:`, a spec's `serves:`, or a plan's `Serves:`), whether its measure is met with the weeks in a row, and whether it stalled; then the `quality bar` row, the verdicts postponed for no goal or declined for a non-goal with the most-cited one, and the agent pull requests whose plan names no goal; a checkout off `origin/HEAD` or a direction `shipmill product show` refuses exits 2 (spec 027) (#509)
- product-intake's `intake_state.py --plans` reports PLAN_DUE for a goal with no open plan: `no-work` when no draft or approved spec, triaged issue, pull request plan, open opportunity, or plan item serves it and its newest plan wasn't declined, and `requested in #N` for a trusted `goal-plan` request; with `--wip N` a `no-work` plan waits for room (PLAN_WAITS) and a request never does (#510)
- `shipmill init --downstream` writes `.github/workflows/downstream.yml`, the workflow that runs the `[downstream]` repositories' tests on each pull request through shipmill's reusable `downstream.yml`; it refuses a policy without `[downstream]` and an existing file without `--force` (#513)

### Fixed

- An interactive gate session (`claude --bg`) that `claude agents` lists as `failed`, or as `done` within 60 seconds of its launch, no longer counts as an attempt toward `retry_hours`: the next tick reads `SESSION_DEAD`, names the session and its state with `claude logs <id>` as the fix, starts another, and holds the same findings for `retry_hours` after 3 dead in a row, as a headless one does (#500)
- github-issue-triage's `chains.py link` writes as the App: run from a checkout whose `.github/shipmill.toml` sets `[agents] app_id`, the native blocked-by or sub-issue relation and the `Depends on` line it adds to the body go through `shipmill gh` (from PATH, else through uvx), and a `shipmill gh` exit 2 stops the link with its message, never retried with plain `gh`; reads stay on plain `gh`, and without app_id nothing changes. Before, both writes ran as the maintainer's gh login (D-14) (#526)

## [0.56.0] - 2026-10-20

### Added

- A stable release that promotes an rc names in its plan reason how many of the issues the rc fixed have a requester who confirmed its pre-release notice, such as `2 of 3 requesters confirmed`; the count is reported only and never makes a lane due or holds one (S-021-8) (#395)
- `shipmill evals compare --base <main.json> --head <pr.json>` gates a pull request's eval run against the default branch's (spec 025, D-37): it reads the runner's `aggregate-result.json` (`schemaVersion` 1), counts a run as passed only when every scored grader passed and a run that errored, aborted, or skipped its paid graders as failed, exits 1 when the suite's pass rate drops more than 0.05 (`--tolerance`), a case falls from 3 of 3 to at most 1 of 3, or a new or `--changed` case passes fewer than 2 of 3, prints each regressed, new failing, improved, and removed case and both pass rates, fails with `evals: budget reached after <n> of <m> runs` on a run stopped at its budget, and exits 2 on a missing or malformed `aggregate-result.json` (#443)
- Delivery hooks: the PreToolUse hook refuses a `git push` to the default branch (`default-branch-push`, off with `[hooks] default_branch = false`) and a `cp`, `mv`, or `rsync` of a `[hooks] private` path out of the repo (`private-paths`) (#444)
- The docs name the delivery hooks: github-pr-triage's rule 8 and landing reference say which forms a hook refuses, shipmill-setup asks for `[hooks] private` paths and reads `doctor`'s hooks block, `docs/release-lanes.md` documents the `[hooks]` keys, and `docs/install.md` says the hooks come with the plugin, need `uv`, and what happens when one can't start (#447)
- `docs/direction.md`, a guide for the maintainer to the product's direction (`docs/product.md`): what it holds, what the agents do with it, its structure, and the `shipmill product` commands that change it; linked from the README, `docs/flow.md`, shipmill-setup, and `shipmill doctor`'s direction FAIL line (#498)
- The policy reads an optional `[downstream]` section: the App id, a run timeout, and one table per downstream repository (`repo`, `workflow`, `ref`, `report_only`, `timeout_minutes`), refusing a malformed one with exit 2 naming the key; nothing runs on it yet (#503)
- Tests prove the PR gate reads a `downstream: <name>` check like any check: `FAILURE`, `TIMED_OUT`, and `ACTION_REQUIRED` fail it, a running one keeps it pending, and `NEUTRAL` and `SUCCESS` count as green (#504)
- A goal in `docs/product.md` may carry one measure on the line under it, `  measure: <metric> <comparison> <target>`, naming a metric from a fixed registry (`deploy_frequency`, `lead_time_median`, `human_touch`, ...) and a target in its unit: `shipmill product check` refuses an unknown metric or comparison, a target in the wrong unit, and a misplaced or second measure line with its file, line, and rule; `shipmill product show --json` gives every goal a `measure` key, and the PR gate and `specs.py check` accept the line (spec 027) (#505)
- product-intake's `plans.py`: `check` holds a goal plan's body to its grammar (marker, goal, headings, Work items, Milestone), naming the line and rule for each problem, and `items` lists a plan's items with the issue filed for each (#507)

### Removed

- `[lanes.stable] min_soak_days`, deprecated in 0.53.0: a policy that sets it, whatever its value, exits 2 with `[lanes.stable] min_soak_days was removed (spec 029); delete it, or run shipmill upgrade --apply stable-every-batch`, and `shipmill doctor` reports that as its policy failure. `shipmill upgrade --apply stable-every-batch` still reads and fixes such a config. `promote_from = "rc"` promotes the newest rc once a stable trigger is due, whatever its age, and its reason says how old the rc is, `promotes v1.5.0rc2, cut 1 day(s) ago`, instead of `soaked 1 day(s)` (#464)

### Fixed

- CI now runs `shipmill product check` and `shipmill review check`, as spec 024 says, so a malformed `docs/product.md` or `REVIEW.md` can no longer reach main (#493)
- An eval case's write through `shipmill gh`, or `uvx ... shipmill gh` headless, now reaches the offline `gh` stub instead of failing for want of the App's token: `evals/bin` gains `shipmill` and `uvx` shims that send `shipmill gh` to the stub, logged with `"via": "shipmill"` so a grader still catches a plain `gh` write, and pass every other command to the real program (#494)
- A release proposal, an issue, a comment, or release notes too long for one command-line argument no longer fails with `Argument list too long`: shipmill passes every body to `gh` on stdin, and one over GitHub's limit (65,536 characters for an issue or comment, 125,000 for release notes) is cut to fit and ends with a line linking the changelog that holds the full text (#499)
- Gate: a lost Claude Code login no longer burns the retry window. Before a launch the gate runs `claude auth status --json`, and when Claude Code isn't logged in it starts no session and reports `CLAUDE_AUTH` with the fix (`claude auth login`), sending one desktop notification per failure episode with `[agents] notify = true`; `doctor` checks the login too. A headless session whose log holds an authentication failure, or that ended within 60 seconds of its launch (by its log's last write) with no result in its log, doesn't count toward `retry_hours`: the next tick launches again and reads `SESSION_DEAD`, naming the dead session, how many died in a row, and its log's last line; after 3 dead sessions in a row the same findings wait for `retry_hours` again. `shipmill status` reports both, and github-ship-watch's `watch_state.py` reports a gate whose sessions end dead as `GATE_SESSIONS_DEAD` (#500)

### Changed

- shipmill-setup no longer edits a repo's CLAUDE.md, AGENTS.md, or CONTRIBUTING.md when it turns changelog fragments on: `setup_state.py`'s new `CHANGELOG_RULES` warning names each line there that mentions Unreleased as file and line, and leaves the change to the maintainer (D-42) (#496)

## [0.55.0] - 2026-10-19

### Added

- A deployment tells its fixed issues: after a tag's first successful deployment to an environment of `[environments]`, read from GitHub deployments, the watch reports UNANNOUNCED for each closed issue whose fix the tag holds and the environment didn't run before, and `shipped.py --environment <name> --post` comments `Deployed to <environment> in <tag>.` under a `<!-- shipmill:available: <environment> <tag> -->` marker, once per issue and environment (spec 021) (#393)
- The watch reads the requester's answer to a pre-release notice: REQUESTER_CONFIRMED when the issue's author reacted 👍 to it, and REQUESTER_REPORT when they commented after it or reacted 👎, for a session to hand to triage as a possible regression; anyone else's reaction gives no row, an issue a bot opened has no requester, and neither row is an action or labels, holds, or reopens anything (spec 021) (#394)
- `shipmill milestones` (`--json` for one object) prints spec 022's MILESTONE_WAITING and MILESTONE_OVERTAKEN rows, the overtaken one with its number, the version to rename it to, and the rename through `shipmill gh api`; github-ship-watch's `watch_state.py` runs it when a lane sets `milestone = true`, so `shipmill status --rows` and `--json` show both rows, MILESTONE_OVERTAKEN is an action (exit 1), and under "watch" a pass renames an overtaken milestone (#475)

### Changed

- Product intake reads the direction's Goals and Non-goals: each opportunity issue says `Serves: G-n` or `Serves no goal`, the accept question to the maintainer says the same, and an opportunity serving no goal is never proposed for acceptance on demand alone (#488)

## [0.54.0] - 2026-10-19

### Changed

- Docs: no stable release is described as a soaked rc. `docs/release-lanes.md` shows a stable lane that releases main's head after every green batch, the fix-forward, revert, hotfix, and rollback order for a bad batch, and a "Stable releases" section on the breaking hold, `promote_from = "rc"` with no age, and `min_soak_days`, deprecated in 0.53.0 and refused from the next minor, with `shipmill upgrade --apply stable-every-batch` as the migration; `README.md`, the site, shipmill-setup's lane table, and the triage rubric's "a breaking release waiting for the maintainer" row follow (#463)

### Fixed

- Plugin: the fix printed for a stale shipmill@shipmill install (the gate's `PLUGIN_STALE` tick, `doctor`, `status`, the setup checklist, and github-ship-watch's `SHIPMILL_OUTDATED`) runs `claude plugin marketplace update shipmill` before the update or reinstall, and the gate's daily update with `plugin_update = true` refreshes the marketplace once before updating its checkout's installs, reporting a failed refresh and still trying the update; `claude plugin update` alone left an install behind when Claude Code's copy of the marketplace predated the release (#477)

## [0.53.0] - 2026-10-18

### Added

- `shipmill status` reports MILESTONE_WAITING, with its reasons, while a lane with `milestone = true` has a milestone with no open issues whose specs aren't built or shipped, and MILESTONE_OVERTAKEN, with the rename to the version the lane cuts next, when a stable tag of an open milestone's version exists while the milestone has open issues; both are read with the release's own planner, which no milestone changes the bump of (spec 022) (#398)
- Skills: the agents work toward `docs/product.md` (spec 024, D-34). github-issue-triage's verdict on new behaviour names the goal it serves (`Serves: G-n`), gives won't fix for a non-goal and postpone for a feature serving no goal, still hands a user's request serving none to product intake, and leaves bug fixes alone; github-issue-resolve writes the pull request's `## Plan` (Serves, Files, Order, Proof) before the code and updates it before a push that departs from it; the reviewer brief carries the `REVIEW.md` rubric, the direction's Goals, Non-goals, and Quality bar, and the plan, with nits capped; github-pr-triage never merges an edit to the direction on its own judgment; shipmill-setup asks the maintainer for the direction when it connects `[agents]`, never inventing a goal. A repo without `docs/product.md` triages, plans, and reviews as before (#408)
- Delivery hooks: after an edit of `docs/product.md`, a file under `docs/product/`, or a `REVIEW.md`, the PostToolUse hook runs `shipmill product check` or `shipmill review check` and shows a failed check's output to the model (#445)
- Hooks: `shipmill doctor`, for a repo with `[agents]`, prints a line per delivery-hook rule, on or off and why, and self-tests the hook of the plugin install a session would load on a refused `gh pr merge 1 --rebase`, failing with the fix when it doesn't refuse, the install has no `hooks/hooks.json`, `uv` isn't on PATH, or a settings file sets `disableAllHooks`; it warns when it can't read what a session loads (the plugin listing, a settings file) and when `origin/HEAD` is unset. A headless gate runs the same self-test before a launch and, when it fails, starts no session and reads `HOOKS_FAILED`; an interactive gate reports it and starts the session (#446)
- A breaking stable candidate gets its `Ready to release` issue, with the breaking entries listed first, even in a run that releases rc or dev, and only a person's hand start releases it: `shipmill plan --actor` (from `$GITHUB_TRIGGERING_ACTOR`) skips stable for a `[bot]` login or a run naming no actor, and land closes the issue once the release is tagged (#462)

### Fixed

- Hooks: when uv is missing, can't find or install a Python 3.11 or newer, or `hooks/delivery.py` is missing, the hook prints one line naming `shipmill doctor` and exits 1, so the command runs unchecked instead of every shell command being refused (#458)

### Changed

- A trigger never releases a breaking change on stable: when quiet time, a window, or a milestone makes the stable lane due and its pending entries (at the rc's base, for a promotion) sit under a `major` heading, `shipmill plan` proposes it with the cause "a breaking change waits for the maintainer's decision" under `act` too; starting the stable lane by hand still releases it (#459)
- `shipmill init` writes a stable lane that releases after every batch of merges (`quiet_minutes = 30`), with no `promote_from`, `min_soak_days`, `schedule`, or `milestone`, and the rc lane only as comments, so the `release.yml` it derives has no schedule; `shipmill upgrade --apply stable-every-batch` takes `min_soak_days` out of `[lanes.stable]`, keeps `promote_from`, and adds `quiet_minutes = 30` only to a table with no trigger, every other byte left as it was (#461)

### Deprecated

- `[lanes.stable] min_soak_days`: still honoured for this minor release, with a `shipmill doctor` WARN naming spec 029 and `shipmill upgrade --apply stable-every-batch`; the next minor release refuses it. `shipmill doctor` also warns about a prepare or land job lacking `issues: write` for a config whose stable lane can hold a breaking change (`[bump] major`), in the one warning per job it already gives (#460)

## [0.52.0] - 2026-10-18

### Added

- Evals: `shipmill evals check [--repo DIR]` validates the agents' eval suite, `evals/`, without a model, exiting 1 with one line per case naming the rule it breaks (an unlisted case or a listed one with no directory, a skill not under `skills/`, tags not naming it, a malformed source, an unknown kind, a commit that does not resolve, no deterministic grader outside a finding case, `max_turns` above 40 or `timeout_seconds` above 900); a repository with no case under `evals/` passes, and CI runs it on every pull request (#437)
- Evals: eval cases run offline with no token: `evals/bin/gh` answers reads from a case's recorded fixture, logs every read, write, and miss to `.eval/gh.jsonl` without contacting GitHub, and records reads with `EVAL_GH_RECORD=1`; `evals/scaffold.sh` sets a case's workspace at its commit with its fixture at `.eval/`, and the shared `no-miss` grader fails a run that read anything unrecorded (#438)
- The policy reads an optional `[hooks]` section in `.github/shipmill.toml`: `default_branch` (true or false, default true) and `private` (a list of globs, default none), refusing any other key or a wrong type with exit 2 naming the key (#440)
- Plugin hooks: in a repo whose `.github/shipmill.toml` has `[agents]`, a PreToolUse hook refuses a plain `gh` write while `app_id` is set, a rebase merge, and a force push without a lease pinned to a commit, each with the command to run instead (#441)

### Changed

- Every skill's "Improve the skill" section says a lesson comes with a case under `evals/` that fails without it, in the same pull request; the postmortem template gains an `## Eval case` section; and github-pr-triage never counts a red `evals` check as unrelated: it blocks the merge unless the maintainer accepts that run (#439)

## [0.51.0] - 2026-10-18

### Added

- The notices on fixed issues name their stage: a dev or rc tag posts `Released in <tag> (pre-release).` with the pin command and that a plain install gets it with the next stable release, a stable promotion of an rc tells every issue the rc fixed, and each notice starts with a `<!-- shipmill:available: <stage> <tag> -->` marker so a rerun posts nothing; a new optional `[notices]` section in `.github/shipmill.toml` sets the `pin` and `install` commands, with `{version}`, `{tag}`, and `{name}` (spec 021) (#392)
- `specs.py split NNN --milestone <title>` puts every proposed build issue in the feature issue's milestone, as a `milestone:` line and a `milestone` key in `--json`, and the spec gate files each with `gh issue create --milestone` (#399)
- `triage_state.py` reports OFF_MILESTONE, an action, for an open build issue whose feature issue (its sub-issue parent in the repo) is in a milestone the build issue isn't in, so a goal's milestone holds every build issue the release lane reads (spec 022) (#400)
- `shipmill product add|edit|retire` and `shipmill review add-rule|protect|set-cap|retire`
  (`--dir DIR` for a subdirectory's `REVIEW.md`) edit one structured line of
  `docs/product.md` or a `REVIEW.md` and print it: an added id is one above any the file's
  git history held, a missing section is written in its fixed place, a moved section's file
  is edited, every other line stays byte for byte, and a file its check refuses exits 2
  without a write (#404)
- `shipmill doctor` fails a repo whose config has `[agents]` and no `docs/product.md`, or one
  `shipmill product check` refuses, naming the fix; a repo without `[agents]` gets no direction
  line (#405)
- `specs.py check` refuses a spec that isn't built without a `serves:` line naming the goals of `docs/product.md` it serves (or `quality bar`), or naming a goal the direction doesn't list, sections moved to `docs/product/` included; a repo without a direction is checked as before (#406)
- PR triage: `pr_gate.py` reads the direction and `REVIEW.md` from the default branch (spec 024). It refuses an agent's pull request (authored by `--bot-login`, or any named with `--agent`) whose body has no `## Plan` with `Serves:`, `Files:`, `Order:`, and `Proof:`, or whose `Serves:` names a goal `docs/product.md` doesn't list (exit 6, REFUSED); a repo without `docs/product.md` and a person's pull request skip the check. A pull request whose files match a `REVIEW.md` Protected areas glob, or that edits `docs/product.md` or `docs/product/`, waits on the maintainer (exit 5, NEEDS_DECISION) until `--maintainer-accepted`. It reads them at the checkout's `origin/HEAD`, or at `origin/<base branch>` when that isn't set; outside a checkout, or when the default branch holds neither file, it gates exactly as before (#407)

### Changed

- `milestone = true` makes a lane due only once the milestone's goal is built: every spec whose Issues section names one of its issues, or whose file one of its issues links, says `status: built` at main's head, and each of their build issues closed by a merged pull request in the candidate's base (the rc's base, for a promotion), closed as not planned, or confirmed by a trusted close-confirmed comment; the plan names what holds it, and a milestone no spec belongs to is due as before (spec 022) (#397)
- `shipmill gate` starts no session while the `shipmill@shipmill` install a session in its
  checkout would load is older than the latest release (D-35, superseding D-23's "the
  session still starts"). It reads that install at any scope, user scope included, as
  Claude Code picks it (the most specific scope installed for the checkout's project: local,
  project, user, then managed; a linked worktree's project is its main checkout), after the
  daily `plugin_update` when that is on. The tick reads `PLUGIN_STALE: ...` with the
  install's version and scope, the latest release, and the command that updates it, stops
  and starts no session, and the next tick with a current install launches; a failed read
  is printed and the session starts. `gate --json` adds `loaded`. `shipmill status` shows a
  paused gate as waiting on you with that command, and github-ship-watch's
  `SHIPMILL_VERSION` (so `status`, `doctor`, and the setup checklist) names the install a
  session loads, warning when it is behind (#417)

### Fixed

- `triage_state.py` links a PR to an issue by a closing keyword only in the PR's title outside backticks or at the start of a body line outside a code fence, the rule `shipped.py` reads, so a PR that quotes "Closes #N" mid-line no longer reads as the issue's fix or makes DONE_NOT_CLOSED close it (#416)

## [0.50.0] - 2026-10-18

### Fixed

- Shipped notices: a PR's closing keyword counts only at the start of a body line, in its title, or as GitHub's closing link, never quoted mid-line or in backticks, and a number with no issue behind it is skipped with a note instead of stopping the watch and the gate with exit 2 (#368)
- github-issue-triage: post the close-confirmed comment once the issue is closed, never with `gh issue close --comment`, which posts it before the close so it never counts (D-29); specs 005 and 014 note D-30's trusted upgrade issues (#369)

### Deprecated

- Config: `[roadmap]` is deprecated (D-32). A config with it still loads and the policy validates it, but nothing reads it, and `doctor` warns that the work-in-progress limit is now `[agents] wip`; the next minor release refuses `[roadmap]` (#377)

### Added

- Config: `[agents] wip = N` (1..100) is the work-in-progress limit github-issue-triage reads (`triage_state.py --wip N`): at most N issues in progress at once; without it there is no limit (D-32) (#377)
- `shipmill product check|show|ids` reads the product's direction, `docs/product.md` (spec 024): check exits 1 naming the file, line, and rule each broken heading, item, id, or moved section breaks; show prints it, or only `--section` sections, as Markdown or `--json`; ids lists every id with its text, moved sections in `docs/product/` resolved (#402)
- `shipmill review check` exits 1 naming the file, line, and rule when a `REVIEW.md`'s Important, Nits, or Protected areas section breaks its format, at the root or in a subdirectory, and passes free sections and a repo without one; `shipmill review show [--path FILE ...] [--json]` prints the rubric for the changed files, the root's and their directories' merged, each item with its file and the smallest cap (#403)

### Removed

- Product intake: the roadmap plan is gone (D-32). The skill no longer proposes, ranks, or creates milestones; `roadmap_state.py` and the milestone-proposal template are removed, and a milestone is the maintainer's own list of what a version must hold. Grouping requests into opportunities stays (#377)

## [0.49.0] - 2026-10-17

### Changed

- github-pr-triage lands a pull request with a squash merge, and the base of a stack with a merge commit, instead of matching the repo's history; it never rebase-merges (D-33) (#378)

## [0.48.0] - 2026-10-10

### Changed

- A headless gate now asks the config-upgrade question: with `--trusted-only`, `triage_state.py` trusts an issue the release workflow opened as the Bot `github-actions[bot]` when it carries both the `shipmill-upgrade` label and the `<!-- shipmill-upgrade: <id> <version> -->` marker as its first line, so `watch_state.py` reports it as UPGRADE_PENDING instead of UNTRUSTED; any other `github-actions[bot]` issue stays UNTRUSTED (D-30) (#314)
- shipmill.dev: the tab icon is the gear mark from the page and its preview image, and the preview's source, `site/og.html`, sits next to `og.png` to redraw it (#361)

### Added

- Triage: a right close can end SUSPECT_CLOSE. `triage_state.py` reads each recently closed issue's last 5 comments (paging back to the close only when all 5 came after it) and drops the SUSPECT_CLOSE row when a comment after the last close has `<!-- shipmill:close-confirmed -->` as its first line and comes from an OWNER, MEMBER, or COLLABORATOR or the `--bot-login` App; an outsider's marker never counts, and a reopen and a new close re-arm it. The skill's step 7 and `references/comments.md` give the comment (#332)

### Fixed

- Triage: `triage_state.py` no longer reads SUSPECT_CLOSE for an issue closed by a commit that names it only mid-line when a same-repo merged pull request closes it, by GitHub's link or a closing keyword in its title or body; a commit with no such pull request, or one that only mentions the issue or never merged, still reads SUSPECT_CLOSE (#363)

## [0.47.0] - 2026-10-10

### Added

- Triage: an issue labelled `human` is a person's item, triaged from the start and never dispatched; with every hold closed it reads HANDOFF_DUE until a trusted `<!-- shipmill:handoff -->` comment, WITH_PERSON until an assignee or trusted author replies `done`, then VERIFY_DUE, and NO_ASSIGNEE with no assignee; one closed as completed by a person with a `## Check` section reads VERIFY_CLOSED (never SUSPECT_CLOSE) until a trusted `<!-- shipmill:verified -->` comment, and `--wip` never counts a person's item (#342)
- Triage: `chains.py show <owner/repo#N>` prints the chain an issue belongs to, every issue it waits on and every issue that waits on it (natively or as its parent), recursively and each once across repos, with its executor (`agent`, or `person: @login` for a `human` item) and its state (CLOSED, BLOCKED with the open holds, READY); a READY item in a repo whose `.github/shipmill.toml` has no `[agents]` table reads NO_GATE and the command exits 1. With `--trusted-only` it never reads or follows an untrusted author's issue, and on a forge without issue relations it walks the `Depends on` lines alone. github-ship-watch reports each such item in a chain of the repo's open issues as a `CHAIN_NO_GATE` row, and a walk that fails as one `CHAIN_UNREADABLE` row, both actions for a person (#343)
- Watch and setup: github-ship-watch lists a person's item waiting on its assignees in ISSUES_OPEN as `WITH_PERSON #N (@login ...)` (triage_state.py's `--json` line for WITH_PERSON now carries an `assignees` list), and shipmill-setup's `setup_state.py` wants the `human` label wherever it wants `needs-decision` and `--fix` creates both (#344)
- Triage: the skill documents chains of work, in a Chains section and its references: the two link forms (`Depends on` lines and GitHub's blocked-by and sub-issue relations) and `chains.py link`, a person's item (the `human` label, each of its states, and what a session does for it, from the hand-off comment to checking the done report against its `## Check`, with the needs-decision question when the check can't run), a parent's close, and `chains.py show`; the spec gate links build issues with `chains.py link`, and `docs/flow.md` walks a chain across three repos with a person's step in it (#345)
- shipmill.dev: a link preview image (`og.png`, 1200×630) with `og:image` and `twitter:card`, so a shared link shows the page's headline and conveyor instead of text only (#351)

### Fixed

- `chains.py show --trusted-only`, the watch's chain walk, judges an issue's author by the repo the walk started from (D-16), not by the issue's own repo, where an outsider owns their own: an issue in another repo is followed only when its author is the starting repo's owner or collaborator (one `gh api repos/<repo>/collaborators/<login>` per login, cached) or the `--bot-login`, so an outsider's issue linked to a public one no longer makes every watch tick report CHAIN_UNREADABLE (#355)
- `shipmill status` knows spec 017's person's-item states: HANDOFF_DUE, VERIFY_DUE, and NO_ASSIGNEE are listed to triage, WITH_PERSON is parked with the logins it waits on (`(@login ...)`), and VERIFY_CLOSED is a closed item to check on its own `verify close` line, no longer counted among the open issues; CHAIN_NO_GATE and CHAIN_UNREADABLE wait on you on a `chain` line with their fix instead of under "other" (#358)

## [0.46.0] - 2026-10-10

### Added

- `docs/design/product-layer.md` maps the product layer (feedback, opportunities, specs, build items, decisions, milestones, releases), who moves each object, and the gaps ranked, starting with #334, #336, #337 and #338
- Triage: a GitHub issue dependency (blocked by) or a sub-issue holds a triaged issue as a "Depends on" line does, in any repo, listed once with its text holds and marked `(native)` or `(child)`; a parent's note starts with `children K/N closed`, and a forge that can't read the relations falls back to the text holds with one note (#340)
- Triage: `chains.py link <owner/repo#N> --blocked-by <owner/repo#M>` and `--child <owner/repo#C>` write a dependency both as GitHub's native relation (blocked by, or sub-issue) and as a `Depends on` line in the issue's body, adding only the half that is missing; when the forge refuses the relation it writes the line alone and says `text only:` (#341)

### Changed

- shipmill.dev: a new landing page with the run of #312 to 0.41.2 as its proof, the seven stages, per-stage control, release lanes, and a contact address, `hello@shipmill.dev` (#346)

## [0.45.0] - 2026-10-09

### Changed

- `shipmill init` derives `release.yml`'s schedule from the policy (spec 015): the hourly tick
  only when a lane sets `milestone` or the stable lane promotes with `quiet_minutes`, one cron
  per UTC window time when the lanes are schedule-only, and no `schedule:` at all when every
  run starts from a push or by hand, so a private repo stops paying for idle hourly runs. The
  starting policy still gets the hourly tick. `shipmill init --caller` rewrites only
  `release.yml` from the existing policy (with `--ci` and `--runs-on`), and `shipmill doctor`
  warns on a `schedule` check naming each cron the policy needs that `release.yml` lacks (#324)

### Added

- Self-hosted runner docs: `docs/release-lanes.md` gains "Self-hosted runners" (the `runs-on` input, `init --runs-on`, what the runner needs, and the settle wait holding it) and "The schedule in `release.yml`"; shipmill-setup asks for the runner on a private repo, warns when a self-hosted runner also runs deploys, and rewrites `release.yml` with `init --caller --force` after editing the policy; `setup_state.py` warns with `RUNNER_SHARED` when a deploy or dispatch workflow runs on shipmill's runner labels while a lane sets `quiet_minutes` (#325)

### Fixed

- With `[agents] app_id` set, a gate session's prompt names the App's `<slug>[bot]` login and
  tells the session to pass `--bot-login '<slug>[bot]'` to `triage_state.py` and
  `watch_state.py`, and github-issue-triage's steps 1 and 7 say so too, so a session's own
  reads no longer show an App question the maintainer answered as NEEDS_DECISION, or, with
  `--trusted-only`, an issue the App opened as UNTRUSTED; a repo without an App gets the same
  prompt as before (#329)

## [0.44.0] - 2026-10-09

### Fixed

- A stable promotion skips when `.github/workflows/` changed since the rc it would promote, since the release's CI runs main's workflows on the rc's code, and the same run cuts the next rc instead, which carries the new CI and soaks before it is promoted (#317)

### Added

- The reusable `prepare.yml` and `land.yml` take a `runs-on` input, a runner label or a JSON
  list of labels, that every one of their jobs runs on; it defaults to `ubuntu-latest`, so a
  caller that passes nothing runs as before. `shipmill init --runs-on <runner>` writes it
  into `release.yml`'s `prepare` and `land` jobs, a label bare and a list as compact JSON in
  single quotes, and exits 2 naming the value for one that isn't a runner label or a
  non-empty JSON list of labels, writing no file; without the flag `release.yml` is the one
  `init` wrote before (spec 015) (#323)

## [0.43.0] - 2026-10-09

### Fixed

- `shipmill status --rows` and `--json`, and the summary after a failed App check, read with the App's `--bot-login` when the config sets `[agents] app_id` and its key is on this host, so an App question the maintainer answered no longer reads NEEDS_DECISION (#311)
- `shipmill settle-minutes` prints 0 when the policy's mode is `off`, so the settle job no longer sleeps billed runner minutes after every push for a run that then skips; the release lanes reference adds the cost on private repositories, and shipmill-setup reads the repo's visibility and, on a private repo, offers the cheaper setups with rough monthly figures before choosing lanes (#318)

### Changed

- shipmill's site is at `https://shipmill.dev/`, and its health URL is
  `https://shipmill.dev/health.json`; the old `shipmill.github.io/shipmill` addresses
  redirect there. The package homepage and the plugin's homepage point at it (#315)

## [0.42.0] - 2026-10-09

### Added

- Config upgrades are asked about and carried out: `watch_state.py` reports an open `shipmill-upgrade` issue as `UPGRADE_PENDING` (or in NEEDS_DECISION while its question waits), github-ship-watch asks the maintainer through the needs-decision protocol under `[autonomy] upgrade = "propose"` and opens the upgrade pull request as the App on `shipmill/upgrade-<id>`, github-pr-triage merges it only on an accepting answer from an owner, member, or collaborator or under `act`, and `shipmill upgrade --propose` takes the `shipmill-upgrade-later` ("not now") label off only once a newer shipmill release changes the upgrade (#281)

### Fixed

- An answered needs-decision issue reads DECIDED in `triage_state.py`, an action the gate starts a session for on the next tick instead of after its retry window, and a hold word in one sentence of a comment line no longer holds the issue on a link another sentence names (#309)

## [0.41.2] - 2026-10-09

### Fixed

- A headless gate session no longer stops on a chained Bash call whose commands are all on
  the allowlist (`cd <dir> && git push`): the skills and the implementer and reviewer briefs
  run one allowlisted command per Bash call (`git -C <dir>`, no `;` or `&&` chains or pipes
  into unlisted tools) and rerun a denied chain as separate calls; a command that isn't on
  the list is still a needs-decision (#312)

## [0.41.1] - 2026-10-08

### Fixed

- github-pr-triage no longer tells a reviewer to reword an Unreleased entry after a rebase in
  a repo with changelog fragments, which `changelog_guard.py check` fails: stale wording is
  fixed in the fragment that holds the entry, and an entry still under Unreleased stays or
  moves into a fragment in the same PR (#304)
- `shipmill upgrade --apply changelog-fragments` writes `changelog.d/README.md` with an
  example in the config's `[changelog] style`, as `shipmill init` does, instead of always
  the keep-a-changelog one; it refuses a style it doesn't know, and still leaves an existing
  `README.md` alone (#305)

## [0.41.0] - 2026-10-08

### Changed

- `shipmill gate --json`'s `plugin` changes shape: it was `installed`, `latest`, `updated`,
  and `error`, and is now `latest`, `installs` (each `scope`, `installed`, `updated`), and
  `error`, one entry per install keyed on the gate's checkout (#240)

### Fixed

- The package metadata names its author as Roman Medvedev instead of the handle Romamo
- The LICENSE names the copyright holder as Roman Medvedev instead of the handle Romamo
- With `[agents] plugin_update = true`, the gate now updates every shipmill plugin install
  keyed on its checkout, at local scope as well as project scope, so a gate whose checkout
  has a local install (shipmill's own) no longer stays on an old release (D-23). After the
  update it reads the installs again and reports a failure, not an update, when an install
  stayed behind or an install in another folder changed; the session still starts (#240)

### Added

- `shipmill upgrade --propose` opens one issue labelled `shipmill-upgrade` per pending
  config upgrade, with `<!-- shipmill-upgrade: <id> <version> -->` on its first line, and
  updates it in place on later runs; under `[autonomy] upgrade = "observe"` it opens none.
  An upgrade whose issue was closed while the config lacks its key is declined: never
  proposed again, and no longer listed by `shipmill upgrade`, which now reads the
  `shipmill-upgrade` issues when one is pending. A config that sets the key closes its open
  issue as completed. The reusable `land.yml` runs it in its own `upgrade` job after a
  release lands, with the `issues: write` the caller's land job already grants, so no
  caller workflow changes, and a failure there names the upgrade and fails that job only,
  never the release; a dry run proposes nothing. `shipmill doctor` lists each pending
  upgrade with its fix, never failing on one, and warns about a land job without `issues:
  write` only when `upgrade` is propose or act and an upgrade is pending (D-9); `shipmill
  status` lists each pending upgrade with its
  issue's link or the `--apply` command as its fix (spec 014) (#280)
- Changelog fragments are on by default: `shipmill init` sets `[changelog] fragments =
  "changelog.d"` and writes `changelog.d/README.md`, and `shipmill init --no-fragments`
  writes neither; in a repo with fragments, `changelog_guard.py check` fails a pull request
  that adds a line under Unreleased, naming the fragment to write, or a fragment that
  doesn't read; the skills add a fragment instead of editing `CHANGELOG.md`, and shipmill's
  own pull requests do too (spec 013) (#274)

## [0.40.0] - 2026-10-08

### Changed

- Decision D-27: with `[changelog] fragments` set, a revision whose tree has no fragments
  folder and whose own config doesn't set the key has no fragments; spec 013 gets
  S-013-17 for it (#291)

### Fixed

- A repo that turns on `[changelog] fragments` mid-cycle can plan and release the stable
  promotion of an rc cut before the folder existed, and run `shipmill notes` and proposals
  against an older tag or base: a revision whose tree has no fragments folder, and whose
  own `.github/shipmill.toml` doesn't set the key, reads as no fragments, and the stable
  stamp applies that to the base it releases; HEAD when planning, and a revision whose
  config sets the key, still exit 2 naming the folder. Only `[changelog] fragments` is
  read from that revision's config, so an older config's retired keys don't block it;
  malformed TOML or a `fragments` that isn't a string fails (D-27) (#291)

## [0.39.0] - 2026-10-08

### Changed

- Decision D-26: when a stable release folds its rc sections, prose before an rc
  section's first `### ` heading is dropped, and any other text outside an entry still
  fails the fold (#283)

### Fixed

- A stable promotion folds rc sections that open with prose, such as "The 34th 1.0 release
  candidate: 2 breaking changes, ...": the prose before an rc section's first `### `
  heading is dropped, in both styles, so `shipmill plan` and `prepare` no longer fail with
  `text outside a '- ' entry` (D-26); any other text outside an entry, or a list item
  before the first heading, still fails the fold (#283)
- `shipmill plan` no longer stops at a stable lane that can't work out its candidate,
  such as an rc section it can't fold: it goes on to rc and dev, names the stable lane's
  error in the reason when one of them releases or proposes, and exits 2 with that error
  only when none does; `--lane stable` fails as before. An rc, dev, or hotfix `prepare`
  never reads the fold (#296)

## [0.38.0] - 2026-10-08

### Added

- Changelog fragments on the hotfix lane (spec 013): a hotfix's section holds the
  Unreleased entries and the fragment entries its merges added (each merge's added or
  modified fragments against those it deleted or modified, by `git diff` with its first
  parent, so a renamed fragment adds nothing), and the merges' fragment files stay off
  the release branch, as `CHANGELOG.md` does; a merge that adds neither still fails. `shipmill sync`,
  after a hotfix or a stable release cut off a moved main, deletes on main each fragment
  whose every entry the section holds, and exits 2 naming the entry when the section
  holds one that is in neither Unreleased nor a fragment on main. Without `[changelog]
  fragments` nothing changes (#273)

### Changed

- Spec 011, a fix on every non-OK status row, is built: each of its 20 criteria is checked
  against main under its Verification section (#242)

### Fixed

- `shipped.py --post` (its "Released in" notices) and `setup_state.py --fix` (its labels)
  write as the App through `uvx --from git+https://github.com/shipmill/shipmill@v0
  shipmill gh` when the checkout's `.github/shipmill.toml` sets `[agents] app_id`, as spec
  012 asks of every write, instead of as the person running them; without `app_id` they
  use plain `gh` as before. A `shipmill gh` exit 2 stops the script with nothing retried,
  and a config that can't be read, or an `app_id` outside a readable `[agents]` table,
  exits 2 before anything is written. The config is the checkout's, so a run from a
  subfolder still writes as the App. Reads stay on plain `gh` (#290)

## [0.37.0] - 2026-10-08

### Changed

- `shipmill gate`'s QUIET line names the pull requests it leaves for a person: with no
  work and pull requests in `PRS_OPEN` while `[agents] prs` isn't true, it reads `QUIET:
  nothing needs an agent; N pull request(s) wait to land, landing off ([agents] prs =
  false)`; with none waiting it reads as before. A row's `fix` from `watch_state.py --json`
  enters neither the gate's fingerprint nor its session prompt, so a new fix starts no
  session (#260)
- The six skills that write to GitHub run every `gh` call that writes as `shipmill gh`
  when the repo's config sets `[agents] app_id`, in every session, gated or started by
  hand, and stop on its exit 2 instead of retrying with plain `gh`; a decision a person
  gives in the session is posted with the first line `Decision by @<login>, relayed by
  <agent>`; `docs/install.md` and shipmill-setup document `shipmill gh`, the no-checkout
  token cache, and that the App's identity covers the sessions a person starts. Spec 012
  is built (#263)

### Added

- Changelog fragments, the core of spec 013: `[changelog] fragments = "<folder>"` in
  `.github/shipmill.toml` makes each `<folder>/<name>.md` pending alongside Unreleased.
  `shipmill plan` reads them at the planned revision through git and bumps by their
  headings; `propose`, `notes`, and a pre-release's GitHub release list them; a stable
  `prepare` writes Unreleased, then the fragments in file-name order, then the version's rc
  sections into one section and deletes the released fragments in the release commit,
  keeping `README.md`; dev and rc releases leave the folder alone. A missing folder or a
  malformed fragment exits 2 naming it, and `shipmill doctor` counts fragments and names
  one a released section already holds, with the `git rm` that removes it. Without the
  key nothing changes (#272)
- Spec 011: github-ship-watch's `watch_state.py` and `shipmill status` run a `gh` read that
  fails on an `HTTP 5xx`, a timeout, or a reset or refused connection once more after 5
  seconds; when it fails again, the error line ends `transient GitHub API error: rerun`. An
  auth, not-found, or any other failure still fails at once, and no write is ever rerun
  (#261)
- `shipmill upgrade` lists the config upgrades a repo hasn't decided (`--json` for
  scripts): `changelog-fragments` until `[changelog] fragments` is set to any value, and
  `plugin-update` for a config with an `[agents]` section and no `plugin_update` key.
  `shipmill upgrade --apply <id>` adds the upgrade's line at the end of its table, keeping
  every other byte of `.github/shipmill.toml`, creates the files it owns
  (`changelog.d/README.md`), and commits nothing; an unknown id, one that doesn't apply, or
  one already decided exits 2 naming it. `[autonomy] upgrade` takes observe, propose (the
  default), or act, and an open hold reads act as propose; doctor's autonomy row names it
  (spec 014) (#279)

### Fixed

- A failing `shipmill plan` no longer stops github-ship-watch's `watch_state.py`, so the
  gate reads a repo's issues and pull requests again: the failure is a new `BOT_PLAN_FAILED`
  row on the release workflow, with the planner's error line and the plan to run to see it, an
  action for a person (exit 1, not an agent's), read as no release due; `shipmill status`
  reads it as STUCK (#276)

## [0.36.0] - 2026-10-08

### Added

- Spec 014: config upgrades. shipmill proposes a feature that needs an opt-in in a repo's
  config (changelog fragments, `plugin_update`) as an issue, asks the maintainer through
  the needs-decision protocol, and opens the pull request once they accept;
  `[autonomy] upgrade` picks observe, propose, or act, and a declined upgrade is never
  proposed again (#277)
- Spec 013: changelog fragments. With `[changelog] fragments = "changelog.d"`, each pull
  request adds its entry as its own file instead of editing `CHANGELOG.md`, so PRs stop
  conflicting on it; a stable release writes the fragments into its section and deletes
  them, and `shipmill init` turns them on by default (#256)
- github-ship-watch's `watch_state.py` gives each row that needs a person or an agent a
  fix, the one line that clears it: `gh run rerun <id> --failed -R <repo>` for a failed
  bot, operate, or publish run, the lane to start for a stalled bot, the `git -C` commands
  for a stale worktree, the close command for a hold, the skill to run for issues,
  incidents, and untrusted items, and for open pull requests no gate lands, the
  `[agents] prs` setting. `--json` adds it as `fix` (a string or null) beside the
  unchanged keys, and the table prints it on an indented `fix:` line; a fix names its repo
  and checkout and never quotes an issue's or a pull request's title. `fleet.py` reads
  the new key (#258)
- `shipmill gh <args>` runs the `gh` on `PATH` with exactly those arguments, as the repo's
  App when `[agents] app_id` is set (a token limited to gh's `-R`/`--repo`, else origin's
  repo; any failure to get it exits 2 and never runs `gh`), else as the host's login with
  no empty `GH_TOKEN`; and `shipmill app-token` works outside a checkout, caching under
  `$XDG_CACHE_HOME/shipmill/<owner>/<repo>/` with mode 0600 (spec 012) (#262)
- `AGENT_AS_PERSON`: with `[agents] app_id` set, `shipmill status` prints a WARN row and
  `shipmill doctor` a WARN check when an issue, pull request, or issue comment of the last
  7 days carries an agent's marker but a person's login wrote it, naming the count, up to
  three URLs, and the fix (`shipmill gh`); one GraphQL search, and no request without an
  `app_id` (#264)

### Changed

- `shipmill status` shows the fix for every reason it is STUCK or WAITS ON YOU, on an
  indented `fix:` line after the line it clears: the gate's launchd job, the App, the CLI
  update for the form installed, and landing pull requests when no gate does. Its item lines
  say what acting on them needs: a pull request behind or in conflict with its base, the
  pull requests covering an issue in progress, what a parked issue waits on, how to ready a
  draft, and the `git -C <checkout> pull --ff-only` for a branch behind (`fetch origin
  <branch>:<branch>` when another branch is checked out) (#259)

## [0.35.0] - 2026-10-08

### Added

- Spec 011: every row and summary line of `shipmill status` that waits on you or is stuck
  ends with its fix, an exact command scoped to where it runs or the decision to make;
  `--json` carries it as a `fix` field, and a test fails on a row without one (#242)
- Spec 012: every agent session writes to GitHub as the repo's App, not only gated ones:
  `shipmill gh` runs `gh` with the App's token and never falls back to a person's login,
  `shipmill app-token` works with no checkout, and `status` and `doctor` flag agent text
  posted under a person's name (#250)

## [0.34.0] - 2026-10-08

### Changed

- Decision D-23, superseding D-22: with `[agents] plugin_update = true` the gate updates
  every install of the plugin keyed on its checkout, local scope as well as project
  (#240)
- Decision D-24, superseding D-12: a worktree whose tip is, or was before a force-push,
  the head of a merged pull request on its branch counts as landed, so the gate's prune
  removes it (#244)
- Decision D-25: a stable promotion folds its version's rc sections in the CHANGELOG into
  the stable section, and never skips as nothing pending while they hold entries (#243)

### Fixed

- A repo that moved to shipmill with `[X.Y.ZrcN]` sections in its CHANGELOG, written by
  an earlier release bot, could never promote X.Y.Z: the stable lane skipped with "nothing
  pending under Unreleased". A stable release now counts the rc sections of its version
  (newer than the last stable section) as pending together with Unreleased, writes the
  X.Y.Z section with all their entries merged under their headings (Unreleased first, then
  the rc sections newest first, each entry once), and removes the rc sections and their
  compare links; the GitHub release notes and a release proposal list the same entries.
  When a promotion still skips, the reason names the rc sections it found or says there
  were none. An rc section holding text that is not an entry (prose, a `####` heading, a
  numbered list) stops the release with an error naming it rather than lose that text. A
  CHANGELOG without rc sections releases as before (#243)
- `shipmill worktrees` and the gate's prune no longer keep a worktree forever as
  `<N> commit(s) not landed` when review force-pushed its pull request before a squash
  merge: a branch also landed when its tip is, or was before a force-push, the head of a
  pull request merged into the default branch from that branch or its upstream, matched by
  commit SHA; commits made
  after that head still keep it, counted alone. The merged pull requests come from one
  `gh api graphql` read per run, and a failed read exits 2 and removes nothing (#244)

## [0.33.2] - 2026-10-07

### Fixed

- A headless gate session no longer loses its background subagents 10 minutes after its
  last turn: the gate starts `claude -p` with `CLAUDE_CODE_PRINT_BG_WAIT_CEILING_MS=0` in
  its environment unless the gate's own environment sets the variable, and
  github-issue-triage and github-pr-triage run their agents in the foreground when
  headless (#246)
- The factory stalled when a gate session left the gate's own checkout
  (`tmp/shipmill-gate`) on a branch: every tick refused it and told you to create a
  worktree that already existed. A `--refresh` tick now detaches a clean linked worktree
  on a branch to the default branch's head, keeping the branch and its commits, and
  prints `detached <path> from <branch>` (`detached` in `gate --json`); a dry run moves
  nothing. `launchd` and a tick in the main working tree still refuse a checkout on a
  branch, now with `git -C <path> switch --detach origin/<default>` as the fix, and a
  checkout with tracked changes is refused with the files named. github-issue-resolve and
  github-pr-triage now tell a gate session to work in a new worktree and never switch
  branches or commit in the checkout it started in (#247)

## [0.33.1] - 2026-10-07

### Fixed

- Gate sessions could run a working copy of a skill instead of the released plugin: every
  prompt shipmill writes or recommends (its own `[agents] prompt`, shipmill-setup's, and
  the docs' prompts and `/loop` commands) named the skills without the plugin's prefix, so
  a link or copy in `~/.claude/skills` or `~/.agents/skills` answered them. They now call
  `/shipmill:<skill>`. github-ship-watch (and so `shipmill status`) and the setup checklist
  report each such link or copy of a shipmill skill as `SKILL_SHADOWED`, with its fix
  (remove it, or call the skill with the prefix); a link into the plugin's cache isn't
  one. It is an action for a person, never an agent's. The checklist also reads an
  `[agents] prompt` that calls a shipmill skill without the prefix as `AGENTS_UNPREFIXED`,
  and a home folder with neither as `SKILLS_OK` (#236)

## [0.33.0] - 2026-10-07

### Added

- `[agents] plugin_update` (default `false`: the gate changes no install). With `true`, a
  gate tick about to start a session checks at most once per 24 hours whether its
  checkout's own project install of `shipmill@shipmill` is behind the latest release and,
  when it is, runs `claude plugin update` in the checkout first; a failed update is printed
  on the tick (and in `gate --json`'s `plugin`) and the session starts anyway (D-22).
  shipmill's own gate sets it, and `shipmill init`'s template shows it with its default
  (#233)

### Changed

- Decision D-22: the gate updates its checkout's plugin at most once a day, and only when
  `[agents] plugin_update = true`; otherwise status, doctor, and setup report the behind
  install with a fix that works in its folder (#233)
- The docs and skills recommend installing the CLI from PyPI with `uv tool install
  shipmill` (upgraded with `uv tool upgrade shipmill`) and running a plain `shipmill
  <command>`, keeping `uvx --from git+https://github.com/shipmill/shipmill@v0 shipmill` for
  when it isn't installed and for headless gate sessions; each uvx call resolves git again,
  which took minutes and filled uv's cache. The hints the CLI prints name a plain `shipmill`
  when the `shipmill` on PATH is the running install, and the uvx form otherwise.
  `docs/install.md` gains a "Clean up old builds" section on `uv cache prune` and the plugin's
  old versions under `~/.claude/plugins/cache` (#236)

### Fixed

- `shipmill status` (github-ship-watch's `SHIPMILL_OUTDATED`) reports a stale plugin
  install in the gate's checkout (`tmp/shipmill-gate`) as its own row, and for the repo's
  own install prints a fix that works: an uninstall and install at that scope, since
  `claude plugin update` in the repo picks the nested gate install (a Claude Code bug).
  shipmill-setup's checklist reads the installs too and reports `PLUGIN_OUTDATED` (not
  done) for each one behind the release, instead of `PLUGIN_OK`, and `shipmill doctor`
  reports them with the same rows and fix text: a `plugin` WARN for each install behind
  the release, a PASS when none is, and a WARN, never a crash, when they can't be read (#233)

## [0.32.2] - 2026-10-07

### Fixed

- shipmill-setup no longer calls a stalled factory healthy: `setup_state.py` adds a
  landing row, `LANDING_OFF` (exit 1) when `[agents]` has `prs = false` (or no `prs` key)
  and open non-draft pull requests wait, listing them; setup then asks whether the gate
  should land them, and checks `shipmill status`, calling the setup healthy only when the
  verdict is IDLE or WORKING (#234)

## [0.32.1] - 2026-10-07

### Fixed

- `shipmill status` shows the open pull requests waiting to land: a `to land` line lists
  each with its link, a `landing` line says whether the gate lands them (`[agents] prs`),
  and when no gate does (`prs = false`, or no `[agents]`), the verdict is WAITS ON YOU,
  naming the pull requests and the fix, instead of IDLE while the gate logs QUIET (#231)

## [0.32.0] - 2026-10-07

### Changed

- The README now says what shipmill is, why to use it, and how to start, with a
  quickstart and links that work on PyPI; the release reference (lanes, policy,
  environments, operate, autonomy, versions, CLI, limits) moved to
  `docs/release-lanes.md`. The PyPI metadata gains keywords, classifiers, and homepage,
  documentation, and issue links, and the GitHub Pages site becomes a landing page

## [0.31.1] - 2026-10-07

### Fixed

- github-ship-watch no longer reads a version tag cut before the package's first PyPI upload
  as NOT_PUBLISHED, which started a gate session with nothing to repair: such a tag reads
  PREDATES_PUBLISH, a report-only row, while a later missing release stays NOT_PUBLISHED
  (#228)

## [0.31.0] - 2026-10-07

### Added

- `.github/workflows/publish.yml` builds the release tag it is given, checks that the tag is
  `vX.Y.Z` and matches `pyproject.toml`, runs `shipmill --help` from the wheel in a fresh
  environment and checks the wheel holds the skills' state scripts, then uploads with `uv
  publish` through trusted publishing in the `pypi` environment. The stable and hotfix lanes
  dispatch it, and `docs/install.md` says shipmill is on PyPI and needs Python 3.14 (#224)

### Changed

- shipmill's own gate runs headless: `[agents] mode = "headless"`, so each gated session
  is a detached `claude -p` that asks on GitHub and ends

### Fixed

- The CLI's own hints name the full `uvx --from git+https://github.com/shipmill/shipmill@v0
  shipmill` form instead of a bare `shipmill <command>`: the `next:` line after `init`,
  doctor's workflow and operate details, the launchd error off macOS, the status picture's
  launchd reason, `app-create`'s closing line, and the operate note in the config `init`
  writes. A test fails on a bare command in any string the package prints, raises, or
  writes (#223)

## [0.30.0] - 2026-10-07

### Added

- Spec 010: each stable and hotfix release publishes shipmill to PyPI through a new
  `publish.yml`, with trusted publishing and a smoke test of the built wheel (#216)

### Fixed

- The README, `docs/install.md`, and the github-ship-watch and github-pr-triage skills no
  longer tell you to run a bare `shipmill <command>`, which nothing puts on `PATH`: they
  use `$CR` or the full `uvx --from git+https://github.com/shipmill/shipmill@v0 shipmill`
  form. `docs/install.md` shows an alias for the short name that keeps tracking `@v0`,
  and says why `uv tool install` drifts; the github-ship-watch description, always in an
  agent's context, says how to run the CLI. A test fails on a bare command in the README,
  the top-level docs, or a skill (#215)

## [0.29.0] - 2026-10-07

### Changed

- Decision D-21: every gate session, interactive or headless, asks its questions through
  the needs-decision protocol, so a question nobody answers waits on GitHub instead of
  holding the gate (#206)
- Every `shipmill gate` session asks through the needs-decision protocol, interactive
  too: the interactive prompt ends with a `Gate session:` paragraph naming your `gh`
  login, so the session posts its question as a marked comment with the `needs-decision`
  label before it asks in the session, and an unattended question waits on GitHub instead
  of reading as work. An answer given in the session is posted on the item and the label
  comes off. An interactive launch now reads your login with `gh api user` and starts
  nothing when that fails. With `app_id` set, an interactive gate checks the App before it
  reads the state, as headless does, and reads it with `--bot-login <slug>[bot]`, so a
  reply on GitHub to the bot's question wakes the item. `setup_state.py` wants the
  `needs-decision` label whenever the config has an `[agents]` section (D-21) (#206)
- `shipmill status` prints a short linked summary instead of blocks: a heading with the
  repo, its link, and the verdict, with no list of reasons, since each reason is a line of
  its own; then the repo (in sync, at which version, release ok or the problem), every
  issue and pull request waiting on a decision or listed by state with its own link
  instead of a label search, the open issues and pull requests counted with the list's
  link, the gate as `OK, launchd every N min` or its problem, the mode, the GitHub App
  (`active`, `not active`, or the problem), and shipmill's version (`up to date` or the
  update commands); empty lines are dropped, and `--rows`, `--json`, and the exit code
  are unchanged (spec 009, #212)

### Fixed

- `specs.py` honours a dropped criterion, one whose text starts `dropped in #N`:
  `coverage` prints it as dropped instead of demanding a test, `split` leaves it out of
  new build issues, and `check` needs no Issues line for it, so a built spec that drops
  criteria can pass (#219)

## [0.28.0] - 2026-10-07

### Added

- `shipmill status` says whether the factory works or is stuck: a verdict (STUCK, WAITS ON
  YOU, WORKING, IDLE) with its reasons, then the local `main` against GitHub's and the
  version each is at, the open issues and pull requests (waiting on you with a GitHub link,
  to triage, to build), the gate's job, last run, last decision, mode and App, and one
  shipmill line with the CLI and plugin versions; `--rows` prints the old table (spec 009)

## [0.27.0] - 2026-10-07

### Changed

- A gate without a GitHub App is unfinished setup (D-19): shipmill-setup makes the App step
  required before it schedules the gate, `setup_state.py` reads `AGENTS_NO_APP` for any
  `[agents]` prompt without `app_id`, in either mode, and exits 1 on it (it was headless
  only and counted as done), and github-ship-watch's `watch_state.py`, and so `shipmill
  status`, reports a new `GATE_NO_APP` row, an action for a person that never starts a
  gate session. The gate and `launchd` still run without one (#204)
- shipmill-setup asks for the gate's `[agents] mode` every time, with the App question, and
  writes `mode = "interactive"` or `mode = "headless"` (D-20); `setup_state.py` reads a new
  `AGENTS_NO_MODE` row, exit 1, for a prompt with `app_id` and no `mode` key (after
  `AGENTS_NO_APP`, one row for the section). The config's default stays interactive, and
  shipmill's own config now says `mode = "interactive"` (#205)
- Decisions D-19 and D-20: a gate set up without an App, or without an explicit
  `[agents] mode`, is unfinished setup and reads as an action, never as done (#204, #205)

## [0.26.0] - 2026-10-06

### Added

- `shipmill status` prints github-ship-watch's report for the checkout's repo, as a table or
  with `--json` its JSON lines, and exits 1 when a row needs action, so a person without an
  agent or a CI job can ask "is anything stuck?" (spec 008)

### Changed

- `shipmill gate` reads a crashed `watch_state.py` (exit 1, no rows) as a failure with the end
  of its stderr, where it read it as QUIET
- Spec 008 after a second review: status needs a checkout even with a named repo, shows the
  script's whole stderr and passes it through on success, and the gate shares the guard
  that reads a crashed `watch_state.py` as a failure, not as QUIET
- Spec 008 settled after review: `status` exits 2, not 1, when `watch_state.py` crashes
  without printing a row; `watch_command` gains a `json` parameter for the table; the
  origin and the repo check reuse `_origin_repo` and `check_checkout`

## [0.25.0] - 2026-10-06

### Added

- Spec 008 for `shipmill status`, which prints github-ship-watch's report for the checkout's
  repo and exits 1 when something needs action
- github-ship-watch compares the host's `shipmill@shipmill` plugin (`claude plugin list`)
  with the latest shipmill release: SHIPMILL_VERSION lists the installs that apply to the repo (user scope, the
  checkout, and the gate's working directory) and a marketplace on an old repo name, and
  SHIPMILL_OUTDATED names an install behind the release with the command that updates it.
  The gate's checkout was found pinned at 0.14.0 while 0.24.0 was out (#196)
- github-ship-watch reports BRANCH_DELETE_OFF when the repo's `delete_branch_on_merge` is
  off, with the command that turns it on: merged branches piled up unnoticed after a repo
  move, since only setup checked it. An action for a person, never an agent's (#194)

### Fixed

- github-ship-watch's SHIPMILL_OUTDATED no longer reports a plugin install keyed on a linked
  git worktree, such as the gate's checkout: Claude Code loads the main checkout's install
  there, so the leftover entry was never used and its update command couldn't clear it (#198)

## [0.24.0] - 2026-10-06

### Added

- `[agents] mode = "headless"` for `shipmill gate` (D-17): a launch runs `claude -p` with
  `--permission-prompts none`, the `HEADLESS_TOOLS` allowlist, `--disallowedTools
  AskUserQuestion`, and a new `--session-id`, and its prompt ends with a paragraph that sends
  a decision for your `gh` login to the needs-decision protocol. The session runs detached,
  its output in `sessions/<uuid>.log` under the state directory, and the gate tracks it in
  `gate.json` by pid and process start time: RUNNING while it runs, never WAITING. The state
  read passes `--trusted-only` (D-16), and with `app_id` set `--bot-login <slug>[bot]`; a
  headless gate refuses `--claude-arg` flags that would bring prompts back or break the
  tracking. `mode` defaults to `"interactive"`, which launches exactly as before, and
  `shipmill launchd` now writes `AbandonProcessGroup` (run it once more for an installed
  job) (S-005-1, S-005-2, S-005-3, S-005-5, S-005-6, S-005-11, S-005-19, S-005-20, S-005-21)
  (#162)
- A headless `shipmill gate` without `app_id` notifies you of each item that waits on your
  needs-decision reply, since GitHub doesn't notify you of a comment under your own login:
  on a tick that reads the state, at once and then every `remind_hours`, recorded in
  `needs-decision.json` beside `waiting.json` and under its rules. With `app_id` the bot's
  mention notifies on GitHub and the gate sends nothing; a headless launch without it says
  so. `--json` gains `mode` and a `decisions` list (S-005-12, S-005-13, S-005-14,
  S-005-15) (#163)
- shipmill-setup's checklist knows headless mode: with `[agents] mode = "headless"` it wants
  the `needs-decision` label (`--fix` creates it, color `d876e3`), and without `app_id` the
  agents row reads `AGENTS_NO_APP`, counted as done, saying GitHub won't notify you of a
  question posted as your own login. Interactive and no-`[agents]` setups see no new row,
  and an `[agents]` `mode` no longer reads as the release mode. agent-modes.md, the
  shipmill-setup skill, and install.md document headless mode: `HEADLESS_TOOLS` and how to
  widen it (`--claude-arg=--allowedTools --claude-arg "Bash(npm *)"`), the trust filter, the
  label, and notifications with and without an App (S-005-16, S-005-18) (#164)

### Changed

- Spec 005's S-005-8 counts a `needs-decision` question only from a trusted author: an
  owner, member, or collaborator, or with `--bot-login` the bot's own marker comment. An
  outsider's marker comment can no longer re-park an answered item, and a maintainer's
  question after a bot's triage comment no longer reads as its reply. The code follows in
  #184

### Fixed

- `shipmill launchd` writes each `--claude-arg` into the job as `--claude-arg=<flag>`. It
  wrote `--claude-arg` and the flag as two arguments, which the job's gate refused ("expected
  one argument") on every tick, since a separate value that starts with a dash reads as an
  option. Run `shipmill launchd` once more for a job installed with `--claude-arg` (#192)
- A `needs-decision` question now counts only from a trusted author, in `triage_state.py`
  and the pull requests `watch_state.py` reads: a comment whose first line is the marker,
  by an owner, member, or collaborator, or with `--bot-login` by the bot. An outsider's
  marker comment no longer re-parks an answered item, a bot comment without the marker is
  no question, and with `--bot-login` a maintainer's marker question newer than the bot's
  leaves the item labelled with no question, so it waits instead of reading as answered
  (S-005-8) (#184)
- github-ship-watch no longer reports `WORK_BRANCH_STALE` for a work branch whose run is
  still alive behind ten or more newer runs: with a work branch on origin, it asks GitHub
  for the release workflow's unfinished runs by status (queued, in progress, waiting,
  pending, requested), as `prepare` does, instead of reading the newest ten, and a failed
  query stops the watch (exit 2) rather than reading as no owner. The row's re-check before
  deleting the branch asks by status the same way. A pass with no work branch makes no
  extra calls (#185)

## [0.23.0] - 2026-10-06

### Added

- The needs-decision protocol for headless sessions: a question for the user becomes a
  comment whose first line is `<!-- shipmill:needs-decision -->` and a `needs-decision`
  label, and the item waits on GitHub (`references/needs-decision.md`, linked from a headless
  rule in github-issue-triage, github-issue-resolve, and github-pr-triage).
  `triage_state.py` reads such an issue as NEEDS_DECISION, no action, until an OWNER,
  MEMBER, or COLLABORATOR replies, and gains `--bot-login` and `--trusted-only` (an outside
  author's issue reads UNTRUSTED). `watch_state.py` passes both through, leaves waiting
  issues and pull requests out of ISSUES and PRS_OPEN, and lists them in a NEEDS_DECISION
  row (an action, `agent: false`) and, with `--trusted-only`, outsiders' issues and fork pull
  requests in an UNTRUSTED row, so `shipmill gate` reads a repo whose only work waits as
  QUIET (S-005-7, S-005-8, S-005-9, S-005-10, S-005-17) (#161)
- D-18: a Release run that finds a work branch no active run owns deletes it and pushes its
  own, given `actions: read`; without it, the stop stays but is reported (#175)
- github-ship-watch reports what else is going on in the repo, and every status report lists
  it: the open issues triage owes nothing on yet, by state (ISSUES_OPEN); each queued or
  running workflow run (RUNS_ACTIVE); the gate's triage mode from `[agents]` (TRIAGE_MODE);
  the Claude Code sessions on the host working the repo (AGENT_SESSION); and the gate's
  launchd loop with its last decision (LOOP). All are report-only, so the exit code and the
  gate's fingerprint are unchanged (#182)

### Fixed

- A work branch left on origin by a Release run cancelled before its cleanup job got a
  runner no longer stalls the lane: the next run's `prepare` deletes it and pushes its own
  when no other queued or in-progress run of the Release workflow could own it (D-18). This
  takes `actions: read` on the caller's prepare job, which `shipmill init` now writes; the
  reusable prepare job takes the caller's grant instead of setting its own, so a caller
  without it still runs. Every stop at a held work branch is now visible: a warning
  annotation and a run-summary line naming the branch and its commit, saying to grant
  `actions: read` when that is the cause; the run stays green. github-ship-watch reports
  `WORK_BRANCH_STALE` for a `shipmill/v*` branch no active run owns, and deletes it and
  starts the lane (#175)

## [0.22.0] - 2026-10-06

### Changed

- `docs/design/agent-modes.md` records the #160 probe of a headless `claude -p` session on
  Claude Code 2.1.291: it outlives the launchd job that started it, a call outside the
  allowlist is denied with no prompt, AskUserQuestion is absent, and it exits on its own
  even when its last reply asks a question (S-005-4)

## [0.21.0] - 2026-10-06

### Changed

- github-issue-triage asks a design question on the issue too, as a **Decision needed**
  block at the top of its verdict comment: the question in one plain sentence, the options
  numbered with the recommended one first and what each means for users, and how to answer
  (reply with a number). A reply on the issue counts as the answer, so the maintainer
  doesn't have to attach to the gate session; a held PR's decisions are asked the same way
- Spec 005 now runs headless gate sessions as `claude -p` instead of `claude --bg`, after
  the #160 probe found a `--bg` session reads `blocked` whenever its last reply asks for
  something: the gate starts the session detached, logs its output under the state
  directory, tracks it by pid, and never reads it as waiting; `shipmill launchd` sets
  `AbandonProcessGroup` so a session outlives its tick (D-17)

## [0.20.0] - 2026-10-06

### Added

- `shipmill app-install [owner/name ...]` guides installing the gate's App on more repos:
  for each repo the App doesn't cover it opens the App's Install App page and says per
  account whether to click Install or Configure and which repos to pick, then waits until
  each is covered; it never installs or adds anything itself. `shipmill app-create`'s
  install step uses the same guide (#172)
- Spec 007 for `shipmill app-install`, which guides installing the gate's App on more repos
  and accounts, and checks that it took

### Changed

- shipmill's own gated sessions write as the `shipmill-romamo` GitHub App (`[agents] app_id`)
- `shipmill app-create` makes the App yours by default (your personal account), private
  unless a gated repo is in an org, then public so it installs there; an interactive run
  asks who should own it, your account first, and `--owner` picks an org you administer
  (#167)
- `shipmill app-create` names the App `shipmill-<owner>` by default (`shipmill-agent` under
  the `shipmill` account), falling back to `shipmill-<login>`, so each account's bot is told
  apart on its pull requests; when both are taken it exits 2 naming free alternatives

### Fixed

- `shipmill app-create` sets the App's homepage to `https://github.com/shipmill/shipmill`,
  not the first gated repo's URL

## [0.19.0] - 2026-10-06

### Added

- Spec 006 for `shipmill app-create`, which makes the gate's GitHub App in one click and
  picks its owner and visibility from where the gated repos are
- `shipmill app-create` makes the gate's GitHub App in one click: it finds the accounts your
  `gh` login administers and the repos in them holding `.github/shipmill.toml`, plans a
  private App when they are all in one account and a public one when they span several
  (`--owner`, `--public`, `--private`, `--name`, `--repos` change it; `--dry-run` prints the
  plan), opens GitHub's create page with the permissions filled in, saves the key to
  `~/.config/shipmill/app-<app_id>.pem` with mode `0600`, waits for the installations, and
  prints the `app_id` line to commit; exit 1 names a repo still missing the App. The setup
  skill and `docs/install.md` use it first, the manual steps as the fallback (#155)
- Spec 005 for headless gate sessions: `[agents] mode = "headless"` starts sessions that
  can't prompt, a decision for the user becomes a `needs-decision` comment and label the
  gate waits on, and headless work is limited to trusted authors' items, with D-16 (#134)
- Spec 005's build issues: #160 to #164 (#134)

### Fixed

- D-15's `Decided` line names the issue it was decided in (#147), so `specs.py check`
  accepts a spec that cites it
- `shipmill app-create` prints each line as it happens, so a piped or backgrounded run shows
  the plan and the URL at once; its local page no longer posts to GitHub by itself, which
  lost the manifest when GitHub asked to sign in first (*We didn't find an App Manifest*),
  but shows the plan and each permission with its use and a **Create on GitHub** button to
  click again after signing in; and a taken default name moves to a free variant, while a
  taken `--name` exits 2 naming the free ones (#157)

## [0.18.0] - 2026-10-06

### Added

- `shipmill gate` prunes on each tick as `shipmill worktrees --prune` does, held or not:
  after the waiting step and before the hold check, it removes each worktree that provably
  landed with the local branch it held, prints `pruned <path> (<branch>)` for each, and
  lists their paths under a new `pruned` key in `--json`. `--dry-run` removes nothing,
  prints `would prune <path> (<branch>)`, and lists them under `pruned`. A prune error
  (`claude agents --json` or `gh pr list` failing, or git refusing a removal) exits 2 and
  starts no session; the gate's own checkout is never a candidate (#124)
- Spec 004's build issues: #141 to #144 (#136)
- `[agents] app_id` names the GitHub App gated sessions write as, and `shipmill gate
  --app-key <path>` its private key (default `~/.config/shipmill/app-<app_id>.pem`). On a
  launch with `app_id` set, the gate checks the key's mode, signs the App's JWT with
  `openssl`, and checks the App is installed on the repo with every permission spec 004
  lists, exiting 2 naming what failed (D-14) (#141)
- github-ship-watch's `watch_state.py` reports a `WORKTREE_STALE` row, report-only
  (`agent: false`, never an action), for each worktree under `.claude/worktrees/` or
  `tmp/wt-*` that `shipmill worktrees` keeps and that is over 7 days old, naming its path
  and why it is kept. It runs `shipmill --repo <repo-dir> worktrees --json` for a shipmill
  bot, so the watch needs `claude` on `PATH` there, and a failing command exits 2 as a
  failing plan does. shipmill-setup's gate section documents the prune and `shipmill
  worktrees`, and github-issue-resolve, github-pr-triage, and github-issue-triage say that
  the worktrees a session leaves behind once it exits are the gate's prune's to remove.
  Spec 002 is built (#125)
- `shipmill app-token <owner/repo> --app-id <id> [--app-key <path>]` prints a GitHub App
  installation token limited to that one repository and spec 004's permissions. It caches
  the token in `$(git rev-parse --git-common-dir)/shipmill/app-token.json` (mode `0600`,
  replaced atomically), reuses it while it has at least 10 minutes left, and exits 2 on a
  malformed cache, naming it. `--git-credential get` answers git's credential protocol for
  `https://github.com` with `username=x-access-token`; another host gets no answer, and
  `store`, `erase`, and other operations print nothing. `python -m shipmill` now runs the
  CLI, and the session's `gh` and `git-credential-shipmill` helpers, which hold no token,
  can be written for the gate's launch (#142)
- With `[agents] app_id` set, `shipmill gate` starts its session as the App's bot. After
  the App's checks it reads the bot account's id, writes the `gh` and git credential
  helpers to `$(git rev-parse --git-common-dir)/shipmill/bin/`, and launches `claude --bg`
  with `--settings` env that puts that folder first on `PATH`, makes `<slug>[bot]` and
  `<id>+<slug>[bot]@users.noreply.github.com` the git author and committer, and, through
  `GIT_CONFIG_*`, replaces the host's github.com credential helpers with the App's and
  sends `git@github.com:` and `ssh://git@github.com/` remotes over https. The env holds no
  token, and the gate's own reads keep the host's `gh` login. Any failure exits 2 before a
  session is stopped or started. The decision line ends ` as <slug>[bot]`, `--json` gains
  `identity` (`null` without an App), and `--dry-run` runs the checks, writes nothing, and
  prints `would launch as <slug>[bot]`. With `app_id` unset the launch is unchanged.
  `shipmill launchd --app-key <path>` passes the key, made absolute, to the job's gate,
  and refuses it when `app_id` is unset or the key is missing or readable by others (#143)
- shipmill-setup's gate section and `docs/install.md` give the GitHub App's setup: creating
  it with no webhook and spec 004's permission table, installing it only on the repos the
  gate works on, the private key at `~/.config/shipmill/app-<app_id>.pem` with `chmod 600`
  (or `--app-key` on `gate` and `launchd`), `app_id` in `[agents]`, the token cache and
  helpers, the dry run that proves it, and that without `app_id` sessions launch as before.
  `docs/design/agent-modes.md` describes the session's identity, `--settings` env, and the
  `app-token.json` and `bin/` state, and github-ship-watch says the App's `<slug>[bot]`
  counts as a bot in the metrics. Spec 004 is built (#144)

### Changed

- `[agents] max_wait_hours` is now `max_wait_minutes` (0..10080) and defaults to 15, so
  `shipmill gate` stops a session that has waited on you for 15 minutes unless the config
  says otherwise (D-15, superseding D-13); 0 still never stops one. A config that still
  sets `max_wait_hours` is refused naming the key. Waits read in minutes under an hour
  (`stopped <id> after 15m waiting`), and `--json` reports `waited_minutes` in place of
  `waited_hours` (#147)

## [0.17.0] - 2026-10-06

### Added

- Spec 003 for notifying when a gated session waits on you, and stopping it after an
  optional `max_wait_hours`, with D-13: a hold doesn't keep the gate from stopping a stuck
  session (#119)
- Spec 003's build issues: #128 to #130 (#119)
- The `[agents]` section takes `notify` (default true), `remind_hours` (1..168, default 4),
  and `max_wait_hours` (0..168, default 0), refusing a bad value naming the key; the gate
  doesn't act on them yet (#128)
- `shipmill gate` sends a desktop notification when a session it started waits on you
  (`osascript` on macOS, `notify-send` elsewhere), and again every `remind_hours` while it
  waits; `notify = false` turns it off. The wait is kept in `waiting.json` next to
  `gate.json`, a failed send prints `notify failed for <id>: <error>` without changing the
  decision, notifying runs on held ticks too, `--dry-run` prints `would notify <id>`, and
  `--json` lists each blocked session under `waiting`. A tick with a blocked session now
  reads the `[agents]` section (#129)
- `shipmill gate` stops a session that has waited on you for `max_wait_hours` (when not 0)
  with `claude stop`, prints `stopped <id> after <N>h waiting: <name>`, sends a last
  notification, and decides the rest of the tick without it, held or not (D-13); a failed
  `claude stop` exits 2 and launches nothing, and `--dry-run` prints `would stop <id>`.
  Spec 003 is built (#130)
- `shipmill worktrees [--json]` lists every worktree of the repository as REMOVABLE, once
  its branch provably landed on the default branch (by ancestry, patch id, or a squash of
  its whole diff), or KEPT with the first check it fails: the main or current checkout, not
  under `.claude/worktrees/` or `tmp/wt-*`, missing, locked, detached, on the default
  branch, under a day old, a live Claude Code session in it, another worktree inside it,
  uncommitted changes, commits not landed, or an open pull request (#122)
- `shipmill worktrees --prune` removes each REMOVABLE worktree with `git worktree remove`
  (never `--force`) and then the local branch it held, printing those rows as REMOVED (also
  the `verdict` in `--json`); no other worktree or branch, local or remote, is touched.
  `--prune --dry-run` prints them as WOULD_REMOVE and removes nothing, and `--dry-run` alone
  exits 2. The first removal or branch deletion git refuses stops the prune with exit 2,
  naming the worktree and git's error and what it removed before (#123)
- Spec 004 for gated sessions writing as a GitHub App (`[agents] app_id`), with D-14:
  with an App set, a session starts as the App or not at all (#137)

## [0.16.0] - 2026-10-05

### Added

- shipmill-setup's `setup_state.py` reports whether GitHub deletes a pull request's branch
  when it merges: `BRANCH_DELETE_ON`, or `BRANCH_DELETE_OFF` (exit 1), which `--fix` turns
  on through the repo setting `delete_branch_on_merge`. github-pr-triage's stacked merges
  rely on it to retarget a stacked PR. github-issue-triage now deletes the branch of a PR
  it closes because the new plan dropped it (#117)
- Spec 002 for pruning landed worktrees, and D-12: whoever creates a worktree removes it,
  and `shipmill gate`'s prune owns what an exited session left (#116)
- Spec 002's build issues: #122 to #125 (#116)

### Changed

- shipmill's own `.github/shipmill.toml` has an `[agents]` section, so `shipmill gate` triages
  this repo's new issues and lands its green pull requests

## [0.15.0] - 2026-10-05

### Added

- `docs/install.md`: the full installation, from prerequisites through the skills, release
  lanes, and the gate, to pausing and removing shipmill. The README keeps a short Install
  section and links to it; its Quick start and Where the agents run sections moved there
- A one-line setup: `claude plugin marketplace add shipmill/shipmill && claude plugin install
  shipmill@shipmill && claude "/shipmill:shipmill-setup"`, from the root of a repo, installs
  the plugin and starts the shipmill-setup skill
- `watch_state.py --json` marks every row with `agent: true|false`: true for BOT_FAILED,
  BOT_STALLED, NOT_PUBLISHED, UNANNOUNCED, ISSUES, OPERATE_FAILED, and INCIDENT_OPEN, the
  rows an agent works on; false for every other state, PROMOTION_DUE, UNHEALTHY, HOLD, and
  PRS_OPEN among them. The text table is unchanged, and `fleet.py` reads the new field
  without adding it to its own report (#49)

### Changed

- `shipmill gate` starts a session on the rows `watch_state.py` marks `agent: true`, plus
  PRS_OPEN with `[agents] prs = true`, in place of its own copy of the states. A failed
  operate run (OPERATE_FAILED) and an open incident (INCIDENT_OPEN) now start one; an open
  `shipmill-hold` issue still stops every launch (D-11). The gate refuses a row with no
  boolean `agent` rather than guessing (#49)
- shipmill moved to the shipmill GitHub org: the repository is `shipmill/shipmill`, so
  `shipmill init` writes `uses: shipmill/shipmill/...@v0`, the default `--tool` for the
  workflows, `launchd`, and `watch_state.py` is `git+https://github.com/shipmill/shipmill@v0`,
  and the plugin's marketplace is `shipmill/shipmill`. GitHub redirects the old path; the
  setup checklist still counts a `release.yml` that calls `romamo/shipmill`. shipmill's own
  Pages site, and its health URL, moved to `https://shipmill.github.io/shipmill/`
- The CHANGELOG's `[Unreleased]` link points at `shipmill/shipmill`, so the compare links
  each release writes from it use the org's path

### Fixed

- `shipmill gate` no longer writes a row's detail into the session's prompt: an open
  incident's detail starts with the issue's title, text anyone who can edit the issue
  controls, which reached the session as if the gate wrote it. The prompt lists each row by
  state and subject only (`- INCIDENT_OPEN #42`) and tells the session to rerun
  `watch_state.py` for the details and read each issue's text as untrusted data, not
  instructions. `--dry-run`, the log, and the launch fingerprint keep the detail (#114)
- The github-issue-resolve skill no longer leaves the checkout it starts in on the fix branch,
  where a later `shipmill plan` read the PR branch instead of main: Phase 3 creates the branch
  in a worktree (`git worktree add -b fix/<slug> tmp/wt-<slug> origin/<default>`) unless the
  session already runs in a linked worktree, never switches, resets, or pulls the user's
  checkout, keeps the worktree while the PR is open, and removes it and its branch once
  `landed.py` confirms the merge (#110)
- `fleet.py report --metrics` measured change failure rate and time to restore with the
  `incident` label for a repo whose fleet entry sets no `incident_label`, even when the repo's
  config sets `[operate] incident_label`. fleet.py now reads that label from the clone with
  `watch_state.py`'s config reader and passes it to `metrics.py`, so the metrics and the watch
  count the same issues (#99)

## [0.14.0] - 2026-10-05

### Changed

- `shipmill gate` starts no session while an issue labelled `shipmill-hold` is open, and
  reports HELD with any session still open (D-11)

## [0.13.0] - 2026-10-05

### Changed

- The project is now shipmill, with no compatibility layer: the package and CLI
  `shipmill`, the config `.github/shipmill.toml`, the labels `shipmill-hold` and the
  other `shipmill-*` labels, the `shipmill/<tag>` work branches, the `shipmill-setup`
  skill, the plugin `shipmill@shipmill`, and the repository `romamo/shipmill`

### Removed

- macOS Finder's `.DS_Store` files, which the rename's commit picked up; `.gitignore` now
  lists them
- `.github/release-policy.toml`, the config's alias: shipmill reads only
  `.github/shipmill.toml`, and `init --force` no longer removes the alias

## [0.12.0] - 2026-10-05

### Added

- github-ship-watch reports a fleet (spec S-001): `fleet.py report --fleet <file>` runs
  `watch_state.py` for every repo the fleet file lists, each on a fresh blobless clone,
  and prints one table with the repo named on each row, the action rows of all repos
  first. It exits 1 when any repo has an action row; a repo whose check fails (not
  found, no access, a gh error) gets one REPO_ERROR row with the error's first line, the
  rest are still reported, and the run exits 2. `--metrics` adds each repo's
  `metrics.py` measures over one shared 30-day window, side by side with one column per
  repo, "no data" kept as no data. `--json` prints the report as one object, each repo
  with its rows (and its metrics with `--metrics`). The skill's new Fleet section
  documents the fleet file, the report, and a routine prompt that runs it. The fleet
  file is `[[repos]]` tables naming each repo as `owner/name`, with an optional
  `incident_label`, refused (exit 2, naming the file and the problem) when it is
  missing, isn't TOML, has no repos, has an entry without `repo` or with an unknown key,
  names a repo not in owner/name form, or lists a repo twice.
  `watch_state.py --incident-label` takes the place of the config's
  `[operate] incident_label`, so a fleet entry's label is the one its watch reads (#91)

## [0.11.0] - 2026-10-04

### Added

- A merged spec becomes a task graph: `specs.py split NNN` proposes its build issues,
  one per `--group` of criteria, each with a title, a body naming its `S-NNN-k`
  criteria, and `Depends on` lines (`--after B:A`) to fill in as the issues get numbers
  (`--json` for the same as one object). `specs.py check` reads the Issues section as
  `- owner/repo#N: S-NNN-1, S-NNN-2` and holds every criterion of an approved or built
  spec to exactly one build issue there. `triage_state.py` reads a `Depends on
  owner/repo#N` (or same-repo `#N`) line in an issue's body as a hold: BLOCKED while the
  dependency is open, UNBLOCKED once it closes, and UNFILLED (an action state) while a
  `#{Bk}` placeholder from `split` is left unfilled; `--wip N` reports the room left
  under a WIP limit. The triage skill files the build issues as sub-issues of the
  feature issue, dispatches them in dependency order within `[roadmap] wip` once the
  config has it (#70), stacks a
  dependent PR on its dependency's open one, and verifies the whole spec when the last
  build issue closes (#71)
- github-ship-watch learns from failures. `watch_state.py` reports POSTMORTEM_DUE (an
  action) for an issue labelled `[operate] incident_label` (default `incident`) closed as
  completed, not as not planned or a duplicate, that no `docs/postmortems/*.md` on the
  default branch names in an `Incident:` line (`owner/repo#N`, the issue's URL, or `#N`),
  read through the GitHub contents API. The skill drafts the postmortem from the
  incident's comments and deployment statuses as a pull request the maintainer merges,
  from the new `docs/postmortems/TEMPLATE.md` (timeline, cause, what caught it, what would
  have caught it sooner, actions); after the merge each rule becomes a `D-n` entry through
  `decisions.py` and each other action an issue. A weekly retro, run only when the user
  schedules it, compares this week's metrics with last week's, reads the refused and
  reworked PRs, recurring review findings, and stuck states, and posts a short comment on
  the roadmap issue with at most three proposals, each opened as an issue. The new
  `scripts/retro.py` gathers the retro (`gather`) and checks proposal titles against the
  open issues (`dedupe`), and `metrics.py --until` ends the window at a date or time, so
  the week before can be measured (#72)
- A `product-intake` skill groups product feedback (open issues triage left to it, open
  discussions when Discussions are on, and their thumbs-up reactions) into one
  `opportunity` issue per outcome, with the problem, who is affected, the evidence, and
  what success looks like. The maintainer accepts one with the `planned` label or declines
  it by closing it as not planned with the reason in a comment; a later request for a
  declined outcome is linked into that opportunity's Evidence, never proposed again, and an
  accepted one goes to github-issue-triage's spec gate as a feature. Its
  `scripts/intake_state.py` reports NEW_FEEDBACK, OPPORTUNITY_OPEN, ACCEPTED, HANDED_OFF,
  DECLINED, NO_REASON, DONE, MERGED, and OVERLAP; an issue labelled `bug`, `roadmap`, or
  one of shipmill's own labels isn't feedback, and `--skip-label` adds more. `[autonomy] intake` sets how far it
  goes: `propose` (the default) or `observe`; `act` is refused, and `doctor` prints it (#69)
- The `product-intake` skill plans the roadmap: milestones are the roadmap, and it
  proposes the next one from accepted opportunities, ranked by evidence (requests and
  thumbs-up) per load (the opportunity plus its spec's build issues), within a new
  `[roadmap]` config section: `wip`, the issues open at once across the open milestones
  (default 5), and `cadence`, the weeks between milestone due dates (default 2). The
  proposal is a `milestone-proposal` issue the maintainer approves by closing it with an
  "approve" comment. Its `scripts/roadmap_state.py` reports MILESTONE, OVERDUE, WIP_OVER,
  UNPLANNED, PROPOSAL_OPEN, APPROVED, UNREADABLE, and NEXT. `doctor` validates
  `[roadmap]` and prints it when present (#70)
- A deploy gets its first health check right after it succeeds, not at the next scheduled
  `shipmill operate` run up to 10 minutes later: the deploy workflow in the README and the
  shipmill-setup skill ends with an `operate` job that runs `gh workflow run operate.yml -f
  dry-run=false` with `actions: write`, and the 10-minute schedule stays the backstop.
  `doctor` notes when an environment's deploy workflow starts the operate caller, and warns
  when it doesn't for an environment with `from` or `health` (#84)

### Changed

- github-issue-triage sends a user's request for a new capability to product intake
  instead of the spec gate: the new **opportunity** verdict (`Triage: **opportunity**`,
  the marker intake uses) hands it over, `triage_state.py` reads it TRIAGED and
  `intake_state.py` reads it NEW_FEEDBACK until an opportunity groups it. A spec is
  written only for an accepted opportunity (label `planned`), a request one already
  covers (held on that opportunity), or an issue the maintainer filed; bugs, contract
  tweaks, and small additive features keep their verdicts. The rubric, the comment
  templates, the spec gate, github-issue-resolve, product-intake, and `docs/flow.md`
  say so, and tests hold both scripts to the new templates (#78)

### Fixed

- `changelog_guard.py move` no longer leaves an entry headless when a union kept the
  PR's `###` heading line above the other side's lines: an entry right under a release
  heading goes under the nearest `###` heading above it, joining that heading in
  Unreleased or creating it in Keep a Changelog order, and `move` refuses a bullet with
  no `###` heading anywhere above it instead of moving it as a block (#82)
- `triage_state.py` no longer reads an incident closed as completed by hand as
  SUSPECT_CLOSE: an incident closes once the environment is healthy again, and
  github-ship-watch's POSTMORTEM_DUE follows it up. The label is `incident` by default;
  the script can't read the shipmill config, so pass `[operate] incident_label` with the
  new `--incident-label` when it differs (#83)
- A deploy workflow started by hand without `--ref <tag>` recorded its deployment under the
  branch, which names no release tag, so `shipmill operate` couldn't tell what ran there.
  The deploy workflow in the README and the shipmill-setup skill now starts with a `ref`
  job that fails such a run, with the right `gh workflow run ... --ref <tag>` command, and
  `doctor` warns when an environment's deploy workflow has no step comparing `github.ref`
  with `refs/tags/<tag>` (#80)

## [0.10.1] - 2026-10-04

### Fixed

- Spec and metrics follow-ups: `specs.py check` and `coverage` report "no specs" and
  exit 0 when `docs/specs/` doesn't exist yet, and `check` refuses the template's
  placeholder text left in an `approved` spec (Problem through Out of scope) or a
  `built` one (any section); `triage_state.py` reads a plain `#N` right after a hold
  phrase ("waits on #N") as the same repo; `metrics.py` pages an issue's comments back to its first "Released
  in" notice, so a notice from before the window keeps a later one out of issue to
  release, and its docstring and SKILL.md name the backport shape lead time misreads
  (#68)

## [0.10.0] - 2026-10-04

### Added

- `shipmill operate` rolls back an environment that fails `[operate] rollback_after`
  health checks in a row (default 3) to the previous tag that reached `success` there,
  under `rollback` autonomy and the hold: act dispatches, propose (or the hold) has the
  incident propose it for `operate --approve-rollback <environment>`, observe reports.
  It opens one issue per environment and bad tag, labelled `[operate] incident_label`
  (default `incident`), with the failing check and the rollback, and comments on it
  when the environment is healthy again or when the rollback fails its checks too, where
  it stops. An open incident holds the `[gates] blocker_lanes` like the blocker label.
  A failed check now writes a `failure` status each time, up to `rollback_after` in a
  row, to count them. `doctor` validates `[operate]` and wants `issues: write` on the
  operate job once an environment has `health` (#31)
- github-ship-watch reports what `shipmill operate` found, for a repo whose config has
  `[environments.<name>]` tables: OPERATE_FAILED (the operate caller's latest run failed;
  the watch reruns a flaky one once), UNHEALTHY (an environment's newest `shipmill health`
  status is a failure), PROMOTION_DUE (an open "Ready to promote" proposal, with its
  approve command, or a promotion operate would make or propose if it ran on a schedule),
  and INCIDENT_OPEN (an open issue labelled `[operate] incident_label`, default
  `incident`, with its age and the PRs linked to close it). Every repo with a shipmill
  config also gets a HOLD row for an open `shipmill-hold` issue, with who opened it and
  when; a hold alone doesn't make the watch exit 1. Incidents and holds lead the report,
  and the watch never deploys or rolls back itself (#33)
- Under `release = "propose"`, the land workflow closes the lane's "Ready to release"
  issue once the release is tagged, with a comment naming the tag and the run, and says so
  when the issue proposed another version. A new `close-proposal` job takes the caller's
  grant: add `issues: write` to the land job in `.github/workflows/release.yml` (`shipmill
  init` writes it, and `doctor` warns under `release = "propose"` until it is there).
  `shipmill operate` closes a "Ready to promote" or "Ready to deploy" issue once the
  environment runs its tag or a later one, whoever deployed it (#40)
- github-ship-watch's `metrics.py` measures a repo over a window (`--days 30` by
  default) from GitHub alone: deploy frequency (successful deployments per environment,
  or stable releases for a repo without deployments), lead time for changes (a merged
  PR's first commit to the first stable release that shipped its merge commit, median
  and p90), change failure rate (incidents per deploy, or `release-blocker` issues and
  hotfix releases per release), time to restore (an incident to operate's "healthy
  again" comment or its close), issue to release (an issue to its "Released in" notice),
  human touch (merges a person merged or approved; an agent merging with a person's
  token counts as the person), and agent share (merged PRs whose body carries Claude
  Code's footer or whose commits carry a `Co-Authored-By: Claude` or `Claude-Session:`
  trailer, and how many of those a person approved in a review). An empty measure reads
  "no data", never 0. A table by default, `--json`, and `--markdown` for a weekly post on
  the roadmap issue, which the user schedules (#56)
- A spec gate in github-issue-triage: an issue asking for new behaviour gets the verdict
  **feature** and a spec file `docs/specs/NNN-<slug>.md` (template in
  `docs/specs/TEMPLATE.md`) with numbered acceptance criteria `S-NNN-k`, merged through
  its own PR before any implementer starts. `specs.py` writes the next spec (`new`),
  validates them (`check`), lists the specs a path or area touches (`find`), and prints a
  spec's criteria for the implementer brief (`criteria`). `triage_state.py` reads a hold
  on a pull request of the same repo: BLOCKED while it is open, UNBLOCKED once it
  merges, and the new action state SPEC_REFUSED (exit 1) once it closes unmerged, until
  a newer triage comment decides again (#54)
- Acceptance tests from specs: a test proves a spec's criterion by naming it,
  `test_s007_2_...` (Go `TestS007_2...`) or a `proves: S-007-2` comment line, and
  `specs.py coverage [--spec NNN]` lists each criterion of the built specs with the
  Python, JS/TS, Go, and Rust tests that prove it, exiting 1 when one has none. A spec
  carries `status: draft|approved|built` and a Verification section; `check` refuses a
  built spec that lists no issues or leaves a criterion out of Verification. CI runs
  `check` and `coverage`, and the reviewer brief checks that each listed test really
  asserts its criterion (#55)

### Fixed

- The triage skills keep an implementer's or reviewer's worktree until its PR merges, not
  just until it's pushed: a revision goes back to the same agent through SendMessage, and
  an agent whose worktree was removed can't be resumed
- `doctor` accepts the repository hosting shipmill calling its own `operate.yml` locally:
  there `.github/workflows/operate.yml` is the reusable workflow, so the operate check
  reads the workflow that `uses: ./.github/workflows/operate.yml` instead. A blank line no
  longer hides what follows it: a later job's `environment:`, or a workflow input (#53)
- `shipmill propose` and `shipmill operate` no longer open a duplicate proposal issue in
  a repo with more than 500 open issues: every release or deploy proposal carries a
  `shipmill-proposal` label, created on first use, and is found among the open issues with
  it (refusing, rather than guessing, at 100 of them). A proposal opened before the label
  is found once by the old scan and labelled on that update.
  github-ship-watch finds proposals by the label too, falling back to its title search
  while none has it (#41)
- A config error for an unknown key in `[lanes]`, `[bump]` or `[autonomy]` lists the allowed
  keys as the values the file accepts (`'dev', 'hotfix', 'rc', 'stable'`), not as enum
  reprs like `<Lane.DEV: 'dev'>` (#59)
- Proposal follow-ups: `land` leaves open a release proposal for a later version than the
  one it released, as `operate` does for a deploy proposal; github-ship-watch always runs
  its title search beside the label lookup, so an unlabelled deploy proposal shows while a
  labelled one exists; and a `shipmill-proposal` label another run created meanwhile no
  longer fails the run (#65)

## [0.9.0] - 2026-10-04

### Added

- `shipmill gate <owner/repo>` starts a Claude Code background session (`claude --bg`)
  for a repo only when its state needs one: it reads the state with code, skips while a
  session it started is still working or waits on you, skips findings unchanged since
  the last launch, and passes the findings in the prompt. The prompt, whether open PRs
  count as work, and the retry window come from a new `[agents]` section of
  `.github/shipmill.toml`. `--refresh` moves a dedicated, detached checkout to the
  default branch first. The wheel now bundles the skills
- `shipmill launchd <owner/repo>` runs the gate from launchd every few minutes on a
  Mac, with a PATH built from where claude, gh, git, and uvx live outside temporary
  folders. Each pass is a new session, and a quiet tick makes no model call
- shipmill-setup connects the agent side: `setup_state.py` reports releases, the
  `[agents]` section, the plugin in `.claude/settings.json`, and the labels the skills
  read, and `--fix` enables the plugin and creates the labels. The gate on launchd is a
  new choice for where agents run
- `shipmill operate`, run every 10 minutes by the new reusable `operate.yml` through a
  caller that `shipmill init --operate` writes: for each environment it reads the current
  deployment from GitHub, checks its `health` URL (2xx within 10 s; a JSON body's `version`
  must name the deployed release), and records the result as deployment statuses, written
  only when the state changes. It promotes a `from` environment once its source has been
  healthy on a tag for `bake_minutes`, and redeploys a `lane` environment that missed its
  lane's newest tag, each at most once per tag (a deployment of it or a run of the
  workflow on it counts) and under `deploy.<environment>` autonomy:
  act dispatches, propose (or the hold) opens a "Ready to promote" issue that `operate
  --approve <environment>` deploys once, observe reports. `land` now starts environment
  workflows on the tag, so each deployment's ref names it. `doctor` checks the operate
  caller and its permissions once an environment uses `from` or `health` (#30)

## [0.8.0] - 2026-10-04

### Added

- Environments: an `[environments.<name>]` table in `.github/shipmill.toml` names a deploy
  `workflow` and exactly one of `lane` or `from`, plus an optional `health` URL and, with
  `from`, `bake_minutes`; a `from` chain must end at a `lane` environment. `land` starts the
  workflow of each environment whose `lane` is the release's, with `tag` and `environment`
  inputs, and lists it as `deploy.yml@staging`; `from` environments wait for promotion.
  `doctor` checks each workflow takes both inputs and that a job sets `environment:`, so
  GitHub records a deployment; `init` writes a commented example (#29)
- `[autonomy]` in `.github/shipmill.toml` sets each stage to `observe`, `propose`, or `act`
  (`release`, `deploy.<environment>`, and `rollback`, all `act` by default), and an open
  issue labelled `shipmill-hold` turns every `act` into `propose`. Under `release =
  "observe"` a due lane is only reported; under `"propose"`, or while a hold is open, the
  new `propose` job of `prepare.yml` opens or updates one "Ready to release vX on <lane>"
  issue per due lane instead of releasing. A lane started by hand still releases under
  propose; under a hold only a hotfix started by hand does. `doctor` prints the effective
  autonomy per stage and warns on an open hold. Proposing needs `issues: write` on the
  prepare job of the calling workflow, which `shipmill init` now writes; `doctor` warns
  about it only once a stage is set to propose or a hold is open. Each `deploy.<name>` must
  name an environment in `[environments]`. Deploy and rollback autonomy take effect once
  shipmill deploys (#32)

## [0.7.0] - 2026-10-04

### Fixed

- `changelog_guard.py move` carries each entry a rebase dropped into a released section
  under its own `###` heading in Unreleased, creating the heading in Keep a Changelog
  order, and leaves the released section as the base has it; it no longer leaves a bullet
  with no heading. `check` also fails on such a headless bullet and on a duplicate heading
  under Unreleased, and `union` keeps a blank line between a release heading and the
  heading it meets. The landing loop runs `move`, `check`, and the planner's dry run after
  every rebase, and prints the Unreleased section for the lander to read (#25)
- `triage_state.py` reads a busy repo such as pypa/pip: a page GitHub rejects for its
  resource limits is asked again at half the size, down to 10 issues, and one still
  rejected there fails with one error line instead of gh's line per node (#24)

### Added

- `.github/shipmill.toml`, the one config file every shipmill layer will read: `shipmill
  init` writes it, and `doctor` names the file it read. `.github/release-policy.toml` keeps
  working as an alias with the same keys, and `doctor` warns to rename it with `git mv`; a
  repo with both files fails. `init` refuses when either file exists, and `--force` replaces
  the alias with `shipmill.toml`. ship-watch finds either file. Rename to `shipmill.toml`
  only once the shipmill CLI your Release workflow runs (the `tool` input of `prepare.yml`
  and `land.yml`, default `@v0`) is this release or newer (#28)

## [0.6.0] - 2026-10-04

### Added

- "Where the agents run" in the README, and a last hand-over step in `shipmill-setup`
  that asks whether the skills run on demand, on a `/loop`, or as a cloud `/schedule`
  routine, and whether a routine may merge

### Changed

- The `release-lanes-setup` skill is now `shipmill-setup`: `/shipmill-setup` (or
  `/shipmill:shipmill-setup` from the plugin) replaces `/release-lanes-setup`. A checkout
  linked into `~/.agents/skills` re-runs the link loop from the README and removes the
  dangling `release-lanes-setup` link. "Set up release lanes" and "add a release bot"
  still find it

### Fixed

- The design gate finds an open decisions PR by the log file it changes, not by
  `DECISIONS` in its title, which missed a PR titled "Record D-1 and D-2"
- `triage_state.py` pages past the caps of its GitHub query instead of reading a capped
  list as complete: open issues beyond the newest 100, an issue's comments beyond the
  newest 50 (an older verdict or "On hold" line), cross-references beyond the oldest 50
  (a later linked PR), and tags back to the newest stable one. An issue with more than 100
  labels exits 2 as bad input. A repo under the caps still takes one query (#19)

## [0.5.2] - 2026-10-04

### Fixed

- `doctor`'s `work branch` check asks origin for a `shipmill` branch, as `prepare` does,
  instead of reading the clone's fetched refs: a shallow or single-branch clone (such as a
  CI checkout) passed while origin had the branch, and a stale `origin/shipmill` failed
  after it was deleted. It warns when there is no origin or origin can't be reached

## [0.5.1] - 2026-10-04

### Fixed

- A scheduled or hand-started run of the prepare workflow no longer cancels a push run
  waiting out `quiet_minutes`: only a newer push shares the settle job's concurrency
  group, and any other run gets a group of its own (#6)
- `prepare` names a branch `shipmill` on origin that blocks the `shipmill/<tag>` work
  branch, instead of failing with git's raw `cannot lock ref` error, and `doctor` checks
  for it as `work branch` (#7)
- `github-pr-triage` launches reviewer agents from the repo's root and has each confirm
  its remote: from a nested clone, worktree isolation copied the wrong repository and a
  reviewer's fix commits were lost with its worktree
- `triage_state.py` reads an issue's newest triage comment, not its oldest, so a
  re-decision changes NEEDS_PR and clears REVISIT. It compares comment and tag times as
  instants, so a tag date with a UTC offset no longer misorders against a comment's `Z`
  time
- The triage skills record a pass's decisions in one docs PR opened before dispatch, not
  in each implementing PR: decision ids are sequential, so two PRs that each added an
  entry both took the same `D-n`. github-pr-triage renumbers a colliding entry when it
  lands a batch

## [0.5.0] - 2026-10-03

### Added

- A design gate and a decisions log for the triage skills. An issue that changes a flag,
  a format, a default, a public API, or stored state gets its design written into the
  issue and checked against the repo's settled decisions before an implementer starts;
  a departure waits for the user. `decisions.py` keeps the log (`DECISIONS.md` or
  `docs/decisions.md`): `add` numbers and links entries, `find` lists the rules a diff's
  paths touch, `check` validates it. Implementer and reviewer briefs carry the matching
  rules, and github-pr-triage holds a PR that departs from one

## [0.4.0] - 2026-10-03

### Added

- The `github-ship-watch` skill: one pass reports a failed or stalled release bot, a
  release missing from PyPI, fixed issues not yet told which version shipped them, and
  issues triage owes, then finishes what the policy already decided. Its
  `watch_state.py` exits 1 when anything needs action, for `/loop` and `/schedule`

### Fixed

- `shipped.py` fetches tags with `--force`, so it no longer fails once the bot has moved
  a major tag such as `v0`

## [0.3.1] - 2026-10-03

### Fixed

- `github-pr-triage` starts a shipmill bot by naming the lane: a hand-started
  `lane=policy` run cancels the push run's quiet wait and then skips (#6)

## [0.3.0] - 2026-10-03

### Breaking

- release-lanes is now shipmill: the package, the CLI (`shipmill init`, `shipmill doctor`,
  and the rest), and the repository `romamo/shipmill`. In a repository already set up,
  replace `romamo/release-lanes` with `romamo/shipmill` in `.github/workflows/release.yml`,
  or run `shipmill init --force` and restore your policy. A release commit now waits on a
  `shipmill/` work branch

### Added

- The GitHub workflow skills join `release-lanes-setup`: `github-issue-triage`,
  `github-issue-resolve`, and `github-pr-triage`, with the whole flow in `docs/flow.md`.
  `github-pr-triage` starts a shipmill bot after its last merge
- A Claude Code plugin and marketplace in `.claude-plugin`: `/plugin marketplace add
  romamo/shipmill`, then `/plugin install shipmill@shipmill`. Each release sets the
  plugin's version

## [0.2.1] - 2026-10-03

### Fixed

- A rejected push now reports git's error, and a rejected tag push is retried: the first
  release by the bot (0.2.0) landed on main, but its tag push was refused and the
  reason was lost. The `land` step also fails when the tool fails, where a pipe through
  `tee` hid the failure and reported success

## [0.2.0] - 2026-10-03

### Added

- `doctor` fails a `[tool.uv.sources]` entry taken from a local path or installed
  editable, and the setup skill covers a Python package's build and smoke test

## [0.1.0] - 2026-10-01

### Added

- Release lanes driven by a hand-written CHANGELOG: `dev` and `rc` pre-releases cut from
  main without touching it, `stable` releases promoted from an rc that soaked without a
  blocker, and `hotfix` releases of chosen pull requests from `release/X.Y`
- Triggers per lane (quiet time after merges, schedule windows in any time zone, a finished
  milestone) and gates (a `release-blocker` label, freeze windows); every lane can be
  started by hand
- Version bumps from the pending entries' headings or from the paths changed since the last
  stable tag
- Reusable `prepare.yml` and `land.yml` workflows that run the caller's CI on the release
  commit before tagging, then sync a stable release made off main back into main
- `init` and `doctor` commands, and a setup skill for agents

[Unreleased]: https://github.com/shipmill/shipmill/compare/v0.193.0...HEAD
[0.193.0]: https://github.com/shipmill/shipmill/compare/v0.192.0...v0.193.0
[0.192.0]: https://github.com/shipmill/shipmill/compare/v0.191.0...v0.192.0
[0.191.0]: https://github.com/shipmill/shipmill/compare/v0.190.1...v0.191.0
[0.190.1]: https://github.com/shipmill/shipmill/compare/v0.190.0...v0.190.1
[0.190.0]: https://github.com/shipmill/shipmill/compare/v0.189.0...v0.190.0
[0.189.0]: https://github.com/shipmill/shipmill/compare/v0.188.0...v0.189.0
[0.188.0]: https://github.com/shipmill/shipmill/compare/v0.187.0...v0.188.0
[0.187.0]: https://github.com/shipmill/shipmill/compare/v0.186.0...v0.187.0
[0.186.0]: https://github.com/shipmill/shipmill/compare/v0.185.0...v0.186.0
[0.185.0]: https://github.com/shipmill/shipmill/compare/v0.184.0...v0.185.0
[0.184.0]: https://github.com/shipmill/shipmill/compare/v0.183.0...v0.184.0
[0.183.0]: https://github.com/shipmill/shipmill/compare/v0.182.0...v0.183.0
[0.182.0]: https://github.com/shipmill/shipmill/compare/v0.181.0...v0.182.0
[0.181.0]: https://github.com/shipmill/shipmill/compare/v0.180.0...v0.181.0
[0.180.0]: https://github.com/shipmill/shipmill/compare/v0.179.3...v0.180.0
[0.179.3]: https://github.com/shipmill/shipmill/compare/v0.179.2...v0.179.3
[0.179.2]: https://github.com/shipmill/shipmill/compare/v0.179.1...v0.179.2
[0.179.1]: https://github.com/shipmill/shipmill/compare/v0.179.0...v0.179.1
[0.179.0]: https://github.com/shipmill/shipmill/compare/v0.178.0...v0.179.0
[0.178.0]: https://github.com/shipmill/shipmill/compare/v0.177.0...v0.178.0
[0.177.0]: https://github.com/shipmill/shipmill/compare/v0.176.0...v0.177.0
[0.176.0]: https://github.com/shipmill/shipmill/compare/v0.175.0...v0.176.0
[0.175.0]: https://github.com/shipmill/shipmill/compare/v0.174.0...v0.175.0
[0.174.0]: https://github.com/shipmill/shipmill/compare/v0.173.1...v0.174.0
[0.173.1]: https://github.com/shipmill/shipmill/compare/v0.173.0...v0.173.1
[0.173.0]: https://github.com/shipmill/shipmill/compare/v0.172.0...v0.173.0
[0.172.0]: https://github.com/shipmill/shipmill/compare/v0.171.0...v0.172.0
[0.171.0]: https://github.com/shipmill/shipmill/compare/v0.170.0...v0.171.0
[0.170.0]: https://github.com/shipmill/shipmill/compare/v0.169.0...v0.170.0
[0.169.0]: https://github.com/shipmill/shipmill/compare/v0.168.0...v0.169.0
[0.168.0]: https://github.com/shipmill/shipmill/compare/v0.167.0...v0.168.0
[0.167.0]: https://github.com/shipmill/shipmill/compare/v0.166.0...v0.167.0
[0.166.0]: https://github.com/shipmill/shipmill/compare/v0.165.0...v0.166.0
[0.165.0]: https://github.com/shipmill/shipmill/compare/v0.164.1...v0.165.0
[0.164.1]: https://github.com/shipmill/shipmill/compare/v0.164.0...v0.164.1
[0.164.0]: https://github.com/shipmill/shipmill/compare/v0.163.2...v0.164.0
[0.163.2]: https://github.com/shipmill/shipmill/compare/v0.163.1...v0.163.2
[0.163.1]: https://github.com/shipmill/shipmill/compare/v0.163.0...v0.163.1
[0.163.0]: https://github.com/shipmill/shipmill/compare/v0.162.2...v0.163.0
[0.162.2]: https://github.com/shipmill/shipmill/compare/v0.162.1...v0.162.2
[0.162.1]: https://github.com/shipmill/shipmill/compare/v0.162.0...v0.162.1
[0.162.0]: https://github.com/shipmill/shipmill/compare/v0.161.2...v0.162.0
[0.161.2]: https://github.com/shipmill/shipmill/compare/v0.161.1...v0.161.2
[0.161.1]: https://github.com/shipmill/shipmill/compare/v0.161.0...v0.161.1
[0.161.0]: https://github.com/shipmill/shipmill/compare/v0.160.1...v0.161.0
[0.160.1]: https://github.com/shipmill/shipmill/compare/v0.160.0...v0.160.1
[0.160.0]: https://github.com/shipmill/shipmill/compare/v0.159.0...v0.160.0
[0.159.0]: https://github.com/shipmill/shipmill/compare/v0.158.1...v0.159.0
[0.158.1]: https://github.com/shipmill/shipmill/compare/v0.158.0...v0.158.1
[0.158.0]: https://github.com/shipmill/shipmill/compare/v0.157.1...v0.158.0
[0.157.1]: https://github.com/shipmill/shipmill/compare/v0.157.0...v0.157.1
[0.157.0]: https://github.com/shipmill/shipmill/compare/v0.156.0...v0.157.0
[0.156.0]: https://github.com/shipmill/shipmill/compare/v0.155.0...v0.156.0
[0.155.0]: https://github.com/shipmill/shipmill/compare/v0.154.1...v0.155.0
[0.154.1]: https://github.com/shipmill/shipmill/compare/v0.154.0...v0.154.1
[0.154.0]: https://github.com/shipmill/shipmill/compare/v0.153.0...v0.154.0
[0.153.0]: https://github.com/shipmill/shipmill/compare/v0.152.0...v0.153.0
[0.152.0]: https://github.com/shipmill/shipmill/compare/v0.151.0...v0.152.0
[0.151.0]: https://github.com/shipmill/shipmill/compare/v0.150.0...v0.151.0
[0.150.0]: https://github.com/shipmill/shipmill/compare/v0.149.2...v0.150.0
[0.149.2]: https://github.com/shipmill/shipmill/compare/v0.149.1...v0.149.2
[0.149.1]: https://github.com/shipmill/shipmill/compare/v0.149.0...v0.149.1
[0.149.0]: https://github.com/shipmill/shipmill/compare/v0.148.2...v0.149.0
[0.148.2]: https://github.com/shipmill/shipmill/compare/v0.148.1...v0.148.2
[0.148.1]: https://github.com/shipmill/shipmill/compare/v0.148.0...v0.148.1
[0.148.0]: https://github.com/shipmill/shipmill/compare/v0.147.2...v0.148.0
[0.147.2]: https://github.com/shipmill/shipmill/compare/v0.147.1...v0.147.2
[0.147.1]: https://github.com/shipmill/shipmill/compare/v0.147.0...v0.147.1
[0.147.0]: https://github.com/shipmill/shipmill/compare/v0.146.2...v0.147.0
[0.146.2]: https://github.com/shipmill/shipmill/compare/v0.146.1...v0.146.2
[0.146.1]: https://github.com/shipmill/shipmill/compare/v0.146.0...v0.146.1
[0.146.0]: https://github.com/shipmill/shipmill/compare/v0.145.0...v0.146.0
[0.145.0]: https://github.com/shipmill/shipmill/compare/v0.144.0...v0.145.0
[0.144.0]: https://github.com/shipmill/shipmill/compare/v0.143.0...v0.144.0
[0.143.0]: https://github.com/shipmill/shipmill/compare/v0.142.0...v0.143.0
[0.142.0]: https://github.com/shipmill/shipmill/compare/v0.141.0...v0.142.0
[0.141.0]: https://github.com/shipmill/shipmill/compare/v0.140.0...v0.141.0
[0.140.0]: https://github.com/shipmill/shipmill/compare/v0.139.0...v0.140.0
[0.139.0]: https://github.com/shipmill/shipmill/compare/v0.138.0...v0.139.0
[0.138.0]: https://github.com/shipmill/shipmill/compare/v0.137.0...v0.138.0
[0.137.0]: https://github.com/shipmill/shipmill/compare/v0.136.0...v0.137.0
[0.136.0]: https://github.com/shipmill/shipmill/compare/v0.135.0...v0.136.0
[0.135.0]: https://github.com/shipmill/shipmill/compare/v0.134.2...v0.135.0
[0.134.2]: https://github.com/shipmill/shipmill/compare/v0.134.1...v0.134.2
[0.134.1]: https://github.com/shipmill/shipmill/compare/v0.134.0...v0.134.1
[0.134.0]: https://github.com/shipmill/shipmill/compare/v0.133.0...v0.134.0
[0.133.0]: https://github.com/shipmill/shipmill/compare/v0.132.0...v0.133.0
[0.132.0]: https://github.com/shipmill/shipmill/compare/v0.131.0...v0.132.0
[0.131.0]: https://github.com/shipmill/shipmill/compare/v0.130.0...v0.131.0
[0.130.0]: https://github.com/shipmill/shipmill/compare/v0.129.0...v0.130.0
[0.129.0]: https://github.com/shipmill/shipmill/compare/v0.128.4...v0.129.0
[0.128.4]: https://github.com/shipmill/shipmill/compare/v0.128.3...v0.128.4
[0.128.3]: https://github.com/shipmill/shipmill/compare/v0.128.2...v0.128.3
[0.128.2]: https://github.com/shipmill/shipmill/compare/v0.128.1...v0.128.2
[0.128.1]: https://github.com/shipmill/shipmill/compare/v0.128.0...v0.128.1
[0.128.0]: https://github.com/shipmill/shipmill/compare/v0.127.2...v0.128.0
[0.127.2]: https://github.com/shipmill/shipmill/compare/v0.127.1...v0.127.2
[0.127.1]: https://github.com/shipmill/shipmill/compare/v0.127.0...v0.127.1
[0.127.0]: https://github.com/shipmill/shipmill/compare/v0.126.0...v0.127.0
[0.126.0]: https://github.com/shipmill/shipmill/compare/v0.125.0...v0.126.0
[0.125.0]: https://github.com/shipmill/shipmill/compare/v0.124.1...v0.125.0
[0.124.1]: https://github.com/shipmill/shipmill/compare/v0.124.0...v0.124.1
[0.124.0]: https://github.com/shipmill/shipmill/compare/v0.123.2...v0.124.0
[0.123.2]: https://github.com/shipmill/shipmill/compare/v0.123.1...v0.123.2
[0.123.1]: https://github.com/shipmill/shipmill/compare/v0.123.0...v0.123.1
[0.123.0]: https://github.com/shipmill/shipmill/compare/v0.122.2...v0.123.0
[0.122.2]: https://github.com/shipmill/shipmill/compare/v0.122.1...v0.122.2
[0.122.1]: https://github.com/shipmill/shipmill/compare/v0.122.0...v0.122.1
[0.122.0]: https://github.com/shipmill/shipmill/compare/v0.121.0...v0.122.0
[0.121.0]: https://github.com/shipmill/shipmill/compare/v0.120.0...v0.121.0
[0.120.0]: https://github.com/shipmill/shipmill/compare/v0.119.2...v0.120.0
[0.119.2]: https://github.com/shipmill/shipmill/compare/v0.119.1...v0.119.2
[0.119.1]: https://github.com/shipmill/shipmill/compare/v0.119.0...v0.119.1
[0.119.0]: https://github.com/shipmill/shipmill/compare/v0.118.0...v0.119.0
[0.118.0]: https://github.com/shipmill/shipmill/compare/v0.117.5...v0.118.0
[0.117.5]: https://github.com/shipmill/shipmill/compare/v0.117.4...v0.117.5
[0.117.4]: https://github.com/shipmill/shipmill/compare/v0.117.3...v0.117.4
[0.117.3]: https://github.com/shipmill/shipmill/compare/v0.117.2...v0.117.3
[0.117.2]: https://github.com/shipmill/shipmill/compare/v0.117.1...v0.117.2
[0.117.1]: https://github.com/shipmill/shipmill/compare/v0.117.0...v0.117.1
[0.117.0]: https://github.com/shipmill/shipmill/compare/v0.116.0...v0.117.0
[0.116.0]: https://github.com/shipmill/shipmill/compare/v0.115.0...v0.116.0
[0.115.0]: https://github.com/shipmill/shipmill/compare/v0.114.0...v0.115.0
[0.114.0]: https://github.com/shipmill/shipmill/compare/v0.113.0...v0.114.0
[0.113.0]: https://github.com/shipmill/shipmill/compare/v0.112.0...v0.113.0
[0.112.0]: https://github.com/shipmill/shipmill/compare/v0.111.0...v0.112.0
[0.111.0]: https://github.com/shipmill/shipmill/compare/v0.110.0...v0.111.0
[0.110.0]: https://github.com/shipmill/shipmill/compare/v0.109.0...v0.110.0
[0.109.0]: https://github.com/shipmill/shipmill/compare/v0.108.0...v0.109.0
[0.108.0]: https://github.com/shipmill/shipmill/compare/v0.107.1...v0.108.0
[0.107.1]: https://github.com/shipmill/shipmill/compare/v0.107.0...v0.107.1
[0.107.0]: https://github.com/shipmill/shipmill/compare/v0.106.0...v0.107.0
[0.106.0]: https://github.com/shipmill/shipmill/compare/v0.105.0...v0.106.0
[0.105.0]: https://github.com/shipmill/shipmill/compare/v0.104.0...v0.105.0
[0.104.0]: https://github.com/shipmill/shipmill/compare/v0.103.0...v0.104.0
[0.103.0]: https://github.com/shipmill/shipmill/compare/v0.102.0...v0.103.0
[0.102.0]: https://github.com/shipmill/shipmill/compare/v0.101.0...v0.102.0
[0.101.0]: https://github.com/shipmill/shipmill/compare/v0.100.2...v0.101.0
[0.100.2]: https://github.com/shipmill/shipmill/compare/v0.100.1...v0.100.2
[0.100.1]: https://github.com/shipmill/shipmill/compare/v0.100.0...v0.100.1
[0.100.0]: https://github.com/shipmill/shipmill/compare/v0.99.0...v0.100.0
[0.99.0]: https://github.com/shipmill/shipmill/compare/v0.98.1...v0.99.0
[0.98.1]: https://github.com/shipmill/shipmill/compare/v0.98.0...v0.98.1
[0.98.0]: https://github.com/shipmill/shipmill/compare/v0.97.0...v0.98.0
[0.97.0]: https://github.com/shipmill/shipmill/compare/v0.96.0...v0.97.0
[0.96.0]: https://github.com/shipmill/shipmill/compare/v0.95.0...v0.96.0
[0.95.0]: https://github.com/shipmill/shipmill/compare/v0.94.0...v0.95.0
[0.94.0]: https://github.com/shipmill/shipmill/compare/v0.93.0...v0.94.0
[0.93.0]: https://github.com/shipmill/shipmill/compare/v0.92.0...v0.93.0
[0.92.0]: https://github.com/shipmill/shipmill/compare/v0.91.0...v0.92.0
[0.91.0]: https://github.com/shipmill/shipmill/compare/v0.90.0...v0.91.0
[0.90.0]: https://github.com/shipmill/shipmill/compare/v0.89.1...v0.90.0
[0.89.1]: https://github.com/shipmill/shipmill/compare/v0.89.0...v0.89.1
[0.89.0]: https://github.com/shipmill/shipmill/compare/v0.88.0...v0.89.0
[0.88.0]: https://github.com/shipmill/shipmill/compare/v0.87.1...v0.88.0
[0.87.1]: https://github.com/shipmill/shipmill/compare/v0.87.0...v0.87.1
[0.87.0]: https://github.com/shipmill/shipmill/compare/v0.86.0...v0.87.0
[0.86.0]: https://github.com/shipmill/shipmill/compare/v0.85.1...v0.86.0
[0.85.1]: https://github.com/shipmill/shipmill/compare/v0.85.0...v0.85.1
[0.85.0]: https://github.com/shipmill/shipmill/compare/v0.84.0...v0.85.0
[0.84.0]: https://github.com/shipmill/shipmill/compare/v0.83.0...v0.84.0
[0.83.0]: https://github.com/shipmill/shipmill/compare/v0.82.0...v0.83.0
[0.82.0]: https://github.com/shipmill/shipmill/compare/v0.81.1...v0.82.0
[0.81.1]: https://github.com/shipmill/shipmill/compare/v0.81.0...v0.81.1
[0.81.0]: https://github.com/shipmill/shipmill/compare/v0.80.1...v0.81.0
[0.80.1]: https://github.com/shipmill/shipmill/compare/v0.80.0...v0.80.1
[0.80.0]: https://github.com/shipmill/shipmill/compare/v0.79.0...v0.80.0
[0.79.0]: https://github.com/shipmill/shipmill/compare/v0.78.0...v0.79.0
[0.78.0]: https://github.com/shipmill/shipmill/compare/v0.77.0...v0.78.0
[0.77.0]: https://github.com/shipmill/shipmill/compare/v0.76.0...v0.77.0
[0.76.0]: https://github.com/shipmill/shipmill/compare/v0.75.0...v0.76.0
[0.75.0]: https://github.com/shipmill/shipmill/compare/v0.74.0...v0.75.0
[0.74.0]: https://github.com/shipmill/shipmill/compare/v0.73.1...v0.74.0
[0.73.1]: https://github.com/shipmill/shipmill/compare/v0.73.0...v0.73.1
[0.73.0]: https://github.com/shipmill/shipmill/compare/v0.72.0...v0.73.0
[0.72.0]: https://github.com/shipmill/shipmill/compare/v0.71.0...v0.72.0
[0.71.0]: https://github.com/shipmill/shipmill/compare/v0.70.0...v0.71.0
[0.70.0]: https://github.com/shipmill/shipmill/compare/v0.69.0...v0.70.0
[0.69.0]: https://github.com/shipmill/shipmill/compare/v0.68.0...v0.69.0
[0.68.0]: https://github.com/shipmill/shipmill/compare/v0.67.0...v0.68.0
[0.67.0]: https://github.com/shipmill/shipmill/compare/v0.66.0...v0.67.0
[0.66.0]: https://github.com/shipmill/shipmill/compare/v0.65.0...v0.66.0
[0.65.0]: https://github.com/shipmill/shipmill/compare/v0.64.0...v0.65.0
[0.64.0]: https://github.com/shipmill/shipmill/compare/v0.63.0...v0.64.0
[0.63.0]: https://github.com/shipmill/shipmill/compare/v0.62.0...v0.63.0
[0.62.0]: https://github.com/shipmill/shipmill/compare/v0.61.0...v0.62.0
[0.61.0]: https://github.com/shipmill/shipmill/compare/v0.60.0...v0.61.0
[0.60.0]: https://github.com/shipmill/shipmill/compare/v0.59.1...v0.60.0
[0.59.1]: https://github.com/shipmill/shipmill/compare/v0.59.0...v0.59.1
[0.59.0]: https://github.com/shipmill/shipmill/compare/v0.58.0...v0.59.0
[0.58.0]: https://github.com/shipmill/shipmill/compare/v0.57.0...v0.58.0
[0.57.0]: https://github.com/shipmill/shipmill/compare/v0.56.0...v0.57.0
[0.56.0]: https://github.com/shipmill/shipmill/compare/v0.55.0...v0.56.0
[0.55.0]: https://github.com/shipmill/shipmill/compare/v0.54.0...v0.55.0
[0.54.0]: https://github.com/shipmill/shipmill/compare/v0.53.0...v0.54.0
[0.53.0]: https://github.com/shipmill/shipmill/compare/v0.52.0...v0.53.0
[0.52.0]: https://github.com/shipmill/shipmill/compare/v0.51.0...v0.52.0
[0.51.0]: https://github.com/shipmill/shipmill/compare/v0.50.0...v0.51.0
[0.50.0]: https://github.com/shipmill/shipmill/compare/v0.49.0...v0.50.0
[0.49.0]: https://github.com/shipmill/shipmill/compare/v0.48.0...v0.49.0
[0.48.0]: https://github.com/shipmill/shipmill/compare/v0.47.0...v0.48.0
[0.47.0]: https://github.com/shipmill/shipmill/compare/v0.46.0...v0.47.0
[0.46.0]: https://github.com/shipmill/shipmill/compare/v0.45.0...v0.46.0
[0.45.0]: https://github.com/shipmill/shipmill/compare/v0.44.0...v0.45.0
[0.44.0]: https://github.com/shipmill/shipmill/compare/v0.43.0...v0.44.0
[0.43.0]: https://github.com/shipmill/shipmill/compare/v0.42.0...v0.43.0
[0.42.0]: https://github.com/shipmill/shipmill/compare/v0.41.2...v0.42.0
[0.41.2]: https://github.com/shipmill/shipmill/compare/v0.41.1...v0.41.2
[0.41.1]: https://github.com/shipmill/shipmill/compare/v0.41.0...v0.41.1
[0.41.0]: https://github.com/shipmill/shipmill/compare/v0.40.0...v0.41.0
[0.40.0]: https://github.com/shipmill/shipmill/compare/v0.39.0...v0.40.0
[0.39.0]: https://github.com/shipmill/shipmill/compare/v0.38.0...v0.39.0
[0.38.0]: https://github.com/shipmill/shipmill/compare/v0.37.0...v0.38.0
[0.37.0]: https://github.com/shipmill/shipmill/compare/v0.36.0...v0.37.0
[0.36.0]: https://github.com/shipmill/shipmill/compare/v0.35.0...v0.36.0
[0.35.0]: https://github.com/shipmill/shipmill/compare/v0.34.0...v0.35.0
[0.34.0]: https://github.com/shipmill/shipmill/compare/v0.33.2...v0.34.0
[0.33.2]: https://github.com/shipmill/shipmill/compare/v0.33.1...v0.33.2
[0.33.1]: https://github.com/shipmill/shipmill/compare/v0.33.0...v0.33.1
[0.33.0]: https://github.com/shipmill/shipmill/compare/v0.32.2...v0.33.0
[0.32.2]: https://github.com/shipmill/shipmill/compare/v0.32.1...v0.32.2
[0.32.1]: https://github.com/shipmill/shipmill/compare/v0.32.0...v0.32.1
[0.32.0]: https://github.com/shipmill/shipmill/compare/v0.31.1...v0.32.0
[0.31.1]: https://github.com/shipmill/shipmill/compare/v0.31.0...v0.31.1
[0.31.0]: https://github.com/shipmill/shipmill/compare/v0.30.0...v0.31.0
[0.30.0]: https://github.com/shipmill/shipmill/compare/v0.29.0...v0.30.0
[0.29.0]: https://github.com/shipmill/shipmill/compare/v0.28.0...v0.29.0
[0.28.0]: https://github.com/shipmill/shipmill/compare/v0.27.0...v0.28.0
[0.27.0]: https://github.com/shipmill/shipmill/compare/v0.26.0...v0.27.0
[0.26.0]: https://github.com/shipmill/shipmill/compare/v0.25.0...v0.26.0
[0.25.0]: https://github.com/shipmill/shipmill/compare/v0.24.0...v0.25.0
[0.24.0]: https://github.com/shipmill/shipmill/compare/v0.23.0...v0.24.0
[0.23.0]: https://github.com/shipmill/shipmill/compare/v0.22.0...v0.23.0
[0.22.0]: https://github.com/shipmill/shipmill/compare/v0.21.0...v0.22.0
[0.21.0]: https://github.com/shipmill/shipmill/compare/v0.20.0...v0.21.0
[0.20.0]: https://github.com/shipmill/shipmill/compare/v0.19.0...v0.20.0
[0.19.0]: https://github.com/shipmill/shipmill/compare/v0.18.0...v0.19.0
[0.18.0]: https://github.com/shipmill/shipmill/compare/v0.17.0...v0.18.0
[0.17.0]: https://github.com/shipmill/shipmill/compare/v0.16.0...v0.17.0
[0.16.0]: https://github.com/shipmill/shipmill/compare/v0.15.0...v0.16.0
[0.15.0]: https://github.com/shipmill/shipmill/compare/v0.14.0...v0.15.0
[0.14.0]: https://github.com/romamo/shipmill/compare/v0.13.0...v0.14.0
[0.13.0]: https://github.com/romamo/shipmill/compare/v0.12.0...v0.13.0
[0.12.0]: https://github.com/romamo/shipmill/compare/v0.11.0...v0.12.0
[0.11.0]: https://github.com/romamo/shipmill/compare/v0.10.1...v0.11.0
[0.10.1]: https://github.com/romamo/shipmill/compare/v0.10.0...v0.10.1
[0.10.0]: https://github.com/romamo/shipmill/compare/v0.9.0...v0.10.0
[0.9.0]: https://github.com/romamo/shipmill/compare/v0.8.0...v0.9.0
[0.8.0]: https://github.com/romamo/shipmill/compare/v0.7.0...v0.8.0
[0.7.0]: https://github.com/romamo/shipmill/compare/v0.6.0...v0.7.0
[0.6.0]: https://github.com/romamo/shipmill/compare/v0.5.2...v0.6.0
[0.5.2]: https://github.com/romamo/shipmill/compare/v0.5.1...v0.5.2
[0.5.1]: https://github.com/romamo/shipmill/compare/v0.5.0...v0.5.1
[0.5.0]: https://github.com/romamo/shipmill/compare/v0.4.0...v0.5.0
[0.4.0]: https://github.com/romamo/shipmill/compare/v0.3.1...v0.4.0
[0.3.1]: https://github.com/romamo/shipmill/compare/v0.3.0...v0.3.1
[0.3.0]: https://github.com/romamo/shipmill/compare/v0.2.1...v0.3.0
[0.2.1]: https://github.com/romamo/shipmill/compare/v0.2.0...v0.2.1
[0.2.0]: https://github.com/romamo/shipmill/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/romamo/shipmill/releases/tag/v0.1.0
