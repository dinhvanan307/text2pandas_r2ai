"""Validate relative links in tracked Markdown documentation."""

from __future__ import annotations

import argparse
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote

_INLINE_LINK = re.compile(r"(?<!!)\[[^\]]*\]\((?P<target>[^)]+)\)")
_EXTERNAL_SCHEMES = ("http://", "https://", "mailto:", "tel:")


@dataclass(frozen=True, slots=True)
class BrokenLink:
    source: Path
    line: int
    target: str


def find_broken_links(files: list[Path], repo_root: Path) -> list[BrokenLink]:
    broken: list[BrokenLink] = []
    for source in files:
        if not source.is_file():
            continue
        in_fence = False
        for line_number, line in enumerate(
            source.read_text(encoding="utf-8").splitlines(), 1
        ):
            if line.lstrip().startswith("```"):
                in_fence = not in_fence
                continue
            if in_fence:
                continue
            for match in _INLINE_LINK.finditer(line):
                raw = match.group("target").strip()
                target = (
                    raw[1:-1]
                    if raw.startswith("<") and raw.endswith(">")
                    else raw.split(maxsplit=1)[0]
                )
                if not target or target.startswith(("#", *_EXTERNAL_SCHEMES)):
                    continue
                path_part = unquote(target.split("#", 1)[0])
                if not path_part:
                    continue
                resolved = (
                    repo_root / path_part.lstrip("/")
                    if path_part.startswith("/")
                    else source.parent / path_part
                ).resolve(strict=False)
                if not resolved.exists():
                    broken.append(BrokenLink(source, line_number, target))
    return broken


def _tracked_markdown(repo_root: Path) -> list[Path]:
    output = subprocess.check_output(
        ["git", "ls-files", "*.md"], cwd=repo_root, text=True
    )
    return [repo_root / relative for relative in output.splitlines() if relative]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path.cwd())
    args = parser.parse_args()
    root = args.root.resolve()
    files = _tracked_markdown(root)
    broken = find_broken_links(files, root)
    for item in broken:
        print(f"{item.source.relative_to(root)}:{item.line}: missing {item.target}")
    print(f"markdown_files={len(files)} broken_links={len(broken)}")
    return 1 if broken else 0


if __name__ == "__main__":
    raise SystemExit(main())
