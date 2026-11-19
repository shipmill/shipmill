# S-084: A deploy is verified against the previous release's answers

status: approved
serves: G-2

## Problem

After a deploy, `shipmill operate` reads one health URL. A release can answer that URL with
a 2xx and its own version and still answer the service's real requests differently from the
release before it: half the items, a field gone, a 404 where a page was. Nobody learns until
a user does, and with agents shipping to production without a person watching, that user is
the first reviewer of the change (#1307, which the maintainer accepted on 2026-11-18).

It hits maintainers of web services whose agents land and deploy on their own (G-2: a
quality bar the maintainer can trust without reading every diff). No user has asked for it
yet; the prior art is the Earned Autonomy entry in GitLab's Transcend hackathon, which after
each release replays requests against the new and the previous Cloud Run revision on the
same data and rolls back on any difference: in one run it saw 50 items instead of 100 and
moved traffic back in 3.3 seconds.

This spec keeps D-31 as it is: shipmill sends the requests, compares, records, and decides;
the rollback is the environment's own deploy workflow on the previous tag, as for a failed
health check. It records no traffic and stores nothing outside GitHub (N-2): the project
declares a fixed set of probe requests in its config, and the result is a deployment status.

## Behaviour

### The probes

An environment in `[environments]` of `.github/shipmill.toml` (D-4) may declare probes, an
array of tables parsed in `src/shipmill/environments.py`:

```toml
[[environments.production.probes]]
name = "items"                       # letters, digits, '.', '_', '-'; unique in the environment
path = "/api/items?limit=100"        # starts with '/'; may hold a query
ignore = ["/generated_at", "/items/*/updated_at"]   # JSON pointers; '*' matches any one segment
```

`name` and `path` are required, `ignore` defaults to none. Any other key, a duplicate name,
a path that doesn't start with `/` or holds whitespace, a pointer that doesn't start with
`/`, or more than 20 probes in one environment exits 2 naming the table and the key, as the
other keys of `[environments]` do. An environment without probes behaves exactly as today:
no compare, and no request beyond its health check (D-63).

A probe is a `GET` with no body, no cookie, and no credential, with the `User-Agent`
`shipmill-operate`, through the `Http` protocol of `src/shipmill/operate.py` and its
10-second timeout; the answer is read up to 1 MiB. Probes are for idempotent, public reads:
shipmill never sends another method.

### Where each release answers

The deploy workflow says where a release answers: GitHub Actions writes a job's
`environment: { name, url }` as the deployment status's `environment_url`. `DeploymentStatus`
in `src/shipmill/github.py` gains `environment_url`, read from the statuses endpoint
`deployment_statuses` already calls, and a deployment's address is the newest non-empty
`environment_url` among its statuses. The platform keeps the previous release addressable
(a Cloud Run revision tag, a Vercel deployment URL); shipmill never redeploys it to compare
(D-31).

The **new release** is the environment's current deployment (`Observed.current`); the
**previous release** is the deployment `_last_good` finds today: the newest earlier one, on
another tag, that reached success there and whose last check didn't fail. A probe's URL is
the address with the probe's `path` appended.

### When a deployment is compared

An operate run compares an environment's current deployment once, when all of these hold:

- the environment declares probes
- its current deployment passed its latest health check this run, or the environment has no
  `health`
- the deployment carries no status whose description starts with `shipmill compare:`
- a previous release exists and its tag is lower than the current one, so a rollback's
  deployment is never compared against the release it replaced

When both addresses are known, it compares. Otherwise, or when the previous release's
address answers no probe at all, the environment's report says `not compared: <reason>`
(`no previous release`, `<tag> has no environment_url`, `<tag> at <address> unreachable`),
writes no status, opens no incident, and the next run tries again; promotion and rollback
follow health alone, as today.

### The comparison

For each probe, shipmill sends it to the previous release twice and to the new release
once. Two answers are the same when their HTTP statuses are equal and:

- both bodies parse as JSON: the values are equal after removing every `ignore` pointer and
  every pointer at which the previous release's two answers differ (noise the previous
  release makes by itself, such as a timestamp or a request id)
- otherwise: the bodies are identical text. A probe whose two previous answers differ as
  text is reported `unstable` and counts neither way

A probe that differs is sent once more to both releases, and only a difference that holds on
both sendings counts. The new release giving no HTTP answer to a probe the previous one
answered is a difference; the previous one giving no answer to one probe makes that probe
`unchecked`.

### What a difference means

Differences a change meant to make are explained by its pull request. The pull requests of
a release are those merged between the previous tag and the new one: the first-parent
commits of `git log <previous>..<new>` in operate's checkout (`src/shipmill/gitrepo.py`),
each named by its subject, `<title> (#N)` for a squash and `Merge pull request #N` for a
merge commit (D-96). Their bodies are read only when a difference holds, through the issues
endpoint (`GET /repos/{owner}/{repo}/issues/{N}`), which serves a pull request's body under
the `issues` permission operate already has. A line of a body

```markdown
Changes answers: items, orders
```

explains a difference on each probe it names. A read that fails stops the run with the
error (Q-1), writing nothing for that environment.

The outcome is one deployment status on the current deployment, written with
`auto_inactive=false` as operate's other statuses are:

| Outcome | State | Description |
|---|---|---|
| Every counted probe the same | `success` | `shipmill compare: same answers as <previous tag> on <n> probes` |
| Every difference explained | `success` | `shipmill compare: differs from <previous tag> on <names>, explained by #N` |
| A difference unexplained | `failure` | `shipmill compare: answers differ from <previous tag> on <names>` |

A `shipmill compare:` status is not a health status: `observe()` doesn't count it among the
failed checks in a row, and it doesn't restart a bake. A deployment carrying a `failure`
compare status is not healthy for promotion: an environment promoted `from` it reports
`<source> answers differently on <tag>` and waits, and `_last_good` skips it as a rollback
target.

### The incident and the rollback

An unexplained difference opens the environment's incident for that tag at once, without
waiting for `[operate] rollback_after`, through the same `_incident` path and the same
`incident_label`. One incident per environment and bad tag stays the rule: a compare
failure on a tag whose incident is already open comments on it. The incident's hidden line
gains an optional field, `cause=compare`; a line without it reads as a health incident, so
incidents opened before this build keep parsing. Its title is
`Incident: <env> answers differently on <tag> than <previous tag>`, and its body lists, for
each differing probe, its name, its path without the query, both HTTP statuses, and at most
ten JSON pointers that differ, with an array's length on each side where the pointer names
an array (`/items: 100 vs 50 items`). It quotes no value of either answer: an incident is an
issue anyone with read access sees.

The rollback is `_rollback`'s, under `[autonomy] rollback` and the hold, unchanged: `act`
starts the environment's workflow on the previous tag, `propose` (or `act` under a
`shipmill-hold` issue, D-8) has the incident say so and `--approve-rollback <env>` starts
it once, `observe` only says so. A compare incident reads healthy again only once the
environment runs a tag other than the bad one and passes its health check, never while it
still runs the bad tag.

### Reports and docs

`summary()` adds the compare outcome to the environment's action: `compared with <tag>:
same on <n> probes`, `... differs on <names>, explained by #N`, `... differs on <names>`, or
`not compared: <reason>`, with `unstable` and `unchecked` probes named. `shipmill operate
--dry-run` sends the probes and reports what it would write, and writes nothing.

`docs/release-lanes.md` (Environments; Operate) documents the probes, the
`environment: { name, url }` the deploy workflow sets, the `Changes answers:` line, and what
a difference does; `skills/github-issue-resolve/SKILL.md` tells an implementer whose change
alters an answer a probe covers to add the `Changes answers:` line to the pull request's
body.

Touched areas: `src/shipmill/environments.py` (`[environments.<name>.probes]`),
`src/shipmill/operate.py` (compare, incident, promotion, `_last_good`, summary),
`src/shipmill/github.py` (`DeploymentStatus.environment_url`, a pull request's body),
`src/shipmill/gitrepo.py`, `docs/release-lanes.md`, `skills/github-issue-resolve/SKILL.md`,
`shipmill operate`, and `tests/test_operate.py`, `tests/test_environments.py`.

## Acceptance criteria

- S-084-1: a config with `[[environments.<name>.probes]]` tables holding `name`, `path`, and `ignore` loads; an unknown key, a duplicate name, a path not starting with `/`, an `ignore` pointer not starting with `/`, or a 21st probe exits 2 naming the table and the key; an environment with no probes makes no request beyond its health check and its report carries no compare text
- S-084-2: `DeploymentStatus` carries `environment_url`, and a deployment's address is the newest non-empty one among its statuses; a current or previous deployment with none reports `not compared: <tag> has no environment_url`, and a previous address that answers no probe reports `not compared: <tag> at <address> unreachable`; either writes no status and opens no incident, and the next run tries again
- S-084-3: each probe is sent as a `GET` with no body and no credential, twice to the previous release's address and once to the new one; two JSON answers with equal statuses that differ only at an `ignore` pointer, or at a pointer where the previous release's two answers differ, read the same; non-JSON answers read the same only when identical, and a non-JSON probe whose two previous answers differ is reported `unstable` and not counted
- S-084-4: a probe that differs is sent once more to both releases, and a difference that doesn't hold on the second sending isn't counted; a probe the new release gives no HTTP answer to while the previous one answers counts as a difference
- S-084-5: a deployment whose counted probes all read the same gets one `success` status `shipmill compare: same answers as <previous tag> on <n> probes`, and a later run sends no probe for that deployment
- S-084-6: when every difference is on a probe named by a `Changes answers:` line in the body of a pull request whose number a first-parent commit subject between the two tags names (`(#N)` or `Merge pull request #N`), the deployment gets a `success` status naming the probes and the pull request, and no incident opens; those bodies are read only when a difference holds, and a failed read exits non-zero writing nothing for that environment
- S-084-7: an unexplained difference writes one `failure` status `shipmill compare: answers differ from <previous tag> on <names>`; that status leaves the count of failed health checks in a row and the bake start as they were, an environment promoted `from` that deployment reports `<source> answers differently on <tag>` and doesn't deploy it, and `_last_good` doesn't return its tag
- S-084-8: an unexplained difference opens the incident at once, before `rollback_after` failed checks, titled `Incident: <env> answers differently on <tag> than <previous tag>`, its hidden line carrying `cause=compare`; its body names each differing probe, its path without the query, both statuses, at most ten differing pointers, and an array's lengths, and holds no value from either answer; an incident line without `cause=` still parses as a health incident
- S-084-9: the rollback a compare incident starts follows `[autonomy] rollback`: `act` dispatches the environment's workflow on the previous tag once, `propose` or `act` under an open `shipmill-hold` issue records it as proposed so `--approve-rollback <env>` starts it once, and `observe` dispatches nothing; a compare failure on a tag whose incident is already open comments on it instead of opening another
- S-084-10: a compare incident is not commented healthy again while the environment still runs the bad tag and passes its health check; it is once the environment runs another tag that passes
- S-084-11: a current deployment whose tag is not newer than the previous release's (a rollback), one already carrying a `shipmill compare:` status, or one whose latest health check failed this run is not compared and receives no probe request
- S-084-12: `shipmill operate --dry-run` with probes declared reports the outcome it would write (`would mark` the compare status, `would open an incident`, the rollback it would start) and creates no status, issue, comment, or workflow run; the summary's action names the compare outcome, and the `unstable` and `unchecked` probes
- S-084-13: `docs/release-lanes.md` documents `[[environments.<name>.probes]]`, the deploy job's `environment: { name, url }`, the `Changes answers:` line, and that an unexplained difference opens an incident and rolls back under `[autonomy] rollback`; `skills/github-issue-resolve/SKILL.md` tells the implementer to add a `Changes answers:` line when the change alters an answer a declared probe covers

## Out of scope

- Recording or replaying live traffic: shipmill stores no requests or answers, and the probe set is the project's own declaration (N-2, N-4). A layer outside the core may generate the probe list from recorded traffic and write it to the config
- Methods other than `GET`, request bodies, and credentials or headers on a probe: a probe that needs a secret or writes data can be its own request, once there is a safe way to hand a secret to operate
- Shifting traffic, holding a canary, or keeping the previous release addressable: the platform's (D-31, N-1). An environment whose platform retires the previous release gets `not compared` and health alone
- Comparing more than once per deployment, or comparing over a bake: a release is compared once, against the release it replaced, at its first passing health check
- Comparing against an environment's `from` source rather than its own previous release
- `pr_gate.py` checking that a `Changes answers:` line names declared probes, and the reviewer's rubric for it: the reviewer reads it like any line of the body; a check can be its own request
- `shipmill doctor` warning about an environment with probes whose deploy workflow sets no `environment: url`: the run's `not compared` report names it; a doctor row can be its own request
- Counting compare rollbacks in `metrics.py`'s change failure rate apart from health rollbacks

## Decisions relied on

- D-4
- D-6
- D-8
- D-31
- D-63
- D-96

## Issues

## Verification
