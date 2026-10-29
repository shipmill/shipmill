class ReleaseError(Exception):
    """Bad input: a malformed policy, version, or CHANGELOG, a repo the bot can't read, or a
    state it refuses to act on. The CLI exits 2 with the message. fix, when the error knows
    one, is what to run about it, which the gate's tick.json records (spec 048); the message
    keeps naming it as before"""

    def __init__(self, message: str, fix: str | None = None) -> None:
        super().__init__(message)
        self.fix = fix
