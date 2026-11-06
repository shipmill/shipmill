### Fixed

- Evals: every case runs its own `scaffold.sh`, which calls the shared `evals/scaffold.sh`, since `claude plugin eval` now refuses a `scaffold_script` outside the case's directory and ran no case; `shipmill evals check` refuses such a path, and a default-branch run where no case ran is never kept as the baseline, nor compared against when one was (#929)
- Evals: the workflow keeps the project's virtualenv under `$RUNNER_TEMP`, out of the checkout `claude plugin eval` scans as the plugin, which refused every case for the hard links uv made into `.venv` (#929)
