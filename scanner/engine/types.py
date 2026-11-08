"""Engine ke shared data types. Yahan Django ya httpx import nahi hota, taaki tests aasaani se chalein."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field

# status
PASS, WARN, FAIL, INFO, UNVERIFIED = "pass", "warn", "fail", "info", "unverified"
# label: result kitna pakka hai
MEASURED, ESTIMATED = "measured", "estimated"

EFFORT_LABELS = {
    1: "~5 min",
    2: "~20 min",
    3: "1-2 hours",
    4: "half a day",
    5: "multiple days",
}


@dataclass
class Finding:
    check_id: str
    category: str  # onpage | technical | ai
    title: str
    status: str
    message: str = ""
    evidence: str = ""  # exact snippet / value jo mila (user verify kar sake)
    fix: str = ""  # ready-to-paste code ya text
    fix_note: str = ""  # fix kahan aur kaise lagana hai
    impact: int = 3  # 1..5
    effort: int = 2  # 1..5 (1 = 5 minute ka kaam)
    label: str = MEASURED  # measured | estimated | unverified
    priority: float = 0.0

    def to_dict(self) -> dict:
        d = asdict(self)
        d["effort_label"] = EFFORT_LABELS.get(self.effort, "")
        return d


@dataclass
class FetchResult:
    url: str
    final_url: str = ""
    status: int = 0
    headers: dict = field(default_factory=dict)
    text: str = ""
    chain: list = field(default_factory=list)  # [(url, status), ...]
    elapsed: float = 0.0
    size: int = 0
    truncated: bool = False
    error: str = ""
    error_kind: str = ""  # dns | unsafe | timeout | conn | redirects
