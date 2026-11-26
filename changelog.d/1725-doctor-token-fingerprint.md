### Changed

- `doctor`'s `claude auth` row names the token file's fingerprint (the name of its pause record), the date the file was written and its expiry a year later, and whether a pause record holds for it, naming a still-held record for the fingerprint the gate's last launch ran with, which the file no longer holds, as stale; it reads the records and writes none, and the row now FAILs once the token is past a year, with the same fix as its WARN at 330 days (#1725)
