### Fixed

- An eval case's write through `shipmill gh`, or `uvx ... shipmill gh` headless, now reaches the offline `gh` stub instead of failing for want of the App's token: `evals/bin` gains `shipmill` and `uvx` shims that send `shipmill gh` to the stub, logged with `"via": "shipmill"` so a grader still catches a plain `gh` write, and pass every other command to the real program (#494)
