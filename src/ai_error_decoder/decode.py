"""Match error text against the rules and extract timing details."""
from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from typing import List, Optional

from .rules import RULES


# --------------------------------------------------------------------------- time helpers

def _nth_sunday(year: int, month: int, n: int) -> datetime:
    d = datetime(year, month, 1)
    d += timedelta(days=(6 - d.weekday()) % 7)
    return d + timedelta(weeks=n - 1)


def pacific_offset(utc: datetime) -> timedelta:
    """US Pacific offset (PST -8 / PDT -7) without needing tz data."""
    y = utc.year
    dst_start = _nth_sunday(y, 3, 2).replace(hour=10, tzinfo=timezone.utc)   # 2am PST = 10:00 UTC
    dst_end = _nth_sunday(y, 11, 1).replace(hour=9, tzinfo=timezone.utc)     # 2am PDT = 09:00 UTC
    return timedelta(hours=-7) if dst_start <= utc < dst_end else timedelta(hours=-8)


def next_pacific_midnight(now: Optional[datetime] = None) -> datetime:
    now = now or datetime.now(timezone.utc)
    local = now + pacific_offset(now)
    midnight_local = (local + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    guess = midnight_local - pacific_offset(now)
    return (midnight_local - pacific_offset(guess)).replace(tzinfo=timezone.utc)


DUR_RE = re.compile(r"(?:(\d+(?:\.\d+)?)h)?(?:(\d+(?:\.\d+)?)m(?!s))?(?:(\d+(?:\.\d+)?)s)?(?:(\d+(?:\.\d+)?)ms)?$")


def parse_duration(text: str) -> Optional[float]:
    """'6m0s', '1h2m3.5s', '20ms', '37s', '1.5' -> seconds."""
    text = text.strip().strip('"')
    if re.fullmatch(r"\d+(\.\d+)?", text):
        return float(text)
    m = DUR_RE.match(text)
    if not m or not any(m.groups()):
        return None
    h, mi, s, ms = (float(g) if g else 0.0 for g in m.groups())
    return h * 3600 + mi * 60 + s + ms / 1000


# --------------------------------------------------------------------------- extraction

def _find_json(text: str):
    start = text.find("{")
    while start != -1:
        depth = 0
        for i in range(start, len(text)):
            if text[i] == "{":
                depth += 1
            elif text[i] == "}":
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(text[start:i + 1])
                    except ValueError:
                        break
        start = text.find("{", start + 1)
    return None


def details(text: str, now: Optional[datetime] = None) -> dict:
    now = now or datetime.now(timezone.utc)
    d: dict = {}
    m = re.search(r"\b(4\d\d|5\d\d)\b", text)
    if m:
        d["http_status"] = int(m.group(1))
    # retry-after header
    m = re.search(r"retry-after(?:-ms)?\s*[:=]\s*\"?([\w ,:.+-]+)", text, re.I)
    if m:
        val = m.group(1).strip()
        if "retry-after-ms" in m.group(0).lower():
            d["retry_after_s"] = float(val) / 1000
        elif re.fullmatch(r"\d+(\.\d+)?", val):
            d["retry_after_s"] = float(val)
    # OpenAI "Please try again in 6m0s" / "in 20ms"
    m = re.search(r"try again in ([\d.hms]+)", text)
    if m:
        secs = parse_duration(m.group(1).rstrip("."))
        if secs is not None:
            d["retry_after_s"] = secs
    # OpenAI "Limit 30000, Used 29000, Requested 2000"
    m = re.search(r"Limit (\d+), Used (\d+), Requested (\d+)", text)
    if m:
        d["limit"], d["used"], d["requested"] = map(int, m.groups())
    m = re.search(r"on (tokens|requests) per (min|day)[^:]*", text)
    if m:
        d["limit_kind"] = f"{m.group(1)} per {'minute' if m.group(2) == 'min' else 'day'}"
    # Anthropic reset headers
    for kind in ("requests", "tokens", "input-tokens", "output-tokens"):
        m = re.search(rf"anthropic-ratelimit-{kind}-reset\s*[:=]\s*\"?([\dT:.+Z-]+)", text, re.I)
        if m:
            d.setdefault("resets", {})[kind] = m.group(1)
        m = re.search(rf"anthropic-ratelimit-{kind}-remaining\s*[:=]\s*\"?(\d+)", text, re.I)
        if m:
            d.setdefault("remaining", {})[kind] = int(m.group(1))
    # Claude Code legacy "Claude AI usage limit reached|1731600000"
    m = re.search(r"usage limit reached\|(\d{10})", text, re.I)
    if m:
        d["resets_at"] = datetime.fromtimestamp(int(m.group(1)), tz=timezone.utc).isoformat()
    # "resets at 5pm" / "resets 3:00 PM (Asia/Baghdad)" — keep as text
    m = re.search(r"resets? (?:at |on )?([0-9]{1,2}(?::[0-9]{2})?\s*(?:am|pm)?(?:\s*\([^)]+\))?)", text, re.I)
    if m and "resets_at" not in d:
        d["resets_text"] = m.group(1).strip()
    # Codex resets_in_seconds / resets_at
    m = re.search(r"\"?resets_in_seconds\"?\s*[:=]\s*(\d+)", text)
    if m:
        d["resets_at"] = (now + timedelta(seconds=int(m.group(1)))).isoformat()
    m = re.search(r"\"?resets_at\"?\s*[:=]\s*(\d{10})", text)
    if m:
        d["resets_at"] = datetime.fromtimestamp(int(m.group(1)), tz=timezone.utc).isoformat()

    body = _find_json(text)
    err = body.get("error") if isinstance(body, dict) else None
    if isinstance(err, dict):
        for k in ("type", "code", "status", "message"):
            if err.get(k) is not None:
                d[f"error_{k}"] = err[k]
        if isinstance(err.get("code"), int):
            d["http_status"] = err["code"]
        for item in err.get("details") or []:
            if not isinstance(item, dict):
                continue
            t = item.get("@type", "")
            if t.endswith("RetryInfo") and item.get("retryDelay"):
                secs = parse_duration(str(item["retryDelay"]))
                if secs is not None:
                    d["retry_after_s"] = secs
            if t.endswith("QuotaFailure"):
                quotas = []
                for v in item.get("violations") or []:
                    qid = v.get("quotaId", "")
                    metric = v.get("quotaMetric", "")
                    window = "day" if "PerDay" in qid else "minute" if "PerMinute" in qid else "unknown"
                    quotas.append({"metric": metric, "quota_id": qid, "window": window,
                                   "free_tier": "free" in (qid + metric).lower(),
                                   "limit": v.get("quotaValue"),
                                   "model": (v.get("quotaDimensions") or {}).get("model")})
                d["quotas"] = quotas
    if re.search(r"limit:\s*0\b", text) or any(str(q.get("limit")) == "0" for q in d.get("quotas", [])):
        d["zero_limit"] = True
    if "retry_after_s" in d:
        d["retry_at"] = (now + timedelta(seconds=d["retry_after_s"])).isoformat()
    if any(q["window"] == "day" for q in d.get("quotas", [])) or re.search(r"per ?day|daily", text, re.I):
        d["daily_reset"] = next_pacific_midnight(now).isoformat()
    return d


PROVIDER_HINTS = {
    "google": [r"googleapis", r"RESOURCE_EXHAUSTED", r"\bgemini\b", r"generativelanguage", r"google\.rpc",
               r"INVALID_ARGUMENT", r"FAILED_PRECONDITION", r"aistudio"],
    "anthropic": [r"anthropic", r"\bclaude\b", r"overloaded_error", r"rate_limit_error", r"x-api-key",
                  r"invalid_request_error.*prompt is too long"],
    "openai": [r"openai", r"insufficient_quota", r"x-ratelimit-", r"\bgpt-", r"\bcodex\b", r"chatgpt",
               r"rate_limit_exceeded", r"platform\.openai"],
}


def family(rule_id: str) -> str:
    if rule_id.startswith(("claude", "anthropic")):
        return "anthropic"
    if rule_id.startswith(("openai", "codex")):
        return "openai"
    if rule_id.startswith("gemini"):
        return "google"
    return "any"


def detect_providers(text: str) -> dict:
    scores = {p: sum(1 for h in hints if re.search(h, text, re.I)) for p, hints in PROVIDER_HINTS.items()}
    return {p: s for p, s in scores.items() if s}


def decode(text: str, now: Optional[datetime] = None) -> dict:
    """Return {"rule": {...} | None, "details": {...}, "provider": str|None, "alternatives": [ids]}."""
    hits: List[dict] = []
    for rule in RULES:
        if any(re.search(p, text, re.I | re.S) for p in rule["match"]):
            if any(re.search(p, text, re.I) for p in rule.get("not", [])):
                continue
            hits.append(rule)
    scores = detect_providers(text)
    provider = max(scores, key=scores.get) if scores else None
    if provider:
        # rules for the detected provider first, provider-agnostic next, others last (stable order)
        rank = {provider: 0, "any": 1}
        hits.sort(key=lambda r: rank.get(family(r["id"]), 2))
    det = details(text, now)
    rule = hits[0] if hits else None
    if rule and rule["id"] == "gemini-quota":
        windows = {q["window"] for q in det.get("quotas", [])}
        if windows == {"day"} or det.get("zero_limit"):
            rule = dict(rule, retry="after-reset" if not det.get("zero_limit") else "no")
    return {"rule": rule, "details": det, "provider": provider, "alternatives": [r["id"] for r in hits[1:4]]}
