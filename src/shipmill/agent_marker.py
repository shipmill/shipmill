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


def decided_by(login: str) -> str:
    """S-051-10: the line an issue or pull request written as a person ends its text with,
    the login in a code span (D-61)"""
    return f"Opened by an agent through shipmill, on `@{login}`'s decision."


def closed_with(body: str, line: str) -> str:
    """body marked, with line as its text's last paragraph: before the marker when the marker
    is the last line, as `marked` writes it, so the marker stays last (spec 050) and line is
    the last line GitHub renders; after the text otherwise. A body whose text ends with line
    already is returned marked, so line is never written twice"""
    text = marked(body).rstrip()
    head, _, last = text.rpartition("\n")
    if not _LINE.fullmatch(last.strip()):
        return text if text.rpartition("\n")[2].strip() == line else f"{text}\n\n{line}"
    rest = head.rstrip()
    if rest.rpartition("\n")[2].strip() == line:
        return text
    return f"{rest}\n\n{line}\n\n{last.strip()}" if rest else f"{line}\n\n{last.strip()}"


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
