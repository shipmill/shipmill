### Changed

- Spec 087 widens the headless sandbox per item: a narrow grant (`[agents.sandbox.grant]`, switched on by a `sandbox:<kind>` label a trusted person set, never the App) opens a domain, a path, local ports or a tunnel for one launch and is named on the tick; tunnels reach their port through `local_ports` (`allowLocalBinding`), since one `127.0.0.1:<port>` serves only a proxy-aware HTTP client (#1588); full access (ssh with a key, Docker) never runs headless and goes to its people as a `role:maintainer` item with the command that opens an interactive session (#1610)
