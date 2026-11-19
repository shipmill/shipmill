### Fixed

- Delivery hooks: a `gh api graphql` `mergePullRequest` or `enablePullRequestAutoMerge` mutation is held to the merge method too, its `mergeMethod` read from the query, a `-f`/`-F` variable, an `-F @file`, or an `--input` body: `REBASE` is refused always, `SQUASH` under `[agents] merge = "merge"`, and a mutation or query the hook can't read, such as one on stdin, is refused (#1373)
