### Changed

- `shipmill upgrade --propose` never moves an upgrade issue backwards when two shipmill releases propose on one repo (spec 047): it leaves the title, body, and labels of an issue whose marker records a version newer than its own catalogue's version of that upgrade, compared in version order (0.9.0 before 0.10.0), and reports it `unchanged`; an open issue whose marker names an id it neither offers nor has withdrawn stays open and unchanged and is not listed. A marker whose version shipmill can't read counts as not newer, and the run rewrites it as before (#903)
