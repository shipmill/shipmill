"""Spec 050: the agent marker, the line shipmill ends every body it writes with, so an agent's
text is told from a person's by a sign the agent can't leave off rather than by its author
(D-62). It is the body's last line, after a blank line, never its first: readers match other
markers and prefixes there"""

import re

MARKER = "<!-- shipmill:agent -->"
BODY_LIMIT = 65_536  # GitHub's limit on an issue's, pull request's, comment's, or review's body
ROOM = len(f"\n\n{MARKER}")  # what marking adds to a body that doesn't carry the marker yet
# a later attribute (`<!-- shipmill:agent via=gh -->`) reads the same
_LINE = re.compile(r"<!-- shipmill:agent(?:\s[^>]*)?-->")


def carries(body: str) -> bool:
    """Whether any line of body, stripped of surrounding whitespace, is the marker"""
    return any(_LINE.fullmatch(line.strip()) for line in body.splitlines())


def marked(body: str) -> str:
    """body as shipmill writes it: unchanged when it carries the marker already, else its text,
    a blank line, and the marker as its last line; the marker alone for a blank body"""
    if carries(body):
        return body
    text = body.rstrip()
    return f"{text}\n\n{MARKER}" if text else MARKER


def stripped(body: str) -> str:
    """body with every line that is the marker removed, with the blank lines after it when a
    blank line comes before it, and the blank lines that leaves at its end; a body that doesn't
    carry the marker is returned as it is"""
    if not carries(body):
        return body
    kept: list[str] = []
    dropping = False  # past a removed marker, with a blank line (or the start) before it
    for line in body.splitlines(keepends=True):
        if _LINE.fullmatch(line.strip()):
            dropping = not kept or not kept[-1].strip()
        elif not (dropping and not line.strip()):
            kept.append(line)
            dropping = False
    return "".join(kept).rstrip()


def unmarked(body: str) -> str:
    """body less the marker `marked` ended it with, for comparing a stored body with the text
    it was written from; a body without one is returned as it is"""
    head, _, last = body.rstrip().rpartition("\n")
    return head.rstrip() if _LINE.fullmatch(last.strip()) else body
