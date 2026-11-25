"""Spec 087, What Claude Code provides: the design doc records the sandbox probe (S-087-1)"""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def provides() -> str:
    doc = " ".join(ROOT.joinpath("docs", "design", "agent-modes.md").read_text(encoding="utf-8").split())
    return doc.split("### What Claude Code provides", 1)[1].split("### ", 1)[0]


def test_s087_1_the_design_doc_records_the_macos_sandbox_probe() -> None:
    # proves: S-087-1 (macOS half; the Linux half is recorded by its own sub-issue of #1524)
    section = provides()
    assert "macOS half verified on Claude Code 2.1.330 (#1524)" in section
    assert ROOT.joinpath("docs", "design", "probe-087", "probe.sh").is_file()
    for observed in (
        "Operation not permitted",
        "File is in a directory that is denied by your permission settings",
        "deny network-outbound example.com:443",
        '"remedy": {"kind": "sandbox_violation"}',
        "Could not resolve hostname github.com",
        "as `shipmill-romamo[bot]`",
        "`uv run pytest -q tests/test_headless_docs.py` passed",
        "The project settings file did not widen the sandbox",
        "**Refusal text the tick reads.**",
    ):
        assert observed in section, observed


def test_the_design_doc_records_the_local_port_probe() -> None:
    # #1588: the setting that opens one local port to a sandboxed command, for S-087-10's tunnels
    section = provides()
    assert "macOS verified on Claude Code 2.1.330 (#1588)" in section
    assert ROOT.joinpath("docs", "design", "probe-087", "prompt-port.md").is_file()
    for observed in (
        '`"127.0.0.1:<port>"` in `sandbox.network.allowedDomains` opens that one port',
        "only through the sandbox's proxy",
        "deny network-outbound 127.0.0.1:18766",
        "`sandbox.network.allowLocalBinding: true` (macOS only) opens every local port",
        "**Refusal text for a closed local port.**",
    ):
        assert observed in section, observed
