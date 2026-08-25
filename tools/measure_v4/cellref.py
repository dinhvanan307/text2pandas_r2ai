"""AST-based extraction of dataframe cell selectors from an emitted pandas query.

Pure, deterministic, no QID knowledge. Returns selectors in source order.
"""
from __future__ import annotations
import ast
from dataclasses import dataclass, field, asdict
from typing import Any


@dataclass
class CellRef:
    df_var: str
    filters: dict            # column -> literal value
    value_column: str | None  # column projected, e.g. 'value'
    index: int | None         # .values[i]
    order: int = 0

    def to_dict(self):
        return asdict(self)


def _is_df_name(node) -> str | None:
    if isinstance(node, ast.Name) and node.id.startswith("df"):
        return node.id
    return None


def _collect_eq(node, out: dict) -> None:
    """Collect  df['col'] == 'lit'  comparisons from a boolean mask expression."""
    if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.BitAnd, ast.BitOr)):
        _collect_eq(node.left, out)
        _collect_eq(node.right, out)
        return
    if isinstance(node, ast.Compare) and len(node.ops) == 1 and isinstance(node.ops[0], ast.Eq):
        left, right = node.left, node.comparators[0]
        if isinstance(left, ast.Subscript) and _is_df_name(left.value):
            col = left.slice
            if isinstance(col, ast.Constant) and isinstance(right, ast.Constant):
                out[str(col.value)] = right.value
        return
    # unwrap parenthesised / other containers
    for child in ast.iter_child_nodes(node):
        _collect_eq(child, out)


def extract_cellrefs(query: str) -> tuple[list[CellRef], bool, str | None]:
    try:
        tree = ast.parse(query, mode="eval")
    except SyntaxError as e:
        return [], False, str(e)
    refs: list[CellRef] = []

    class V(ast.NodeVisitor):
        def visit_Subscript(self, node: ast.Subscript):
            df = _is_df_name(node.value)
            if df is not None and not isinstance(node.slice, ast.Constant):
                filt: dict = {}
                _collect_eq(node.slice, filt)
                if filt:
                    refs.append(CellRef(df_var=df, filters=filt, value_column=None,
                                        index=None, order=len(refs)))
            self.generic_visit(node)

    V().visit(tree)

    # attach projected column + positional index by re-walking for the enclosing shape
    proj: list[tuple[str | None, int | None]] = []

    class W(ast.NodeVisitor):
        def visit_Subscript(self, node: ast.Subscript):
            df = _is_df_name(node.value)
            if df is not None and not isinstance(node.slice, ast.Constant):
                filt: dict = {}
                _collect_eq(node.slice, filt)
                if filt:
                    proj.append(_enclosing(node))
            self.generic_visit(node)

    _parent: dict[int, Any] = {}
    for p in ast.walk(tree):
        for c in ast.iter_child_nodes(p):
            _parent[id(c)] = p

    def _enclosing(node):
        col = None
        idx = None
        cur = node
        p = _parent.get(id(cur))
        if isinstance(p, ast.Subscript) and isinstance(p.slice, ast.Constant):
            col = str(p.slice.value)
            cur = p
            p = _parent.get(id(cur))
        if isinstance(p, ast.Attribute) and p.attr == "values":
            cur = p
            p = _parent.get(id(cur))
            if isinstance(p, ast.Subscript) and isinstance(p.slice, ast.Constant):
                try:
                    idx = int(p.slice.value)
                except (TypeError, ValueError):
                    idx = None
        return col, idx

    W().visit(tree)
    for r, (col, idx) in zip(refs, proj):
        r.value_column = col
        r.index = idx
    return refs, True, None
