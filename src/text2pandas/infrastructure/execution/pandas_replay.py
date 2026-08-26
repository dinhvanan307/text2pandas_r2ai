"""Materialize exact bound observations and replay a compiled pandas program."""

from __future__ import annotations

import pandas as pd  # type: ignore[import-untyped]

from text2pandas.application.binding import BoundExecutionPlan
from text2pandas.application.execution import PandasProgram
from text2pandas.infrastructure.sandbox.query import execute_query


class PandasSandboxReplay:
    def replay(self, program: PandasProgram, bound_plan: BoundExecutionPlan) -> float:
        by_uid = {
            operand.candidate.observation_uid: operand.candidate
            for operand in bound_plan.operands.values()
        }
        frames = {}
        for evidence in program.evidence:
            rows = [by_uid[uid] for uid in evidence.observation_uids]
            frames[evidence.variable] = pd.DataFrame(
                {
                    "observation_uid": [row.observation_uid for row in rows],
                    "value": [float(row.value) for row in rows],
                }
            )
        return execute_query(program.query, frames)
