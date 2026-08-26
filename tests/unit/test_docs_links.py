from __future__ import annotations

from pathlib import Path

from tools.check_docs import find_broken_links


def test_document_link_checker_ignores_external_anchor_image_and_code(tmp_path: Path) -> None:
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "target.md").write_text("# Target\n", encoding="utf-8")
    source = docs / "source.md"
    source.write_text(
        "[ok](target.md) [anchor](#x) [web](https://example.com)\n"
        "![image](missing.png)\n"
        "```markdown\n[example](not-real.md)\n```\n",
        encoding="utf-8",
    )

    assert find_broken_links([source], tmp_path) == []


def test_document_link_checker_reports_relative_missing_target(tmp_path: Path) -> None:
    source = tmp_path / "README.md"
    source.write_text("See [missing](docs/missing.md).\n", encoding="utf-8")

    broken = find_broken_links([source], tmp_path)

    assert len(broken) == 1
    assert broken[0].source == source
    assert broken[0].line == 1
    assert broken[0].target == "docs/missing.md"
