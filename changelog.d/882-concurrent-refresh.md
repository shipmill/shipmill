### Fixed

- With `author = "decider"`, two `shipmill gh` runs that refresh the same expired token at once no longer log the person out: GitHub refuses the second refresh because refresh tokens are single-use, so that run re-reads the stored file and writes with the token the first run saved, deleting the file only when it still holds the refused refresh token; a file deleted meanwhile (by `app-logout`, or the other run) writes as the App instead of crashing on the missing file (#882)
