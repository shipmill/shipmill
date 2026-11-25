# S-090: A session writes its progress on an item by editing one status comment

status: built
serves: G-4

## Problem

Once a needs-decision question mentions the maintainer on an issue or a pull request, GitHub
subscribes them to the thread with the reason `mention`, and every later comment there emails
them, whether or not it mentions them itself. Writing a login in a code span (D-61) stops a
comment's own mention, not these emails. A session that works through several steps on one
item posts a comment per step ("the fix is in #N", "replaced by #M", "rebased, CI pending"),
so the maintainer hears of every step of work that no longer waits on them. Editing a
comment sends no notification (shipmill/shipmill#1508, split from #771).

The scripts read the thread by its comments: `triage_state.py` finds the newest `Triage:`
verdict, the hold sentences, the question and its reply, and the dated markers by their
position in the thread and their `createdAt`. Which posts can become edits is settled by what
those readers key on.

## Behaviour

### What the readers key on today

Every reader reads an item's comments oldest first, in GitHub's order, which is the order
they were created, and dates a comment by its `createdAt`; none reads `updatedAt` or
`lastEditedAt` of a comment. An edit keeps a comment's position and its `createdAt`.

- **Position:** `classify_open` in `skills/github-issue-triage/scripts/triage_state.py`
  takes the newest triage comment by index (`verdict`), and compares a relay's index with it
  (`relay[0] > verdict`, DECIDED), a hold's index with it (`hold_refs`: a refused spec PR named
  before the verdict holds nothing), and `question`, `replies`, `waits_on_decision`,
  `relayed_after`, and `unhandled_veto` read "after the question" and "after the decided
  marker" by index. `upstream_state.py`'s `decision` and `parent_check`, `watch_state.py`
  (`open_hold` on the App's drafts, D-67), and `skills/github-pr-triage/scripts/pr_gate.py`
  (`newest_question`, `acceptance`, `unhandled_veto`) read the same way
- **Dates:** the verdict's `createdAt` against a hold's close (#1493), the newest postponed
  verdict's `createdAt` against the newest stable tag (`postponed_state`, REVISIT, spec 061), a
  hand-off, still-waits, check-failed, check-waiting, verified, or close-confirmed marker's
  `createdAt` against a close (D-29, spec 042), and an answer's `createdAt` against the pull
  request's (`acceptance`)

So a `Triage:` verdict and its hold sentences stay new comments. Written into a status
comment created earlier, a verdict keeps that comment's old position: a relay or a reply
posted between the status comment's creation and the verdict's edit reads as newer than the
verdict, and the item reads DECIDED again after the verdict took the answer up. Switching the
readers to `updatedAt` or `lastEditedAt` doesn't fix it but races the other way: a later
status edit for an unrelated step moves the verdict's date past a reply, a relay, a hold's
close, or a stable tag that came after the verdict was really written, so an answer reads as
already taken up, a hold closed meanwhile is dropped as decided again, and a postponed issue
never reaches REVISIT because each edit restarts its clock. A person's edit of an old reply
would move it past the verdict that took it up, too. The readers keep `createdAt` and
position, and no reader dates an edited comment by its edit.

### The status comment

A session keeps one status comment per item (an issue or a pull request) and writes its
progress by editing it. Its body is:

```markdown
<!-- shipmill:status -->
Updated 2026-11-24 10:15 UTC

{the session's text: where the item stands now}

<!-- shipmill:agent -->
```

- The first line is the marker `<!-- shipmill:status -->` exactly; the second is
  `Updated <YYYY-MM-DD HH:MM> UTC`, the host's clock at the write, so the thread shows when it
  last changed; the agent marker (D-62) is the last line, as on every body `shipmill gh` writes
- Each write replaces the whole body: the text says where the item stands now, and GitHub's
  edit history keeps the earlier steps
- It mentions nobody: a login in it goes in a code span (D-61), since GitHub notifies a
  person a mention is added for by an edit as by a new comment
- No reader reads it. Its first line matches no first-line marker (`Triage:`, needs-decision,
  `Decision by`, a veto, `done`, hand-off, still-waits, verified, check-failed, check-waiting,
  close-confirmed, decided), it carries the agent marker, so it is never a reply, a veto, or a
  done report (D-62), and `hold_refs` in `triage_state.py`, which reads hold sentences on any
  line of any comment, skips a comment whose first line is the status marker, so a progress
  line such as "waits on #12" holds nothing. Closing keywords are read from a pull request's
  title, body, and commits only (D-79), never from a comment

### Which posts stay new comments

A new comment is posted only when it has to reach someone or a reader dates it:

- A `Triage:` verdict, with its hold sentences ("On hold: ..."), and a hold line on a pull
  request
- A needs-decision question, a decided comment, a relayed decision (`Decision by`), and a
  veto-handled comment (D-21, D-48, D-49, D-61, D-88)
- A hand-off, a still-waits, check-waiting, check-failed, or verified comment, and a
  close-confirmed comment (D-29)
- The final result: the item is done (a fix merged, a check holds, a parent or report closes
  as done), closed (as not planned, won't fix, duplicate, or stale), or a pull request is
  refused

Every other post is progress and goes in the status comment: in
`skills/github-issue-triage/references/comments.md`, "The fix is in #{PR}" and the Follow-ups'
replaced pull request and plan changed after review; a session's step on a pull request it
reviews or lands (rebased, fixes committed, CI pending). A person's draft gets no status
comment, as it gets no review (D-67).

### `shipmill gh ... comment --status`

`--status` is shipmill's own flag of `shipmill gh issue comment <n>` and `shipmill gh pr
comment <n>` (`src/shipmill/app_gh.py`, `src/shipmill/cli.py`), never passed to gh, as
`--decided-in` is (spec 051). With it and `--body`/`-b` or `--body-file`/`-F`:

1. **Find.** It reads the item's comments with `gh api --paginate
   repos/<owner>/<repo>/issues/<n>/comments` (a pull request's thread comments are its issue
   comments), as the same identity the write uses, every page. The writer's status comment is
   the oldest comment whose first line is the status marker, whose author is the login the
   write goes out as (the App's bot as the App, the host's login with `identity = "host"` or
   `--as-host`), and whose body carries the agent marker. A marker comment by anyone else, or
   without the agent marker, is a person's text (D-62) and is never edited
2. **Write.** It builds the body above from the given text and the time. With the writer's
   status comment, it edits it with `gh api -X PATCH repos/<owner>/<repo>/issues/comments/<id>
   -f body=...`, through the edit path that keeps the agent marker (S-050-3); with none, it
   creates it with `gh api repos/<owner>/<repo>/issues/<n>/comments -f body=...`. The leak
   check (D-94) and the 65,536-character limit (S-050-5) hold as for every write
3. **Refuse.** It exits 2 before any write: with no body flag, with `--edit-last`,
   `--delete-last`, `--create-if-none`, `--web`, or `--editor`; on any command but `issue
   comment` and `pr comment`; when the given text has a line that is the status marker, or a
   bare `@login` outside a code span (naming the login, D-61); and when the comments can't be
   read, since creating then could leave a second status comment

Two sessions that write at once may each create one; the next write edits the oldest and
leaves the other as it is. Every write goes as the App where the repo sets it, never as the
decider (D-65).

### The skills

`skills/github-issue-triage/references/comments.md` gets a "Status comment" section with the
lists above, and its progress templates say `--status`. `skills/github-issue-resolve/SKILL.md`,
`skills/github-issue-triage/SKILL.md`, `skills/github-pr-triage/SKILL.md`, and
`skills/github-ship-watch/SKILL.md` post their progress with `--status` and never as a new
comment.

## Acceptance criteria

- S-090-1: three `shipmill gh issue comment <n> --status --body-file <f>` calls on an item with no status comment run one create and then two `gh api -X PATCH repos/<owner>/<repo>/issues/comments/<id>` edits of that comment, and no other comment write; `--status` never reaches gh, and `pr comment <n> --status` does the same on a pull request
- S-090-2: the written body is the status marker as its first line, `Updated <YYYY-MM-DD HH:MM> UTC` from the clock in UTC as its second, a blank line, the given text, and the agent marker once as its last line; after any number of edits it holds one `Updated` line and one agent marker
- S-090-3: the comment edited is the oldest whose first line is exactly the status marker, whose author is the writing login (the App's bot, or the host's login with `identity = "host"` or `--as-host`), and whose body carries the agent marker, found on any page of the comments (past the first 100 too); a marker comment by another login, one without the agent marker, and one with the marker past its first line are never edited, and with only those the call creates the writer's own
- S-090-4: `--status` exits 2 with no write when given no `--body` or `--body-file`; with `--edit-last`, `--delete-last`, `--create-if-none`, `--web`, or `--editor`; on any command but `issue comment` and `pr comment`; when the given text has a line equal to the status marker; when it has a bare `@login` outside a code span, naming the login; and when the comments can't be read
- S-090-5: a status write runs the leak check (D-94) and the 65,536-character limit on the whole new body, as an `issue comment` does, and exits 2 with no write when either refuses it
- S-090-6: `triage_state.py`, `upstream_state.py`, `watch_state.py` (its `open_hold` included), and `pr_gate.py` read the same state and note for an item with and without a status comment whose text holds a `Triage: **implement**` line, an `On hold: waits on #N` sentence naming an open issue, a `Decision by @<login>` line, a `veto` line, a `done` line, and each first-line marker the readers know, wherever it sits in the thread
- S-090-7: no reader dates or orders a comment by its `updatedAt` or `lastEditedAt`: a status comment or a verdict given a later `updatedAt` and `lastEditedAt` with its `createdAt` and position unchanged leaves every state of S-090-6's readers as it was, a relay after the verdict still reading DECIDED and a postponed verdict older than the newest stable tag still reading REVISIT
- S-090-8: `comments.md` has a "Status comment" section that lists the posts that stay new comments (a verdict and its hold sentences, a hold line on a pull request, a question, a decided comment, a relay, a veto-handled comment, a hand-off, still-waits, check-waiting, check-failed, verified, close-confirmed, and the final result: done, closed, refused) and the progress that goes in the status comment, says a person's draft gets none (D-67), and its "The fix is in #{PR}" and Follow-ups templates post with `--status`
- S-090-9: `github-issue-resolve`, `github-issue-triage`, `github-pr-triage`, and `github-ship-watch`'s `SKILL.md` each post their progress on an item with `--status` and say a progress step is never a new comment

## Out of scope

- Unsubscribing the maintainer from a thread: it needs their own token, against D-14
- Moving a verdict, a hold sentence, or a dated marker into the status comment: the readers
  key on their position and `createdAt` (Behaviour); a verdict still emails a subscribed
  maintainer, once per decision
- Showing the status comment's text in `shipmill status --item` (spec 088): a follow-up once
  status comments exist
- The gate's change check (spec 061), which reads the item's `updatedAt` as today: a status
  edit counts as the session's own write, as its comment did
- Comments written before the build: they stay as they are

## Decisions relied on

- D-5
- D-14
- D-16
- D-21
- D-29
- D-48
- D-49
- D-61
- D-62
- D-65
- D-67
- D-79
- D-88
- D-94

## Issues

- shipmill/shipmill#1591: S-090-1, S-090-2, S-090-3, S-090-4, S-090-5, S-090-6, S-090-7, S-090-8, S-090-9

## Verification

- S-090-1: read `_gh` in `src/shipmill/cli.py`: `status_write` takes `--status` out right after `decided_in`, and `_status_args` turns the call into `gh api repos/<r>/issues/<n>/comments -f body=` or `gh api -X PATCH repos/<r>/issues/comments/<id> -f body=` before `body_edit` and `marked_args` read it, as the App and as the host; holds
- S-090-2: `status_body` builds the marker, `Updated %Y-%m-%d %H:%M UTC` from `dt.datetime.now(dt.UTC)`, a blank line, the text with any agent marker stripped, and the agent marker once; an edit goes through `edited_args`, which keeps the marker once; holds
- S-090-3: `own_status` takes the first (oldest) comment of `gh api --paginate`'s every page whose first line is exactly the marker, whose login is the writer's (`app_login`'s bot as the App, `gh api user` as the host), and which carries the agent marker; holds
- S-090-4: ran `shipmill gh issue comment 1591 --status --edit-last -b x`, `shipmill gh pr comment 1591 --status -b "Thanks @romamo"`, and `shipmill gh issue create --status -t x -b y` in this checkout: each exited 2 naming why, before any token or write; a comments read that fails raises before the write; holds
- S-090-5: the status write becomes a `gh api` create or PATCH whose `body` field `_sized` checks against 65,536 characters and `_leak_check` reads as every write's text, both before gh runs; holds
- S-090-6: `hold_refs` in `triage_state.py` skips a comment whose first line is the status marker, which `watch_state.py`'s `open_hold` reads through; every other reader keys on a comment's first line or on the agent marker, which a status comment's first line and its agent marker keep it out of; holds
- S-090-7: grepped the four readers: none names `lastEditedAt`, and no GraphQL comments selection asks for `updatedAt`; they date a comment by `createdAt` and order it by its place; holds
- S-090-8: read `skills/github-issue-triage/references/comments.md`: its "Status comment" section lists the posts that stay new comments and the progress that goes in the status comment, says a person's draft gets none (D-67), and "The fix is in #{PR}" and both Follow-ups post with `--status`; holds
- S-090-9: read the four `SKILL.md` files: each has a "Progress goes in the status comment (spec 090)" rule posting progress with `--status` and saying a progress step is never a new comment; holds
