### Security

- The ship watch's state script passes the landing branch to `git fetch` only inside a `refs/heads/` refspec, and refuses a config `branch` that git's branch-name rules refuse, so a `branch` such as `--upload-pack=...` is no longer read as a git option (#892)
