from __future__ import annotations

import re
from typing import Optional

import numpy as np


def fmt_val(x: float, kind: str) -> str:
    return f"{x * 100:.2f}%" if kind == "proportion" else f"{x:,.3f}"


def fmt_diff(x: float, kind: str) -> str:
    return f"{x * 100:+.2f} pp" if kind == "proportion" else f"{x:+,.3f}"


def fmt_p(p: Optional[float]) -> str:
    if p is None or (isinstance(p, float) and np.isnan(p)):
        return "n/a"
    return "<0.001" if p < 0.001 else f"{p:.3f}"


def fmt_pct(x: Optional[float], digits: int = 1) -> str:
    return "n/a" if x is None else f"{x * 100:+.{digits}f}%"


# --- grounding check for LLM text -------------------------------------------
_NUM = re.compile(r"(?<![\w.])(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?")


def _tokens(text: str) -> list[tuple[float, int]]:
    out = []
    for m in _NUM.finditer(text):
        tok = m.group().replace(",", "")
        decimals = len(tok.split(".")[1]) if "." in tok else 0
        out.append((float(tok), decimals))
    return out


def ungrounded_numbers(text: str, allowed_text: str) -> list[str]:
    """Numbers in `text` that cannot be matched (up to rounding) to numbers in `allowed_text`."""
    allowed = [v for v, _ in _tokens(allowed_text)]
    bad = []
    for value, decimals in _tokens(text):
        tol = 0.5 * 10 ** (-decimals) + 1e-9
        if not any(abs(value - a) <= tol for a in allowed):
            bad.append(f"{value:g}")
    return bad