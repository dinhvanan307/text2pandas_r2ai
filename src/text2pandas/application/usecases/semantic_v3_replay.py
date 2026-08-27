"""Clean replay audit for materialized Semantic V3 records."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from pathlib import Path

import pandas as pd

from text2pandas.infrastructure.sandbox.query import execute_query


def replay_semantic_v3_records(
    records: Sequence[Mapping[str, object]],
    data_root: Path,
    *,
    tolerance: float = 1e-9,
) -> dict[str, object]:
    root = data_root.resolve()
    cache: dict[Path, pd.DataFrame] = {}
    failures: list[dict[str, object]] = []
    emitted = matched = abstentions = 0
    seen: set[int] = set()
    for record in records:
        qid = int(record.get("qid", 0))
        if qid <= 0 or qid in seen:
            raise ValueError(f"invalid or duplicate qid: {qid}")
        seen.add(qid)
        status = record.get("status")
        answer = _finite_number(record.get("answer"))
        query = str(record.get("pandas_query") or "")
        evidence = record.get("evidence") or []
        if status == "ABSTAIN":
            abstentions += 1
            if answer is not None or query or evidence:
                failures.append({"qid": qid, "reason": "ABSTAIN_PAYLOAD_LEAK"})
            continue
        if status != "OK":
            failures.append({"qid": qid, "reason": f"INVALID_STATUS:{status}"})
            continue
        emitted += 1
        if answer is None or not query or not isinstance(evidence, list) or not evidence:
            failures.append({"qid": qid, "reason": "INCOMPLETE_OK_RECORD"})
            continue
        try:
            frames: dict[str, pd.DataFrame] = {}
            for item in evidence:
                if not isinstance(item, Mapping):
                    raise TypeError("evidence item must be an object")
                path = (root / str(item["csv_path"])).resolve()
                if not path.is_relative_to(root):
                    raise ValueError("evidence path escapes data root")
                if path not in cache:
                    cache[path] = pd.read_csv(path)
                frames[str(item["variable"])] = cache[path]
            replayed = execute_query(query, frames)
            if math.isclose(replayed, answer, rel_tol=tolerance, abs_tol=tolerance):
                matched += 1
            else:
                failures.append(
                    {
                        "qid": qid,
                        "reason": "REPLAY_MISMATCH",
                        "answer": answer,
                        "replayed": replayed,
                    }
                )
        except Exception as error:  # noqa: BLE001 - reported as an audit result
            failures.append(
                {"qid": qid, "reason": f"REPLAY_ERROR:{type(error).__name__}:{error}"}
            )
    return {
        "schema_version": 1,
        "records": len(records),
        "emitted": emitted,
        "abstentions": abstentions,
        "matched": matched,
        "mismatches": sum(item["reason"] == "REPLAY_MISMATCH" for item in failures),
        "errors": sum(item["reason"] != "REPLAY_MISMATCH" for item in failures),
        "replay_consistency": matched / emitted if emitted else None,
        "failures": failures,
    }


def _finite_number(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        return None
    try:
        result = float(value)
    except ValueError:
        return None
    return result if math.isfinite(result) else None

