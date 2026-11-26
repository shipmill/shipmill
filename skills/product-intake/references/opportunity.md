# Opportunity issues and intake comments

Write each body to a file in the repo's `tmp/` and post it with `--body-file`: backticks inside a double-quoted zsh `--body` run as commands. Follow the user's writing rules: no trailing periods on list items, em dashes only rarely.

## The opportunity issue

Title: the outcome the users want, in their words, as a short phrase ("Open reports in a spreadsheet"), never a solution unless every request names the same one.

```markdown
Serves: {G-n}

## Problem

{What the users can't do today, quoting the requests: "{quote}" (#{n}).}

## Who is affected

{The kinds of users the requests come from, and how often they meet the problem, as far as the requests say.}

## Evidence

- #{n} {request title}, +1 {count}
- https://github.com/{owner}/{repo}/discussions/{n} {discussion title}, +1 {count}

{N} requests, +1 {total} as of {date}.

## Success

{What a user can do once this ships, checkable: "a report opens in a spreadsheet with one column per field".}

## Notes

{Solutions the requests propose, the D-n rules it runs into, related opportunities. Optional.}
```

The first line names the goal of the direction the outcome serves (SKILL.md, rule 8): `Serves: G-n`, several as `Serves: G-2, G-3`, or `Serves no goal`, followed by `; hits N-n: {the non-goal's words}` when it hits a non-goal. In a component (`[product] home`), a non-goal of the product, one `shipmill product show` prints under `## Product non-goals (<owner/home>)`, is named the same way with its home, `; hits <owner/home> N-n: {the non-goal's words}` (spec 071), and the opportunity is never proposed for acceptance on demand: the triage line below names it in place of `N-n` and recommends declining it, citing `<owner/home> N-n`. While `shipmill product show` exits 2 on the home's direction, open and update no opportunity (SKILL.md, step 1). A repo without `docs/product.md` leaves the line out.

`intake_state.py` reads members only from the Evidence section, so link every request there and nowhere else counts. Other sections may link issues freely.

```bash
gh issue create -R {owner/repo} --title "{outcome}" --label opportunity --body-file tmp/opportunity-{slug}.md
```

## Intake's triage line on the opportunity

```markdown
Triage: **opportunity**.{ Serves: G-n.} {N} requests ask for this outcome; it waits for the maintainer's call: accept with the `planned` label, or decline by closing it as not planned with the reason in a comment. For a class of service other than standard, accept with `planned` and add `expedite`, or `fixed-date` with a due date on the milestone it is in. Once accepted, it goes through the spec gate as a feature.
```

The class of service is the maintainer's choice (spec 070): only a label a person adds counts, so never add `expedite` or `fixed-date` yourself, and never copy one onto a build issue.

For an opportunity that serves no goal, the accept question says so instead of `{ Serves: G-n.}`, and demand alone never makes it a candidate:

```markdown
Triage: **opportunity**. Serves no goal{; hits N-n: "{the non-goal's words}"}. {N} requests ask for this outcome, but demand alone doesn't make it a candidate: it serves no goal of the direction. It waits for the maintainer's call: add the goal it would need, such as "{a goal in the direction's words}", to `docs/product.md` and then accept it with the `planned` label (adding `expedite` or `fixed-date` for a class other than standard), or decline it by closing it as not planned with the reason in a comment{; one that hits N-n is recommended for decline}.
```

A repo without `docs/product.md` leaves `{ Serves: G-n.}` out and uses the first template only. Never use the word "implement" here: `triage_state.py` reads the newest triage comment's verdict from it.

## On each grouped request

```markdown
Triage: **opportunity**: grouped into #{opportunity} with {N-1} other requests for the same outcome. Follow that issue for the maintainer's decision{; this one is a pure duplicate, so it carries the `duplicate` label}.
```

## On a request for a declined outcome

```markdown
Triage: **opportunity**: this asks for the same outcome as #{opportunity}, which was declined: "{the recorded reason}". It is linked there as further evidence; the maintainer reopens #{opportunity} if the decision changes.
```

Quote the reason without an issue number right after a hold phrase ("waits on #40", "blocked by #40"): `triage_state.py` would read the request as BLOCKED on it. Write "#40 has to land first" instead.

## On a request whose outcome shipped

```markdown
Triage: **opportunity**: this outcome shipped through #{opportunity}{, released in {version}}. If something is still missing, say what, and it will be grouped as a new request.
```

## On a request held at the limit

With `[agents] outcomes` and no room (SKILL.md, step 3, spec 101), a request that would start a new outcome gets this comment instead of an opportunity, posted through `shipmill gh`, which adds the agent marker `intake_state.py` reads it by:

```markdown
<!-- shipmill:intake-held -->
This asks for a new outcome, and it waits for room: {K} of {N} outcomes are in flight under `[agents] outcomes`, the most this product carries at once. Once one of them closes, held requests are proposed in the order they were held, this one among them. The maintainer can have it proposed now by replying `propose`.
```

The first line is the held marker and nothing else. It starts with no `Triage:` marker, so the request's triage verdict stays triage's hand-off, and it never holds the word "implement". Post it once per request: one that already reads HELD gets no second comment.
