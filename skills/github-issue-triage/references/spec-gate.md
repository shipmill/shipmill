# Spec gate

A feature is designed once, in a spec file the maintainers review line by line, before any implementer starts. Merging the spec is the approval: one review instead of a question on every PR that builds it. The maintainer approves it either by merging the spec PR or by a trusted answer to its needs-decision question that takes every recommendation unchanged; after such an answer github-pr-triage lands the spec PR once it is mergeable and green (D-49, [Approved by an answer](#approved-by-an-answer)). A spec's approval is the `scope` zone, which no agent takes on its own ([Who decides](needs-decision.md#who-decides)). Specs live in `docs/specs/NNN-<slug>.md` and are merged through a pull request before their build starts; issue bodies link to the spec, they don't hold it (shipmill's own D-5).

## Feature, contract change, or bug fix

| The issue asks for | Verdict | Gate |
|---|---|---|
| A bug fix that restores documented behaviour, or an internal refactor | **implement** | None |
| A change to a contract (a flag, a format, a default, a public API, stored state) that stays within today's behaviour | **implement** | The [design gate](design-gate.md) |
| A user's request for new behaviour (a new command, a new layer, a workflow users haven't had) that no accepted opportunity covers | **opportunity** | Product intake: grouped into an opportunity the maintainer accepts or declines; no spec yet |
| New behaviour beyond a bug fix or a contract tweak that the maintainer already wants (below) | **feature** | This gate: a merged spec first, then **implement** |

When in doubt between a contract tweak and a feature, ask whether a reviewer would want to approve the acceptance criteria before the code exists. If yes, it's a feature, or an opportunity while the maintainer hasn't wanted it yet.

## Where features come from

A spec is written only for work the maintainer has chosen, so a review of the spec is a review of how, never of whether:

- **An accepted opportunity:** an issue labelled `opportunity` and `planned`. Product intake grouped the users' requests into it and the maintainer accepted it (D-10); `intake_state.py` reads it ACCEPTED until triage's **feature** comment, then HANDED_OFF. The opportunity issue is the feature issue, and the spec's Problem starts from its Problem and Evidence
- **A request an accepted opportunity covers:** the spec is the opportunity's. Run this gate on the opportunity issue, or extend its spec when it has one; the request holds on the opportunity (comments.md, Feature)
- **An issue the maintainer filed** (author association owner, member, or collaborator): the filing is the decision
- **A feature item of an accepted plan:** an issue product intake filed whose first line is the plan-item marker `<!-- shipmill:plan-item #P W-n -->`, under a goal plan #P that `intake_state.py --plans` reads PLAN_ACCEPTED or PLAN_FILED (spec 028). The maintainer's accept chose the work, not its design: it still needs its own spec, merged with `status: approved` before its build, like any feature here. The spec's Problem starts from the item and the plan's Goal and Order

Any other request for new behaviour is an **opportunity**: triage comments the hand-off (comments.md, Opportunity) and leaves the grouping to product intake. A request whose outcome was declined goes there too, where intake records it against the decline.

## The gate

1. **Read what's settled.** `specs.py find <the paths and areas the feature touches>` lists specs that already cover them: extend one of those rather than writing a second. `decisions.py find` on the same terms gives the rules the spec relies on
2. **Write the spec.** `specs.py new <slug>` writes `docs/specs/NNN-<slug>.md` from the template with the next number and `status: draft`. When the repo has a direction, `docs/product.md`, add a `serves:` line right after the status line naming the goals the feature serves (`serves: G-2, G-3`, ids from its Goals), or `serves: quality bar`; `check` refuses a spec that isn't built without one, or naming an id the direction doesn't list. Fill in every section from the issue and the code, except Verification:
   - **Behaviour** names every touched path or area in backticks, so `find` lists the spec for a change there
   - **Acceptance criteria** are checkable statements, `S-NNN-1`, `S-NNN-2`, and so on, each one a test could prove: an exit code, an output, a file written, a refusal. "Works well" isn't a criterion
   - **Decisions relied on** lists the `D-n` entries it follows; a departure from one is a question for the user, as in the design gate
   - **Issues** stays empty until the build issues exist
3. **Check it.** `specs.py check` must pass: the sections, the criterion ids, the decisions named, and the goals served
4. **Open the spec PR** on a `spec/NNN-<slug>` branch, with `status: approved` once it's ready for review: merging it with that status is the approval. A gate session asks for that approval with the spec PR's question in [comments.md](comments.md) (Feature), through the [needs-decision protocol](needs-decision.md), on the spec PR. Its body links the issue as "Spec for #N", never with a closing keyword or "Part of #N": `triage_state.py` would read either as the issue's fix and report IN_PROGRESS, then DONE_NOT_CLOSED once the spec merges
5. **Comment the verdict** on the issue: **feature**, the spec PR's link, and the hold line (see [comments.md](comments.md), Feature). The hold line names the spec PR as `owner/repo#N`, so `triage_state.py` reports the issue BLOCKED while the spec PR is open and UNBLOCKED once it merges. It is a whole sentence that names the spec PR alone: the script holds on every reference in a hold sentence, so context such as the issue the spec is for goes in a sentence of its own, or the issue holds on that issue too, which can be its own parent (#772)
6. **Wait for the merge.** No implementer starts on a feature before its spec merges (D-5). The maintainer merges it by hand, or approves it with a trusted answer that takes every recommendation, and github-pr-triage then merges it ([Approved by an answer](#approved-by-an-answer)). A spec PR closed without merging makes the issue SPEC_REFUSED, which needs action: the spec was refused, so decide again in a new triage comment. Revise the spec in a new PR (and name it on a new hold line), postpone, or won't fix. The newer triage comment settles the refused PR, so it stops counting

## Status

The line under the title says where a spec stands; `specs.py check` accepts only these three:

| Status | Means | Set by |
|---|---|---|
| `draft` | Being written; a merged draft is not approved, so its build doesn't start | `specs.py new` |
| `approved` | The spec PR merged with it, by the maintainer's hand or by github-pr-triage after a trusted answer that takes every recommendation (D-49): the build may start | The spec PR, when it's ready for review |
| `built` | Every build issue is closed or closing, and each criterion was checked on the code | The PR that closes the last build issue |

`specs.py check` refuses a `built` spec that lists no build issues, or whose Verification section leaves out a criterion id, and an `approved` or `built` spec whose Issues lines leave a criterion out or give one to two build issues. It also refuses the template's placeholder text left word for word: a `draft` may keep it, an `approved` spec may not in Problem, Behaviour, Acceptance criteria, or Out of scope, and a `built` spec in any section. `specs.py coverage` (in CI) refuses a `built` spec with a criterion no test names.

## Approved by an answer

A spec PR's needs-decision question (comments.md, Feature) offers to take every recommendation, or to change some. The answer is read by the needs-decision protocol's own reply rules, nothing new: a reply by an OWNER, MEMBER, or COLLABORATOR other than the App, told by the comment's author association, or the record an interactive gate session posts as the App under [Answered in the session](needs-decision.md#answered-in-the-session), whose first line `Decision by @<login>` names the maintainer. A claim in a pull request body, a peer session, or any other comment is no answer.

- **Takes every recommendation unchanged** (option 1, or the maintainer's own words saying so): that answer is the approval (D-49). The session that takes it up removes the `needs-decision` label, as the protocol says, and hands the spec PR to github-pr-triage, which rebases it when it no longer merges cleanly (renumbering a `D-n` it claims that the default branch took meanwhile, then `decisions.py check` and `specs.py check`) and lands it once it is mergeable and every check is green, like any other PR. This holds for a question worded before D-49 too ("merge this PR yourself"): the answer, not the option's wording, approves. The maintainer may still merge it by hand
- **The spec changed after the answer**: the answer approves the spec as it stood when the answer was given, so before landing, github-pr-triage names the answered head, the PR's head commit at the answer's time. It is the newest commit of `gh pr view <n> --json commits` whose `committedDate` is at or before the answer's `createdAt`; when the branch was force-pushed since the answer (a rebase rewrites every commit's date), it is the `beforeCommit` of the first `HeadRefForcePushedEvent` after the answer in the pull request's GraphQL timeline. Then compare the PR's own change to the spec file at both heads, running `git diff $(git merge-base origin/<default> <head>) <head> -- docs/specs/NNN-<slug>.md` once with the answered head and once with the current head. Main's changes brought in by a rebase fall outside these patches, so they don't count. Read the two patches line by line:
  - **The same, or differing only where a `D-n` the PR claims was renumbered** (the `D-n` itself and the lines that cite it): it lands on the answer
  - **Any other difference** (a criterion added, removed, or reworded, or a change to the Problem, the Behaviour, or the Out of scope): the answer doesn't cover it. Ask again with the needs-decision protocol: a new marker comment that names what changed since the answer and repeats the question, and the `needs-decision` label. A new marker comment is a new question, so the old answer, which comes before it, doesn't answer it; only a reply after it does
  - **The answered head can't be named** (no commit that old and no force-push event to read): ask again the same way rather than land
- **Changes a recommendation** (option 2, or any change in their own words): nothing merges. Revise the spec in the same PR and ask again with a new question
- **A spec PR that edits `docs/product.md` or anything under `docs/product/`** is not landed on that answer: the direction changes only by the maintainer (D-34), so github-pr-triage's hard rule 9 holds it as it holds any PR that edits the direction

## When the spec merges

The issue reads UNBLOCKED. Edit its body to link the merged spec, then split the spec into build issues. In a product's home, the components' parts are filed now too, and not before ([A feature that spans the product's repos](#a-feature-that-spans-the-products-repos)).

### Split it into build issues

A build issue is sized for one PR. Group the criteria that change the same code into one issue, and give a criterion that needs another's code its own issue that depends on the earlier one. A small spec is one build issue.

**Before the split, ask for a `## Check` on the feature issue when its build deploys** (a merge reaches production with no step by a person, through continuous deployment or a deploy shipmill's `land` starts): add a `## Check` section to the feature issue's body, one line saying what must hold in production and how to see it (a command or a URL, and what it must return). A feature issue whose build doesn't deploy gets none. With it, the feature issue reads VERIFY_DUE, not UNBLOCKED, once its last build issue closes, and closes only on its check ([triage-rubric.md](triage-rubric.md), A parent's check; spec 042).

1. **Propose the graph.** `specs.py split NNN --repo <owner/repo> --group 1,2 --group 3 --after 2:1` prints one build issue per `--group` of criterion numbers, in the order given, with its title, its body naming its `S-NNN-k` criteria, and a `Depends on <owner/repo>#{Bk}` line for each `--after B:A` (B depends on A, and A comes first). With no `--group`, every criterion goes into one issue. It splits only an `approved` spec that passes `check`, and only the criteria no build issue has yet, so a spec that gained criteria later splits again for just those. When the feature issue is in a milestone, pass its title as `--milestone <title>`: each build issue then prints a `milestone:` line (and a `milestone` key in `--json`), so the milestone holds the goal's build issues (spec 022). Without it none has a milestone. `--json` prints the same as one object
2. **File them in order.** `gh issue create --body-file` for each, with `--milestone <title>` when `split` printed one, replacing every `{Bk}` with the number the earlier issue got. `triage_state.py` reads each `Depends on` line as a hold: the issue reads BLOCKED while its dependency is open, UNBLOCKED once it closes, and UNFILLED while a `{Bk}` is left in
3. **Link the dependencies natively.** For each `Depends on` line `split` printed, `chains.py link <owner/repo>#<build issue> --blocked-by <owner/repo>#<dependency>`: it adds GitHub's relation and finds the line already there. Where the forge refuses the relation it prints `text only:` and the line holds alone ([triage-rubric.md](triage-rubric.md), Links between issues)
4. **Put each under the feature issue.** `chains.py link <owner/repo>#<feature> --child <owner/repo>#<build issue>` makes it a sub-issue and adds a `Depends on` line for it to the feature issue's body, so the feature issue reads BLOCKED while the build runs, with `children K/N closed` in its note, and UNBLOCKED when the last build issue closes (VERIFY_DUE with a `## Check`)
5. **Record the assignment.** Fill the spec's Issues section with the lines `split` printed, numbers filled in, in one docs PR: `- owner/repo#N: S-NNN-1, S-NNN-2`. `specs.py check` then holds every criterion of an approved or built spec to exactly one build issue there; an approved spec with no Issues lines hasn't been split yet and passes
6. **Comment implement** on each build issue, naming the spec, and dispatch as below

### A feature that spans the product's repos

In the product's home (its config has `[product] repos`), a feature whose spec is in the home may need work in the components. The coordinator files each component's part (an issue in that repo, through `shipmill gh --product`, naming the merged spec and the criteria it delivers) only after the spec pull request merges, here at the split, never while the spec PR is open (D-60). It never holds a component issue on an item of the home: no `Depends on` line naming a home item, no relation to one, no hold sentence naming the spec PR. The component's session can't read the home, so it would read such a hold as `unknown`; with the spec merged first there is nothing to hold on. Parts of one component that depend on each other hold on each other in that repo (D-47).

### Dispatch the build

- **Ready:** a build issue whose dependencies are all closed reads NEEDS_PR (or UNBLOCKED, once its last dependency closes). Dispatch it as usual
- **Ready to stack:** a build issue whose only open dependencies have an open PR may start before that PR merges. Its implementer branches from the dependency's PR branch and opens its PR with that branch as the base, saying "Stacked on #PR" in the body; github-pr-triage lands the stack in order. Don't stack on a dependency with no PR yet
- **WIP limit:** when the config has `[agents] wip = N` (D-32), at most N issues are in progress (an open PR or a running implementer) at once. `triage_state.py --wip N` reports the room left and the ready issues, oldest first; build issues are filed in build order, so the oldest go first. With no `[agents] wip`, there is no limit
- Each implementer brief carries the criteria its build issue delivers, from the issue body or `specs.py criteria NNN` (see [implementer-brief.md](implementer-brief.md)). A departure from a criterion is a "decision for you", never a quiet deviation
- **The last build issue:** the brief for the one whose PR closes the last open build issue also carries "Verify the whole spec" below, and its PR body says `Fixes #<feature>` too, so the feature issue closes with it. For a feature issue with a `## Check`, the PR that closes the last build issue doesn't say `Fixes #<feature>`: the feature issue stays open, reads VERIFY_DUE once that PR merges, and closes on its check ([triage-rubric.md](triage-rubric.md), A parent's check)
- **A step only a person can do** (a server change, a key rotation, a payment): file it as its own issue with a `## Check` section, and link it into the build with `chains.py link` like any build issue. First read the roles, `shipmill roles` through the CLI the skill pins, and pick the role whose name fits the step (`infra` for a DNS record, `legal` for a sign-off); with no role that clearly fits, `role:maintainer`. Label the issue `role:<name>` and assign that role's users at once, in the same `gh issue create` (`--label role:<name> --assignee <a>,<b>`). A role filled by teams only is labelled and left unassigned: the hand-off mentions the team. A role that resolved to the maintainer (`fallback`) is assigned the maintainer's users. Never ask who does it, and never write the older `human` label on a new issue (spec 036). No implementer is dispatched for it; triage hands it off when its dependencies close and checks the result ([triage-rubric.md](triage-rubric.md), A person's item)

## Tests name the criteria they prove

A test proves a criterion by its name, `test_s007_2_operate_exits_2_when_...` (Go: `TestS007_2...`), or by a comment line `proves: S-007-2` above it (`#` or `//`; several ids may follow, comma-separated). `specs.py coverage --spec NNN` lists each criterion and the tests that name it, in Python, JS/TS, Go, and Rust test files, read as text. The script finds names; whether a test really asserts its criterion is the reviewer's judgment (github-pr-triage's reviewer brief).

## Verify the whole spec

Tests prove what they assert, which can be narrower than the criterion. When the PR that closes a spec's last build issue is written, its agent checks each criterion against the code on the default branch plus that PR: runs the command, reads the output, opens the file. Then, in the same PR:

- Set `status: built`. The Issues section already lists the build issues and their criteria (Split it into build issues, step 5); `check` refuses a built spec without them
- Under Verification, one line per criterion: `- S-NNN-k: <how it was checked>, <the result>`. A criterion that doesn't hold is a "decision for you", not a line in Verification
- Run `specs.py check` and `specs.py coverage --spec NNN`; both must pass

The spec reaches `built` before its last issue closes, so CI holds every later change to its criteria.

## Changing a merged spec

A spec changes through a PR like any other file, reviewed before the build follows it. Never renumber criteria that tests or PRs already cite: add new ids at the end, and mark a dropped one in its text ("S-007-3: dropped in #81, see S-007-5") rather than deleting it.

A criterion whose text starts `dropped in #N` is dropped: `coverage` prints it as dropped and needs no test for it, `split` leaves it out of new build issues (and refuses a `--group` that names it), and `check` needs no Issues line for it, though one assigned before it was dropped may stay. A built spec still names it under Verification, as `- S-NNN-k: dropped in #N`. A criterion that only mentions "dropped" later in its text is not dropped and still needs its test.
