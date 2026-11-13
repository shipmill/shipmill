### Fixed

- `shipmill gh api repos/<owner>/<repo>/pulls` as a POST, named with `-X`/`--method` or implied by a field, checks the pull request's body for its plan as `shipmill gh pr create` does and exits 2 without running gh when the plan doesn't hold, a body read from `-F body=@<file>` or stdin and a create with no body included; a GET listing pull requests and an edit of one run as before (#1121)
