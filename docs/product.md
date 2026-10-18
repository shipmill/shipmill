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
- U-3: The person who filed an issue, who wants to know where the fix is and to try it first
- U-4: The agents themselves, which read this repository's skills, rules, and direction to work without a person in the session

## Goals

- G-1: A connected repository goes from a new issue to an announced release with no human step but the maintainer's decisions
- G-2: Agents' work holds a quality bar the maintainer can trust without reading every diff
- G-3: The person who asked for a change hears where it is available at each stage and can confirm it works
- G-4: The maintainer sees in one place what waits on them, across all their repositories
- G-5: Agents work toward the product's written direction, and a release can be planned around a goal

## Non-goals

- N-1: Executing a rollout: staged rollout, traffic shifting, and deploys to customers belong to the platform; shipmill decides and verifies (D-31)
- N-2: A server or state of its own: the forge holds the state, in issues, labels, pull requests, tags, and deployments
- N-3: Making the maintainer's decisions: accepting an opportunity, approving a spec, or changing this direction
- N-4: The software lifecycle outside the delivery loop for now: strategy, discovery, operations and SLOs, support, deprecation
- N-5: A coding agent or model of its own: shipmill directs an existing agent

## Quality bar

- Q-1: Fail fast: a malformed config or an unexpected state stops with exit 2 and a message naming the fix, never a guess
- Q-2: Every write an agent makes is attributed to the App, never to a person (D-14)
- Q-3: A release ships only code whose CI passed on the exact release commit, and a stable release ships what a pre-release already carried
- Q-4: Every acceptance criterion of a spec has a test that names it
- Q-5: A change honours the settled rules in `docs/decisions.md`, or records a superseding entry the maintainer approved
- Q-6: The release side works without the agents
