# S-049: Credit the decider

status: built
serves: G-1

## Problem

Once agents land a repo's work through its GitHub App, the maintainer's contribution graph
stops showing it (#783). GitHub credits a commit to the account whose verified email is its
author or a `Co-authored-by` trailer, and a squash merge of an App pull request is authored
by `shipmill-<owner>[bot]`. It carries the maintainer as co-author only when one of their own
commits happened to be in the branch: across 11 repos with `[agents] app_id`, over the 90
days to 2026-10-28, about 330 of about 780 App-authored commits on default branches did, from
61 of 64 in one repo to 2 of 85 in another. Nothing in shipmill writes that trailer on
purpose, and the gate merges without a review, so the maintainer's decision to land a change
leaves no trace on their profile.

For a maintainer whose profile is a public record of their work, the graph thins out while
their output grows, which is a reason to hold back from turning agents on. In the
maintainer's words (2026-10-28): the App's contributions are technically mine.

`Co-authored-by` reads as "wrote this together", so the credit names only a person a record
shows decided the change, never a guess, and it is off unless the repo turns it on.

## Behaviour

### The setting

`[agents] credit` in `.github/shipmill.toml`, read by `src/shipmill/config.py`:

```toml
[agents]
app_id = 123456
credit = "decider"   # or "off", the default
```

Any other value fails the config load with exit 2, naming the key and the two values. With
`credit = "off"` or no key, nothing below happens and every merge is written exactly as
today.

### The merge

With `credit = "decider"`, `shipmill gh pr merge` (`src/shipmill/app_gh.py`, spec 012) finds
the pull request's deciders before it runs gh. When it finds none, gh gets its arguments
unchanged, as today. When it finds some, gh gets the same arguments plus one `--body` that
replaces any `--body` or `--body-file` given: the commit message body the merge would have
had, followed by one trailer per decider:

```text
Co-authored-by: <name> <<id>+<login>@users.noreply.github.com>
```

`<name>` is the account's profile name, or its login when the profile has none; `<id>` and
`<login>` are the account's, read from `GET /users/<login>`. GitHub credits a commit to its
noreply address, so the trailer needs no email of the person's own.

The body the merge would have had is:

- The body given by `--body` or `--body-file`, when one was given
- Otherwise the body GitHub writes by default for the repo's `squash_merge_commit_message`
  (a squash) or `merge_commit_message` (a merge commit) setting, read from
  `GET /repos/<owner>/<repo>`: the pull request's body for `PR_BODY`, the messages of its
  commits for `COMMIT_MESSAGES` (each as `* <message>`, in commit order, when there are
  several; the one message's body when there is one), and nothing for `BLANK` or `PR_TITLE`.
  To it go the `Co-authored-by` trailers GitHub adds by default: one per distinct author of the
  pull request's commits other than the pull request's author, with the name and email the
  commit gives

A decider whose email is already in a `Co-authored-by` trailer of that body, compared without
case, gets no second one. `--subject` and every other flag go to gh unchanged.

Before gh runs, one stderr line per decider names their login, in a code span (D-61), and the
record that made them one, such as ``credit: `@octocat` approved the pull request``.

### Who is a decider

A trusted person is an account whose author association on the record is `OWNER`, `MEMBER`,
or `COLLABORATOR`, or, for a label event, whose permission on the repo is `write`,
`maintain`, or `admin`; never a bot, never the App, and never the pull request's author,
whom the commit already credits. The deciders are the trusted people any of these records
name, in this order, each person once:

1. **An approver:** a person whose latest review on the pull request is `APPROVED`
2. **An answerer:** the author of a trusted answer to a needs-decision question on the pull
   request, on an issue it closes, or on that issue's parent, by the reply rules of the needs-decision protocol
   (`skills/github-issue-triage/references/needs-decision.md`): a reply after the question's
   marker comment, or a comment the App posted whose first line is `Decision by @<login>` or
   ``Decision by `@<login>` ``, which names `<login>`
3. **An issue's author:** the author of an issue the pull request closes (GitHub's closing
   references), or of that issue's parent issue (GitHub's sub-issue parent), since the filing
   is the decision
4. **An accepter:** the person who added the `planned` label to an `opportunity` issue the
   pull request closes, or to that issue's parent

A pull request no such record names gets no trailer: a release bot's commit, or a change an
agent filed and landed with no person's decision, is written as today.

### Merges that skip the credit

With `credit = "decider"`, `shipmill gh api -X PUT repos/<owner>/<repo>/pulls/<n>/merge`
exits 2 before gh runs, naming the `shipmill gh pr merge <n> --squash` command to run
instead, so no merge through shipmill leaves the credit out. A rebase merge stays refused, as
spec 026 has it.

### Doctor and the docs

`shipmill doctor` (`src/shipmill/doctor.py`) prints a `credit` row: `credit: decider, a
merge names who decided it in Co-authored-by (spec 049)` when on, `credit: off` otherwise.
The shipmill-setup skill (`skills/shipmill-setup/SKILL.md`, the `[agents]` keys) and
`docs/flow.md` name the key, say it is off by default, and say what the trailer means: the
person decided the change, which is not a claim they wrote it.

## Acceptance criteria

- S-049-1: A config whose `[agents] credit` is neither `"decider"` nor `"off"` fails to load with exit 2, naming the key and both values; with no key, credit reads as off
- S-049-2: With credit off, `shipmill gh pr merge` hands gh its arguments unchanged and reads no review, comment, issue, or label of the pull request
- S-049-3: With credit on, a pull request whose latest review by a trusted person is `APPROVED` is merged with a `--body` ending in `Co-authored-by: <name> <<id>+<login>@users.noreply.github.com>` for that person, `<name>` the profile name or the login when the profile has none
- S-049-4: With credit on, the author of a trusted answer to a needs-decision question on the pull request, on an issue it closes, or on that issue's parent, and the login named by an App comment starting `Decision by @<login>` or ``Decision by `@<login>` ``, each get the trailer; a reply from an untrusted account, or a comment before the question's marker, gives none
- S-049-5: With credit on, the trusted author of an issue the pull request closes, or of that issue's parent issue, gets the trailer
- S-049-6: With credit on, the person with write, maintain, or admin permission who added `planned` to an `opportunity` issue the pull request closes, or to that issue's parent, gets the trailer
- S-049-7: With credit on, bots, the App, untrusted accounts, and the pull request's author never get the trailer, each person gets at most one, and a pull request no record names is merged with its arguments unchanged
- S-049-8: With credit on, the body before the trailers is the given `--body` or `--body-file` when one was given, else GitHub's default body for the repo's merge message setting (`PR_BODY`, `COMMIT_MESSAGES`, `BLANK`, `PR_TITLE`) with GitHub's default co-author trailers for the other commit authors; a decider already named by email in a trailer there gets none, and `--subject` reaches gh unchanged
- S-049-9: With credit on, `shipmill gh` prints one stderr line per decider naming the login in a code span and the record that made them one, before gh runs
- S-049-10: With credit on, `shipmill gh api -X PUT repos/<owner>/<repo>/pulls/<n>/merge` exits 2 without running gh, naming `shipmill gh pr merge <n> --squash`
- S-049-11: `shipmill doctor` prints a `credit` row that says `decider` with spec 049 when the key is on and `off` otherwise
- S-049-12: The shipmill-setup skill and `docs/flow.md` name `[agents] credit`, its default, and that the trailer means the person decided the change, not that they wrote it

## Out of scope

- An option for the gate to wait for the maintainer's approving review before it merges (#783's alternative): a review GitHub credits by itself, at the cost of a slower loop; a separate opportunity if wanted
- Following a chain further than one parent issue (a build issue's spec pull request and whoever approved it): a build issue under an accepted opportunity reaches its accepter through its parent, which covers the spec gate's flow
- Rewriting commits already on the default branch
- Merges made outside `shipmill gh` (by hand in GitHub's UI, or by a plain `gh` without the App): those are the person's own

## Decisions relied on

- D-14
- D-33
- D-49
- D-61

## Issues

- shipmill/shipmill#785: S-049-1, S-049-2, S-049-3, S-049-7, S-049-8, S-049-9, S-049-10
- shipmill/shipmill#786: S-049-4, S-049-5, S-049-6
- shipmill/shipmill#787: S-049-11, S-049-12

## Verification

Checked on main at e6f729a (#789 and #790 merged): `tests/test_credit.py` and `tests/test_credit_doctor_docs.py` pass (115 tests), and `specs.py coverage --spec 049` lists a test for every criterion.

- S-049-1: `agents.py` reads `credit` as the `Credit` enum, off without the key; the tests load another value and a non-string, each exit 2 naming the key and both values, and an absent key as off
- S-049-2: this repo sets no `credit`, and #789 and #790 merged through `shipmill gh pr merge` with GitHub's own body and trailers; the test asserts gh gets its arguments unchanged and the fake reads no record
- S-049-3: `credit.approvers` takes each person's latest review that isn't a comment; the tests merge end to end and read the trailer with the profile name, or the login without one
- S-049-4: `credit.answers` reads a question by the marker on its first line from the App or a trusted person, and trusted replies after it, on the pull request, its closed issues, and their parents; the App's `Decision by` line names a login bare or in a code span, and since #790's review never the first part of `@bot[bot]`, `@org/team`, or `@a.b`
- S-049-5: `credit.authors` names the trusted author of each closed issue and its parent, skipping another repo's issues; a cut or malformed GraphQL answer exits 2
- S-049-6: `credit.accepters` names who last added `planned` to an `opportunity` issue, trusted by write, maintain, or admin permission; the tests give none for a reader or for an issue that isn't an accepted opportunity
- S-049-7: `credit.deciders` drops bots, the App's login, and the author, and keeps the first source to name a person; `SOURCES` runs approvers, answerers, authors, accepters, the spec's order
- S-049-8: the tests merge with `--body`, `--body-file`, stdin, and each merge message setting; a decider already named by email gets no second trailer, and `--subject` reaches gh unchanged
- S-049-9: the test reads one stderr line per decider, its login in a code span and its record, before gh runs
- S-049-10: the test runs `shipmill gh api -X PUT repos/<owner>/<repo>/pulls/<n>/merge` with credit on: exit 2 naming `shipmill gh pr merge <n> --squash`, gh not run
- S-049-11: `shipmill doctor` in this repo prints `PASS credit: off`; the tests read `decider, a merge names who decided it in Co-authored-by (spec 049)` with the key on, and no row without `[agents]`
- S-049-12: `skills/shipmill-setup/SKILL.md` and `docs/flow.md` name `[agents] credit = "decider"`, its `"off"` default, and that the trailer means the person decided the change, not that they wrote it
