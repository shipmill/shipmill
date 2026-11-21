### Fixed

- `shipmill operate` comments a compare incident healthy again in an environment with probes and no `health`: once the environment's newest successful deployment runs a tag other than the one that answered differently, the incident reads healthy, where before it stayed open until a person closed it. A deployment still in progress ends nothing, and the incident's body says what ends it there (#1451)
