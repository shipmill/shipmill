### Changed

- `pr_gate.py` says which refusal it reads: a refuse record whose line right after its marker is `<!-- shipmill:findings confirmed=N rejected=N minor=N -->` reads `unreviewed: ... refuses it on N confirmed finding(s)`, and one without that line, or with one it can't read, reads `refuses it on findings no second reviewer checked`; both stay UNREVIEWED with exit 9, and a merge record reads READY with or without the line (#1274)
