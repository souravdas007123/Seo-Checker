"""Do scans ka tulna: kya theek hua, kya bigda, kya naya aaya."""
from __future__ import annotations

_SEV = {"pass": 0, "warn": 1, "fail": 2}


def diff_scans(prev: dict, cur: dict, include_new: bool = True) -> dict:
    """prev/cur: {check_id: (status, title)}.

    unverified/info wale checks ko 'unknown' maante hain: unse 'fixed' ya 'bigda' ka dawa nahi karte.
    """
    fixed, improved, regressed, new_issues = [], [], [], []
    for cid, (status, title) in cur.items():
        if cid in prev:
            before = prev[cid][0]
            if before not in _SEV or status not in _SEV:
                continue
            if _SEV[status] < _SEV[before]:
                (fixed if _SEV[status] == 0 else improved).append(title)
            elif _SEV[status] > _SEV[before]:
                regressed.append(title)
        elif include_new and _SEV.get(status, 0) > 0:
            new_issues.append(title)
    return {"fixed": fixed, "improved": improved, "regressed": regressed, "new_issues": new_issues}
