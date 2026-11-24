### Security

- `shipmill gh` refuses with exit 2 a comment holding the `shipmill:decided` marker on an issue or pull request whose body or comments name a CVE or GHSA id, or whose thread can't be read, and points to the needs-decision question instead, so a decision on a known vulnerability is asked whatever its zone's level (D-104, S-030-25) (#1483)
