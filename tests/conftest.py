"""Repository-wide pytest governance hooks."""

from __future__ import annotations

from collections import Counter
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
SKIP_POLICY = ROOT / "configs" / "testing" / "approved_skips_v1.yaml"
_OBSERVED_SKIPS: list[tuple[str, str]] = []


def _skip_reason(report: pytest.TestReport) -> str:
    longrepr = report.longrepr
    if isinstance(longrepr, tuple) and len(longrepr) == 3:
        return str(longrepr[2])
    return str(longrepr)


def _load_allowlist() -> list[dict[str, object]]:
    document = yaml.safe_load(SKIP_POLICY.read_text(encoding="utf-8"))
    if document.get("schema_version") != 1:
        raise pytest.UsageError("approved skip policy schema_version must equal 1")
    entries = document.get("allowlist")
    if not isinstance(entries, list):
        raise pytest.UsageError("approved skip policy allowlist must be a list")
    return entries


def pytest_configure(config: pytest.Config) -> None:
    del config
    _OBSERVED_SKIPS.clear()


def pytest_runtest_logreport(report: pytest.TestReport) -> None:
    if report.skipped and not hasattr(report, "wasxfail"):
        _OBSERVED_SKIPS.append((report.nodeid, _skip_reason(report)))


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    del exitstatus
    observed = _OBSERVED_SKIPS
    entries = _load_allowlist()
    counts: Counter[int] = Counter()
    violations: list[str] = []
    for nodeid, reason in observed:
        matched = next(
            (
                index
                for index, entry in enumerate(entries)
                if nodeid.startswith(str(entry["node_prefix"]))
                and str(entry["reason_contains"]) in reason
            ),
            None,
        )
        if matched is None:
            violations.append(f"unapproved skip: {nodeid} — {reason}")
            continue
        counts[matched] += 1
    for index, count in counts.items():
        maximum = int(entries[index]["max_count"])
        if count > maximum:
            violations.append(
                f"approved skip count exceeded for {entries[index]['node_prefix']}: "
                f"{count}>{maximum}"
            )
    if violations:
        session.exitstatus = pytest.ExitCode.TESTS_FAILED
        terminal = session.config.pluginmanager.get_plugin("terminalreporter")
        if terminal is not None:
            terminal.write_sep("=", "SKIP GOVERNANCE FAILED", red=True)
            for violation in violations:
                terminal.write_line(violation, red=True)
