"""Client-facing strings must not carry UTF-8-read-as-Latin-1 mojibake (m-25072003)."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def test_no_mojibake_in_ads_and_app_strings() -> None:
    files = [
        *(ROOT / "packages/api/src/qualify_api/ads").rglob("*.py"),
        *(ROOT / "Qualify").glob("*.py"),
    ]
    hits = [
        f"{path.relative_to(ROOT)}:{number}"
        for path in files
        if "__pycache__" not in path.parts
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1)
        if "Ã" in line
    ]
    assert files and not hits, f"mojibake found: {hits}"
