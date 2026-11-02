"""Where the skills shipmill runs live: bundled in the wheel, or the checkout's in development.
Its own module, importing only the errors, so a reader of the policy (decide.py) finds the
skills without importing the gate, which imports the upgrades that read the policy"""

from pathlib import Path

from shipmill.errors import ReleaseError


def skills_dir() -> Path:
    """The skills bundled in the wheel, or the checkout's skills folder in development"""
    here = Path(__file__).resolve().parent
    for candidate in (here / "skills", here.parents[1] / "skills"):
        if (candidate / "github-ship-watch").is_dir():
            return candidate
    raise ReleaseError("this shipmill install has no skills folder; reinstall it")
