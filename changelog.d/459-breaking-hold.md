### Changed

- A trigger never releases a breaking change on stable: when quiet time, a window, or a milestone makes the stable lane due and its pending entries (at the rc's base, for a promotion) sit under a `major` heading, `shipmill plan` proposes it with the cause "a breaking change waits for the maintainer's decision" under `act` too; starting the stable lane by hand still releases it (#459)
