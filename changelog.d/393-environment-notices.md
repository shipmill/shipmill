### Added

- A deployment tells its fixed issues: after a tag's first successful deployment to an environment of `[environments]`, read from GitHub deployments, the watch reports UNANNOUNCED for each closed issue whose fix the tag holds and the environment didn't run before, and `shipped.py --environment <name> --post` comments `Deployed to <environment> in <tag>.` under a `<!-- shipmill:available: <environment> <tag> -->` marker, once per issue and environment (spec 021) (#393)
