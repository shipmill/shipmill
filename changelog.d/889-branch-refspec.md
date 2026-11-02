### Security

- The config's `branch` must be a name git's branch-name rules accept (no leading `-`, `..`, spaces, control characters, `~ ^ : ? * [ \`, `@{`, and so on): one they refuse stops the config from loading, naming `branch`, and the gate's refresh passes the branch to git only inside a `refs/heads/` refspec, so a branch such as `--upload-pack=...` is never read as a git option (#889)
