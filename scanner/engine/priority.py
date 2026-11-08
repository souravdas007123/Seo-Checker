"""Score aur 'Pehle ye fix karo' priority engine."""
from __future__ import annotations

from .types import FAIL, PASS, WARN, Finding

_LOSS = {PASS: 0.0, WARN: 0.5, FAIL: 1.0}


def compute_score(findings: list[Finding]) -> int:
    """Sirf pass/warn/fail ginte hain. info aur unverified score ko na badhate na girate."""
    scored = [f for f in findings if f.status in _LOSS]
    total = sum(f.impact for f in scored)
    if not total:
        return 100
    lost = sum(f.impact * _LOSS[f.status] for f in scored)
    return round(100 * (1 - lost / total))


def assign_priority(findings: list[Finding]) -> list[Finding]:
    """priority = impact x severity x aasaani. Zyada impact + kam mehnat = pehle karo."""
    for f in findings:
        sev = _LOSS.get(f.status, 0.0)
        f.priority = round(f.impact * sev * (6 - f.effort), 2)
    return findings


def top_fixes(findings: list[Finding], n: int = 5) -> list[Finding]:
    ranked = sorted((f for f in findings if f.priority > 0), key=lambda f: -f.priority)
    return ranked[:n]
