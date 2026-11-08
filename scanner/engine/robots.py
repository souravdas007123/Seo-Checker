"""Chhota robots.txt parser (sirf utna jitna checks ko chahiye)."""
from __future__ import annotations


def parse_robots(text: str):
    groups: list[dict] = []
    sitemaps: list[str] = []
    cur = None
    last_was_agent = False
    for line in text.splitlines():
        line = line.split("#", 1)[0].strip()
        if not line or ":" not in line:
            continue
        key, value = line.split(":", 1)
        key, value = key.strip().lower(), value.strip()
        if key == "user-agent":
            if cur is None or not last_was_agent:
                cur = {"agents": [], "rules": []}
                groups.append(cur)
            cur["agents"].append(value.lower())
            last_was_agent = True
        elif key in ("allow", "disallow"):
            if cur is not None:
                cur["rules"].append((key, value))
            last_was_agent = False
        elif key == "sitemap":
            sitemaps.append(value)
        else:
            last_was_agent = False
    return groups, sitemaps


def rules_for(groups: list[dict], agent: str):
    """(rules, has_specific_group). Specific group ho to wahi lagta hai, warna '*' group."""
    agent = agent.lower()
    exact = [g for g in groups if agent in g["agents"]]
    chosen = exact or [g for g in groups if "*" in g["agents"]]
    return [r for g in chosen for r in g["rules"]], bool(exact)


def root_blocked(rules) -> bool:
    disallow_all = any(k == "disallow" and v in ("/", "/*") for k, v in rules)
    allow_root = any(k == "allow" and v in ("/", "/*") for k, v in rules)
    return disallow_all and not allow_root
