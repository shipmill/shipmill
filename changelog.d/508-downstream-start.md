### Added

- `shipmill downstream start` writes a `downstream: <name>` check per `[downstream]` repository on a pull request's head and dispatches each one's workflow with a token minted for the App and limited to that repository, then dispatches the collect run; a fork's pull request waits for a person's `workflow_dispatch`, and the reusable `.github/workflows/downstream.yml` runs it from the default branch's checkout, never the pull request's code (#508)
