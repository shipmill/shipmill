### Fixed

- Evals: every case runs its own `scaffold.sh`, which calls the shared `evals/scaffold.sh`, since `claude plugin eval` now refuses a `scaffold_script` outside the case's directory and ran no case; `shipmill evals check` refuses such a path, and a default-branch run where no case ran is never kept as the baseline, nor compared against when one was (#929)
- Evals: the workflow keeps the project's virtualenv under `$RUNNER_TEMP`, out of the checkout `claude plugin eval` scans as the plugin, which refused every case for the hard links uv made into `.venv` (#929)
- Evals: the workflow installs `bubblewrap` and `socat`, so Claude Code can confine a case's shell tool instead of refusing every case before a turn, and lifts Ubuntu's AppArmor limit on user namespaces only when `bwrap` can't create one (#929)
