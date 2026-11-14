# S-060: The App's owner gets an item when a release adds a permission to grant

status: approved
serves: G-4

## Problem

When a release adds a permission to the App's optional table (D-77), the owner of an existing
App has to act: add it in the App's settings, then accept it on each installation. Nothing
tells them to (shipmill/shipmill#1050, from #999). Every signal is one the owner has to go
and look at: the changelog entry, a WARN in `shipmill doctor`, a `warning:` line in the gate's
local tick log, a `DEPLOYMENTS_FORBIDDEN` row only with `[environments]`. `shipmill upgrade`
says nothing about permissions. GitHub asks installations to accept a permission only after
the owner has added it to the App, and that first step is the one nobody is told about.

#985 exists only because it was filed by hand for this project's own App. D-77 makes the
optional table the place every new permission goes, so each one passes the same way: the
feature quietly doesn't work for an existing App, while a new App gets it at creation.

## Behaviour

### What each optional permission serves

`OPTIONAL_PERMISSIONS` in `src/shipmill/app.py` gives each entry, beside its `serves` text, a
`needed(policy)` check saying whether the repo's config turns on what the permission serves.
The one entry today, Deployments: read, is needed when the config declares an environment
(`[environments]`). A new optional permission comes with its check, so the table stays the one
place a permission is added (D-77).

The warnings stay as they are: `shipmill doctor`'s `app` row and the gate preflight's
`warning:` line still name every optional permission the installation lacks, needed or not.

### The item

On a tick that sweeps (spec 046, every `[agents] sweep_hours`), after its config-upgrade
proposal (spec 047), the gate (`src/shipmill/gate.py`) runs a permission notice from a new
module, `src/shipmill/permission_notice.py`, writing as the App. It reads the installation's
permissions once, as minting a token does. A permission is accepted on the installation's
page and one installation covers many repos, so the notice files one item per installation,
not one per repo: for each optional permission the installation lacks, one issue in one repo
of the installation, the carrier, unless an issue for that permission already exists in any
repo of the installation, open or closed. The pattern is spec 014's proposal issue: one
issue per id, found by the marker on its first line and its label, and a close by the
maintainer ends it.

### The carrier

Every gate of the installation picks the same carrier from the same reads, so only one of
them files:

- The candidates are the installation's repos whose `.github/shipmill.toml` parses, sets
  `[agents] app_id` to this App, and turns the permission on (its `needed` check holds). A
  repo whose config is missing or doesn't parse runs no gate, so it is no candidate
- A candidate that is a product's home (its config has `[product] repos`, spec 038) comes
  first: the coordinator already builds the maintainer's queue there. With no home among the
  candidates, or more than one, the carrier is the first by full name, case ignored
- No candidate means no repo needs the permission, and nothing is filed (D-9)
- The gate whose repo is the carrier files the item in its own repo. Every other gate files
  nothing; its line says `permissions: carried by <owner/name>`

To read the installation, the notice mints, with the App's key, a token over the whole
installation with only metadata, contents, and issues read. It lists the installation's repos
(`GET /installation/repositories`), reads each one's `.github/shipmill.toml`, and searches
their issues for the marker. The token is held by the notice alone: it is never handed to a
session, put in a session's environment, or used to write. Writes still go through the
gate's own token, limited to its repo (D-14).

The marker search across the installation is what keeps a second item from being filed when
the carrier changes: a repo added or renamed, a home configured later, a config that stops
needing the permission. A gate that is now the carrier finds the item in the old carrier's
repo and files nothing.

The issue:

- its first line is the marker `<!-- shipmill-permission: <key> <access> -->`, such as
  `<!-- shipmill-permission: deployments read -->`
- its title is `Grant the App <label>: <access> and accept it on its installation`
- it carries the labels `shipmill-permission`, which the gate finds it by, and
  `role:maintainer`, which makes it a person's item (spec 036), and is assigned at once to the
  users the maintainer role resolves to on that tick
- its body names the permission, what it serves (`serves`), and each candidate repo with the
  config that turns it on there, says that one accept covers every repo of the installation,
  then gives the two steps, as #985 gives them:
  1. In the App's settings, set the permission, with the link to the App's permissions page:
     `https://github.com/settings/apps/<slug>/permissions` for an App a user owns,
     `https://github.com/organizations/<owner>/settings/apps/<slug>/permissions` for an
     organization's, read from the App's own record (`GET /app`)
  2. Accept the new permission on the installation's page (`Installation.settings`)
- it ends with a `## Check`: `shipmill doctor` in the carrier repo shows the `app` row as PASS
  for the permission, not WARN

From there the item follows spec 036 and spec 017 unchanged: triage hands it off, which is
the comment that notifies the owner, waits for `done`, and runs its check.

### Later sweeps

- The installation grants the permission and the issue is open: the gate of the repo that
  holds the issue, carrier or not, posts a comment whose first line is
  `<!-- shipmill:verified -->`, saying the installation grants it now, and closes the issue as
  completed. That is the item's check, done by the gate that can read it. Other gates write
  nothing
- The issue is open and the permission is still missing: nothing is written
- The issue is closed, whatever its reason: no gate of the installation files it again. A
  close as not planned is the owner's decline, for good. A close as completed while the
  permission is still missing reads VERIFY_CLOSED in triage, whose session runs the check and
  reopens the issue when it fails (D-79)
- No repo of the installation needs the permission any more and the issue is open: nothing is
  written; the item stays the owner's to close

### Where it shows

- The sweep's decision line gains a part, `permissions: filed #<n> <label>: <access>`, `closed
  #<n>`, or `permissions: none missing`, and `sweep.json` keeps it as it keeps the upgrade
  proposal's (S-047-10). A dry run files and closes nothing and says `permissions: would file
  <label>: <access>`
- A gate without `[agents] app_id` reads and writes nothing for this: there is no
  installation to read, and shipmill writes only as the App (D-54). Its line says
  `permissions: none read, [agents] sets no app_id`
- A failure of the notice (GitHub refusing the installation token, a read, or the write) is
  the line's, never the tick's, as an upgrade proposal's is. A gate that can't read the
  installation files nothing on that sweep, since it can't tell the carrier or find an item
  already filed
- `skills/shipmill-setup/scripts/setup_state.py` wants the `shipmill-permission` label with
  `[agents] app_id`, so `LABELS_MISSING` names it

### Docs

`docs/install.md`, where it says Deployments is optional (D-77), adds that the gate files
this item once per installation, in the carrier repo, when a repo of it needs a permission
the installation lacks, and that closing it as not planned declines it. The changelog entry of a release that adds an optional permission
no longer needs to carry the owner's steps: the item does.

## Acceptance criteria

- S-060-1: Each entry of `OPTIONAL_PERMISSIONS` has a `needed` check; Deployments: read's holds for a config with `[environments]` and not for one without
- S-060-2: A sweeping tick of the carrier's gate, with `[agents] app_id`, whose installation lacks Deployments: read while a candidate's config has `[environments]`, files one issue in its own repo whose first line is `<!-- shipmill-permission: deployments read -->`, with the labels `shipmill-permission` and `role:maintainer`, assigned to the maintainer role's users
- S-060-3: That issue's body names the permission, its `serves` text, each candidate repo with the config that needs it there, the App's permissions page link for a user-owned and for an organization-owned App, the installation's page, and a `## Check` naming `shipmill doctor`'s `app` row
- S-060-4: A later sweep with the permission still missing files no second issue while one with the marker is open, closed as completed, or closed as not planned in any repo of the installation, the carrier's or another's
- S-060-5: A sweep whose installation lacks Deployments: read while no repo of the installation has a config with `[environments]` files nothing
- S-060-6: A sweep whose installation grants the permission while its issue is open in the gate's own repo posts a comment whose first line is `<!-- shipmill:verified -->` and closes the issue as completed, whether or not that repo is still the carrier; a gate whose repo doesn't hold the issue writes nothing
- S-060-7: A tick that doesn't sweep reads no installation and writes nothing for this; a gate without `[agents] app_id` writes nothing and its line says so; a dry run writes nothing and its line names what it would file
- S-060-8: The sweep's decision line and `sweep.json` carry the notice's part; a GitHub refusal of the write ends up in that part, and the tick goes on to its walk as without it
- S-060-9: `shipmill doctor`'s `app` row and the gate preflight's `warning:` line still name each optional permission the installation lacks, needed or not
- S-060-10: `setup_state.py` reports `LABELS_MISSING` naming `shipmill-permission` for a config with `[agents] app_id` whose repo lacks it, and doesn't want it without `app_id`
- S-060-11: `docs/install.md` says the gate files the item for an optional permission the repo needs and its installation lacks, and that closing it as not planned declines it
- S-060-12: For an installation whose candidates are several repos, every candidate's gate picks the same carrier: a candidate whose config has `[product] repos` first, else the first by full name with case ignored; only the carrier's gate files, and each other gate's line says `permissions: carried by <owner/name>`
- S-060-13: A repo of the installation whose `.github/shipmill.toml` is missing, doesn't parse, sets no `[agents] app_id` or another App's, or doesn't need the permission is no candidate
- S-060-14: The notice's installation-wide token asks only metadata, contents, and issues read; it is never written to a session's environment, and every write the notice makes goes through the gate's token limited to its repo
- S-060-15: A sweep whose installation-wide token or read is refused files nothing and names the failure in the line, and the tick goes on to its walk as without it

## Out of scope

- `shipmill upgrade` printing or filing the step: it runs only when someone runs it, the same "go and look" gap; the gate already reads the installation on every sweep
- A permission `PERMISSIONS` requires: an installation that lacks one stops the gate at launch with its own fix (D-63), so no item is needed
- One item per repo: one installation covers many repos and is accepted once on its own page, so an item per repo would give the owner one identical item per repo for one accept (the maintainer's answer on #1063)
- One item across installations: each installation accepts the permission on its own page, so each gets its own item
- A gate writing in another repo of the installation: it reads them to pick the carrier and find the item, and writes only in its own
- Reopening an issue the gate closed when the permission is later revoked: a revoke is the owner's own act
- The release workflow filing the item: it has no App and can't read the installation; the agent side files it (Q-6 holds, since the release side needs no optional permission)
- A `watch_state.py` row of its own: the item is a person's item, which the report already lists

## Decisions relied on

- D-9: an owner is asked about a permission only where the config needs it
- D-14: the gate writes the item as the App, in its own repo only
- D-14 and D-47, departed from: a component's gate reads only its own repo (plus its home's
  docs/product.md and config). The notice reads every repo of its App's installation, their
  configs and their issues, read only and never in a session, to pick the carrier and find an
  item already filed. This needs a new decision refining them, recorded when this spec merges
- D-16: an issue the gate's App opened is trusted, so an unattended session hands it off
- D-54: without the App, nothing is written
- D-62: the item carries the agent marker, so it is no filing of the maintainer's
- D-63: a required permission stays out of this; a new one goes to the optional table
- D-79 (superseding D-76): an issue with a `## Check` closed as completed with no verified comment reads VERIFY_CLOSED, so its check runs
- D-77: the optional table names what each permission serves, and the warnings stay

## Issues

The build issues, filled in once they are filed: one `- owner/repo#N: S-NNN-1, S-NNN-2` per
line, naming the criteria that issue delivers. Each criterion belongs to exactly one.

## Verification

Filled in when the spec reaches `built`: one line per criterion id, saying how it was
checked against the default branch (beyond its tests) and the result.
