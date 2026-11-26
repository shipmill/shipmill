# shipmill

## Mission

Coding agents can write a fix; getting it to users is the rest of the work. shipmill runs
that rest on a repository: agents triage the issues, fix them, and land the pull requests,
and release lanes cut, publish, and announce releases by a policy the maintainer writes.
The maintainer keeps the decisions that are theirs (what the product is for, which
features to build, what may ship) and the loop does everything else, toward the goals
below.

## Users

- U-1: A maintainer of a library or product repository who wants agents to deliver its work while keeping the decisions
- U-2: A founder or small team running several repositories who needs one view of what waits on them
- U-3: The person who filed an issue, who wants to find where the fix is available
- U-4: The agents themselves, which read this repository's skills, rules, and direction to work without a person in the session

## Goals

- G-1: Held: a connected repository goes from a new issue to an announced release with no human step but the maintainer's decisions. Threshold: its measure line. Source: ship-watch's weekly metrics
  measure: issue_to_release_p90 < 2d
- G-2: Held: agents' work holds a quality bar the maintainer can trust without reading every diff. Threshold: its measure line. Source: ship-watch's weekly metrics
  measure: change_failure_rate <= 5%
- G-3: The person who asked for a change can find where it is available; the core reports which release fixed an issue and doesn't promise to tell them (D-69). Check: `status --item` on a closed issue names the release that carries its fix. By: 2026-12-31
- G-4: The maintainer sees in one place what waits on them, across all their repositories. Check: `queue --fleet` lists every item a waiting-on-me round finds, none missing. By: 2026-12-31
- G-5: Held: agents keep to the written direction: work outside the goals is postponed or declined with its reason. Threshold: every merged pull request and every filed issue names the goal or quality-bar item it serves. Source: the plan check at landing and the triage verdicts
- G-6: Agents pursue a goal: they propose the work that reaches it, and the maintainer approves it. Check: #1680 to #1683 and #1688 are closed, and `status --item` on a goal names its state. By: 2026-12-31
- G-7: The loop knows whether each goal is met and each measure held, and proposes changing the direction when it is. Check: the weekly round reads every measure and every goal's check, and proposes the change. By: 2026-12-31
- G-8: Each person's profile credits the work they decided, and the record still tells their words from their agents'. Check: a decision the App relayed shows on the person's profile, and the record tells their words from the agent's. By: 2027-03-31

## Non-goals

- N-1: Executing a rollout: staged rollout, traffic shifting, and deploys to customers belong to the platform; shipmill decides and verifies (D-31)
- N-2: A server or state of its own: the forge holds the state, in issues, labels, pull requests, tags, and deployments
- N-3: Making the maintainer's decisions: accepting an opportunity, approving the spec of work not yet accepted, or changing this direction
- N-4: The software lifecycle outside the delivery loop for now: strategy, discovery, operations and SLOs, support, deprecation
- N-5: A coding agent or model of its own: shipmill directs an existing agent

## Quality bar

- Q-1: Fail fast: a malformed config or an unexpected state stops with exit 2 and a message naming the fix, never a guess
- Q-2: Every write an agent makes is attributed to the App, never to a person (D-14)
- Q-3: A release ships only code whose CI passed on the exact release commit, and a breaking change reaches a stable release only after the maintainer's decision
- Q-4: Every acceptance criterion of a spec has a test that names it
- Q-5: A change honours the settled rules in `docs/decisions.md`, or records a superseding entry the maintainer approved
- Q-6: The release side works without the agents
