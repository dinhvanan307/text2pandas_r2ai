"""General, deterministic, unit-aware, multi-operand answer generation.

Stage boundaries are the point of this package. Each stage has its own typed
contract so a wrong answer can be attributed to exactly one of them:

    frame.py     what the question asks          (parsing defect)
    router.py    what must be computed           (compilation defect)
    binding.py   which cells supply the operands  (selection defect)
    units.py     what the numbers mean            (unit defect)
    render.py    the emitted pandas expression    (rendering defect)
    validate.py  guardrail, never a generator     (blocked, not fixed)
    pipeline.py  orchestration + trace

There is no QID whitelist in this package.
"""
from .binding import BoundOperand, CandidateCell, Selector, bind
from .frame import QuestionSemanticFrame, classify_operation, parse_question
from .ir import (AVG, DIVIDE, GROWTH, LOOKUP, SUBTRACT, SUM, OperandSlot,
                 OperationIR, ROLE_SPEC)
from .pipeline import PipelineResult, answer_question, build_evidence, execute
from .render import render
from .router import route
from .units import (COUNT, MONEY, PERCENT, RATIO, SHARES, UNKNOWN, ConversionStatus,
                    Quantity, Unit, convert, conversion_factor, query_factor)
from .validate import validate

__all__ = [
    "AVG", "DIVIDE", "GROWTH", "LOOKUP", "SUBTRACT", "SUM",
    "BoundOperand", "CandidateCell", "Selector", "bind",
    "QuestionSemanticFrame", "classify_operation", "parse_question",
    "OperandSlot", "OperationIR", "ROLE_SPEC",
    "PipelineResult", "answer_question", "build_evidence", "execute",
    "render", "route", "validate",
    "COUNT", "MONEY", "PERCENT", "RATIO", "SHARES", "UNKNOWN",
    "ConversionStatus", "Quantity", "Unit", "convert", "conversion_factor",
    "query_factor",
]
