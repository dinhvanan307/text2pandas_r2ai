"""DP-003 — D0 Source Snapshot: manifest, checksum, validation.

Mục tiêu: chứng minh toàn bộ build dùng đúng một bản corpus, và corpus đó
không thay đổi trong lúc build (DI-01).

`corpus_id` được định nghĩa CHÍNH XÁC để hai lần cài đặt độc lập cho cùng
một ID — bản kế hoạch chỉ ghi `sha256(sorted(rel_path + file_sha256))`, chưa
đủ để tái lập. Định nghĩa chốt ở đây:

    dòng_i    = rel_path_posix + "\\x1f" + sha256_hex
    corpus_id = "sha256:" + sha256( "\\n".join(sorted(dòng_i)) mã hoá UTF-8 )

Sắp xếp theo thứ tự codepoint của chuỗi ghép, không theo locale.
"""

from __future__ import annotations

import hashlib
import json
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

__all__ = ["FileEntry", "Manifest", "build_manifest", "validate_corpus",
           "verify_unchanged", "SourceValidation"]

_SEP = "\x1f"
_CHUNK = 1 << 20


@dataclass(slots=True)
class FileEntry:
    rel_path: str
    n_bytes: int
    sha256: str
    # RC-05 — `None` nếu tệp là bản đại diện của nhóm nội dung; ngược lại là
    # `rel_path` của bản đại diện. Ghi nhận, KHÔNG loại: xem `duplicate_groups`.
    duplicate_of: str | None = None


# RC2-016 / AMD-04 · HAI ĐỊNH DANH TÁCH BẠCH.
#
#   uid_namespace_id     — hạt giống của make_uid(). ĐÓNG BĂNG theo RC1 để
#                          document_uid/table_uid/row_uid/column_uid/
#                          observation_uid của RC2 TRÙNG RC1. Không bao giờ
#                          đổi trong một dòng release.
#   corpus_content_hash  — băm nội dung corpus THẬT (chỉ tệp báo cáo). Đi vào
#                          build_id/manifest/differential. Đổi khi corpus đổi.
#
# Vì sao phải tách: bản cũ dùng MỘT `corpus_id` băm cả cây `CORPUS.parent`,
# gồm 3.958 tệp không thuộc corpus (3.954 trong `.cache/`). Chỉ cần cache ghi
# thêm một `.lock` giữa build A và B là corpus_id đổi -> build_id đổi -> C0 đỏ
# với lý do hoàn toàn gây hiểu nhầm. Đo thật: cây đó từng là 6.258 tệp ở một
# thời điểm và 5.931 ở thời điểm khác.
RC1_UID_NAMESPACE_ID = (
    "sha256:ca033190f2e9e99f8384bf59749484b0668c573e0a84e02a055d173d99de0cb9")


def is_corpus_report(rel_path: str) -> bool:
    """Tệp có thuộc CORPUS THẬT không (đối lập với tệp nằm cùng cây)."""
    return (rel_path.startswith("financial_statements/")
            and rel_path.endswith("_extracted.txt"))


@dataclass(slots=True)
class Manifest:
    dataset: str
    revision: str
    corpus_id: str            # tương thích ngược: = uid_namespace_id
    n_files: int
    n_reports: int
    n_bytes: int
    files: list[FileEntry] = field(default_factory=list)
    uid_namespace_id: str = ""
    corpus_content_hash: str = ""
    n_content_files: int = 0
    n_content_bytes: int = 0

    @property
    def duplicate_groups(self) -> list[dict]:
        """Các nhóm tệp TRÙNG BYTE, nhóm theo sha256.

        Đây là thuộc tính của corpus nguồn, không phải lỗi của pipeline: ban tổ
        chức phát hành cùng một nội dung dưới hai tên tệp. Ghi ra để người tiêu
        thụ biết mà khử trùng ở tầng truy hồi — nơi nó thật sự tốn điểm, vì hai
        bảng y hệt cùng được trả về sẽ chia đôi precision của câu hỏi đó.
        """
        by_hash: dict[str, list[str]] = {}
        for f in self.files:
            by_hash.setdefault(f.sha256, []).append(f.rel_path)
        return [{"sha256": h, "files": sorted(v), "canonical": min(v)}
                for h, v in sorted(by_hash.items()) if len(v) > 1]

    @property
    def n_duplicate_files(self) -> int:
        """Số tệp DƯ ra (mỗi nhóm n tệp đóng góp n−1), không phải số nhóm."""
        return sum(len(g["files"]) - 1 for g in self.duplicate_groups)

    def to_json(self) -> dict:
        return {
            "dataset": self.dataset,
            "revision": self.revision,
            "corpus_id": self.corpus_id,
            # RC2-016 · hai ID tách bạch, xem AMD-04.
            "uid_namespace_id": self.uid_namespace_id or self.corpus_id,
            "corpus_content_hash": self.corpus_content_hash,
            "n_content_files": self.n_content_files,
            "n_content_bytes": self.n_content_bytes,
            "identity_note": (
                "uid_namespace_id seed cho make_uid() và ĐÓNG BĂNG theo RC1; "
                "corpus_content_hash băm CHỈ tệp báo cáo và đi vào build_id."),
            "n_files": self.n_files,
            "n_reports": self.n_reports,
            "n_bytes": self.n_bytes,
            # `corpus_id` vẫn băm TOÀN BỘ tệp, kể cả bản trùng. Cố ý: corpus
            # thật sự chứa ngần ấy byte, và ID phải mô tả thứ đã nhận, không
            # phải thứ ta muốn nó là.
            "n_duplicate_files": self.n_duplicate_files,
            "duplicate_groups": self.duplicate_groups,
            "files": [
                {"rel_path": f.rel_path, "bytes": f.n_bytes, "sha256": f.sha256,
                 **({"duplicate_of": f.duplicate_of} if f.duplicate_of else {})}
                for f in self.files
            ],
        }


def _sha256_file(path: Path) -> tuple[str, int]:
    h = hashlib.sha256()
    n = 0
    with path.open("rb") as fh:
        while chunk := fh.read(_CHUNK):
            h.update(chunk)
            n += len(chunk)
    return h.hexdigest(), n


def compute_corpus_id(entries: list[FileEntry]) -> str:
    lines = sorted(f"{e.rel_path}{_SEP}{e.sha256}" for e in entries)
    digest = hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest()
    return f"sha256:{digest}"


def build_manifest(root: Path, dataset: str, revision: str,
                   uid_namespace_id: str | None = None) -> Manifest:
    """Duyệt tất định, tính checksum theo luồng. Không dùng mtime làm identity."""
    entries: list[FileEntry] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.name.startswith("."):
            continue
        rel = path.relative_to(root).as_posix()
        if "/_codebase/" in f"/{rel}" or rel.startswith("_"):
            continue  # companion GitHub repo — không thuộc corpus dữ liệu
        digest, n = _sha256_file(path)
        entries.append(FileEntry(rel, n, digest))

    # RC-05 · gắn nhãn bản trùng byte. Bản đại diện là `rel_path` nhỏ nhất theo
    # thứ tự từ điển — một quy tắc TẤT ĐỊNH, để hai lần chạy chọn cùng một bản.
    first_by_hash: dict[str, str] = {}
    for e in sorted(entries, key=lambda x: x.rel_path):
        first_by_hash.setdefault(e.sha256, e.rel_path)
    for e in entries:
        canon = first_by_hash[e.sha256]
        e.duplicate_of = None if canon == e.rel_path else canon

    reports = [e for e in entries if e.rel_path.endswith(".txt")
               and e.rel_path.startswith("financial_statements/")]
    # Nội dung corpus THẬT — cơ sở của corpus_content_hash.
    content = [e for e in entries if is_corpus_report(e.rel_path)]
    ns = uid_namespace_id or compute_corpus_id(entries)
    return Manifest(
        dataset=dataset, revision=revision,
        corpus_id=ns,                      # tương thích ngược
        uid_namespace_id=ns,
        corpus_content_hash=compute_corpus_id(content),
        n_content_files=len(content),
        n_content_bytes=sum(e.n_bytes for e in content),
        n_files=len(entries), n_reports=len(reports),
        n_bytes=sum(e.n_bytes for e in entries), files=entries,
    )


@dataclass(slots=True)
class SourceValidation:
    """Cổng khẳng định, không phải phép biến đổi. Corpus đã đo là sạch."""
    n_files: int = 0
    n_bom: int = 0
    n_utf8_error: int = 0
    n_nul: int = 0
    n_crlf: int = 0
    n_lone_cr: int = 0
    n_tab: int = 0
    n_nbsp: int = 0
    n_zero_width: int = 0
    n_not_nfc: int = 0
    n_empty: int = 0
    n_no_trailing_newline: int = 0
    n_table_not_line_start: int = 0
    n_page_marker_variant: int = 0
    failures: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.failures and self.n_utf8_error == 0 and self.n_empty == 0

    def to_json(self) -> dict:
        return {k: getattr(self, k) for k in self.__slots__}


_ZW = "​‌‍⁠﻿­"
_PAGE_PREFIX = "===== PAGE "


def validate_corpus(root: Path, manifest: Manifest) -> SourceValidation:
    import re

    page_exact = re.compile(r"^===== PAGE \d+ =====$")
    v = SourceValidation()
    for entry in manifest.files:
        if not entry.rel_path.endswith(".txt"):
            continue
        if not entry.rel_path.startswith("financial_statements/"):
            continue
        path = root / entry.rel_path
        v.n_files += 1
        raw = path.read_bytes()
        if entry.n_bytes == 0:
            v.n_empty += 1
            v.failures.append(f"tệp rỗng: {entry.rel_path}")
            continue
        if raw.startswith(b"\xef\xbb\xbf"):
            v.n_bom += 1
        if b"\x00" in raw:
            v.n_nul += 1
        if b"\r\n" in raw:
            v.n_crlf += 1
        if raw.count(b"\r") - raw.count(b"\r\n") > 0:
            v.n_lone_cr += 1
        if not raw.endswith(b"\n"):
            v.n_no_trailing_newline += 1
        try:
            txt = raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            v.n_utf8_error += 1
            v.failures.append(f"UTF-8 lỗi: {entry.rel_path} — {exc}")
            continue
        if "\t" in txt:
            v.n_tab += 1
        if " " in txt:
            v.n_nbsp += 1
        if any(c in txt for c in _ZW):
            v.n_zero_width += 1
        if not unicodedata.is_normalized("NFC", txt):
            v.n_not_nfc += 1
        for line in txt.split("\n"):
            if line.startswith(_PAGE_PREFIX) and not page_exact.match(line):
                v.n_page_marker_variant += 1
            if "<table" in line and not line.startswith("<table"):
                v.n_table_not_line_start += 1
    return v


def verify_unchanged(root: Path, manifest: Manifest) -> list[str]:
    """DI-01: corpus không đổi trong lúc build. Trả danh sách lệch."""
    drift: list[str] = []
    for entry in manifest.files:
        path = root / entry.rel_path
        if not path.exists():
            drift.append(f"biến mất: {entry.rel_path}")
            continue
        digest, n = _sha256_file(path)
        if digest != entry.sha256:
            drift.append(f"checksum đổi: {entry.rel_path}")
        elif n != entry.n_bytes:
            drift.append(f"kích thước đổi: {entry.rel_path}")
    return drift


def write_manifest(manifest: Manifest, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(manifest.to_json(), ensure_ascii=False, sort_keys=True, indent=1),
        encoding="utf-8",
    )


def read_manifest(path: Path) -> Manifest:
    d = json.loads(path.read_text(encoding="utf-8"))
    return Manifest(
        dataset=d["dataset"], revision=d["revision"], corpus_id=d["corpus_id"],
        n_files=d["n_files"], n_reports=d["n_reports"], n_bytes=d["n_bytes"],
        # `duplicate_of` khuyết ở manifest cũ — đọc lại phải chịu được điều đó,
        # nếu không thì mọi gói đã phát hành trước RC-05 trở nên không mở được.
        files=[FileEntry(f["rel_path"], f["bytes"], f["sha256"],
                         f.get("duplicate_of"))
               for f in d["files"]],
    )
