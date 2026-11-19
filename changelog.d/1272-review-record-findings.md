### Added

- `shipmill review record --findings confirmed=N,rejected=N,minor=N` writes the second look's finding counts on the line after the verdict's marker, and refuses a refusal with nothing confirmed or a merge with a confirmed finding; without the flag the record is as before (#1272)
