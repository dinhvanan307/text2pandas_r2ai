"""Use case: dựng catalog từ corpus thô.

Chạy: `python -m text2pandas.interface.cli.main catalog`
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path

from text2pandas.infrastructure.catalog.scanner import iter_corpus, scan_document
from text2pandas.infrastructure.catalog.store import CatalogStore

__all__ = ["CatalogReport", "build_catalog"]


@dataclass(slots=True)
class CatalogReport:
    n_documents: int
    n_tables: int
    n_pages: int
    n_failed: int
    failures: list[tuple[str, str]]
    seconds: float
    by_pattern: dict[str, int]
    basis_conflicts: int
    docs_without_tables: int


def build_catalog(
    corpus_root: Path,
    db_path: Path,
    batch_size: int = 100,
    progress=None,
) -> CatalogReport:
    t0 = time.time()
    store = CatalogStore(db_path)
    store.set_meta("corpus_root", str(corpus_root))

    batch = []
    n_doc = n_tab = n_page = 0
    failures: list[tuple[str, str]] = []
    by_pattern: dict[str, int] = {}
    conflicts = 0
    no_tables = 0

    for idx, path in enumerate(iter_corpus(corpus_root), 1):
        try:
            doc = scan_document(path, corpus_root)
        except Exception as exc:  # noqa: BLE001 — fail loud, ghi lại, đi tiếp
            failures.append((path.name, repr(exc)))
            continue

        by_pattern[doc.identity.id_pattern] = (
            by_pattern.get(doc.identity.id_pattern, 0) + 1
        )
        if (
            doc.identity.basis
            and doc.content_basis
            and doc.identity.basis != doc.content_basis
        ):
            conflicts += 1
        if doc.n_tables == 0:
            no_tables += 1

        batch.append(doc)
        n_doc += 1
        n_tab += doc.n_tables
        n_page += doc.n_pages

        if len(batch) >= batch_size:
            store.write_documents(batch)
            batch.clear()
            if progress:
                progress(idx, n_tab)

    if batch:
        store.write_documents(batch)

    store.set_meta("n_documents", str(n_doc))
    store.set_meta("n_tables", str(n_tab))
    store.conn.commit()
    store.close()

    return CatalogReport(
        n_documents=n_doc,
        n_tables=n_tab,
        n_pages=n_page,
        n_failed=len(failures),
        failures=failures[:20],
        seconds=round(time.time() - t0, 1),
        by_pattern=by_pattern,
        basis_conflicts=conflicts,
        docs_without_tables=no_tables,
    )
