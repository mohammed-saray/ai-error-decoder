"""ai-error-decoder command-line interface."""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from . import __version__
from .decode import decode
from .rules import RULES

RETRY_TEXT = {"yes": "✅ yes, after a short wait", "after-reset": "⏳ only after the quota resets",
              "no": "⛔ no, retrying won't help; fix the cause first"}


def _when(iso: str, now: datetime) -> str:
    dt = datetime.fromisoformat(iso)
    secs = int((dt - now).total_seconds())
    local = dt.astimezone().strftime("%Y-%m-%d %H:%M (UTC%z)")
    if secs <= 0:
        return f"{local} (already passed)"
    h, rem = divmod(secs, 3600)
    m, s = divmod(rem, 60)
    rel = f"{h}h {m}m" if h else (f"{m}m {s}s" if m else f"{s}s")
    return f"{local} (in {rel})"


def render(result: dict, now: datetime) -> str:
    rule, d = result["rule"], result["details"]
    out = []
    if not rule:
        out.append("🤷 Unrecognized error. Paste the full response body (and headers if you have them).")
    else:
        out += [f"🔎 {rule['title']}", f"   provider: {rule['provider']}", "", rule["meaning"], "",
                f"Retry? {RETRY_TEXT[rule['retry']]}"]
    timing = []
    if "retry_at" in d:
        timing.append(f"retry after   {d['retry_after_s']:g}s → {_when(d['retry_at'], now)}")
    if "resets_at" in d:
        timing.append(f"resets at     {_when(d['resets_at'], now)}")
    if "resets_text" in d:
        timing.append(f"resets        {d['resets_text']} (as stated in the message)")
    if "daily_reset" in d:
        timing.append(f"daily reset   {_when(d['daily_reset'], now)}  (midnight Pacific Time)")
    for kind, ts in (d.get("resets") or {}).items():
        timing.append(f"{kind} reset  {ts}")
    for kind, n in (d.get("remaining") or {}).items():
        timing.append(f"{kind} remaining  {n}")
    if "limit" in d:
        timing.append(f"limit {d['limit']:,} · used {d['used']:,} · requested {d['requested']:,}"
                      + (f" ({d['limit_kind']})" if d.get("limit_kind") else ""))
    for q in d.get("quotas", []):
        tag = " · FREE TIER" if q["free_tier"] else ""
        model = f" · model {q['model']}" if q.get("model") else ""
        timing.append(f"quota         {q['quota_id'] or q['metric']} (per {q['window']}{tag}{model})")
    if d.get("zero_limit"):
        timing.append("limit is 0    → this model/tier isn't available to this project at all")
    if timing:
        out += ["", "Details:"] + [f"  {t}" for t in timing]
    if rule:
        out += ["", "What to do:"] + [f"  {i}. {f}" for i, f in enumerate(rule["fixes"], 1)]
    if result.get("alternatives"):
        out += ["", "Also matched: " + ", ".join(result["alternatives"])]
    return "\n".join(out)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="ai-error-decoder", description="Explain AI API and subscription errors "
                                 "(Anthropic/Claude, OpenAI/ChatGPT/Codex, Google Gemini).")
    ap.add_argument("input", nargs="*", help="error text, or a file path; reads stdin when omitted")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--list", action="store_true", help="list known error types")
    ap.add_argument("--version", action="version", version=f"ai-error-decoder {__version__}")
    a = ap.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass
    if a.list:
        for r in RULES:
            print(f"{r['id']:<28} {r['title']}")
        return 0
    if a.input:
        joined = " ".join(a.input)
        p = Path(joined) if len(joined) < 260 else None
        text = p.read_text(encoding="utf-8", errors="replace") if p and p.is_file() else joined
    else:
        if sys.stdin.isatty():
            print("Paste the error, then press Ctrl-D (Ctrl-Z Enter on Windows):", file=sys.stderr)
        text = sys.stdin.read()
    now = datetime.now(timezone.utc)
    result = decode(text, now)
    if a.json:
        rule = result["rule"]
        print(json.dumps({"id": rule["id"] if rule else None, "title": rule["title"] if rule else None,
                          "retry": rule["retry"] if rule else None, "provider": result["provider"],
                          "details": result["details"], "fixes": rule["fixes"] if rule else [],
                          "alternatives": result["alternatives"]}, indent=2, ensure_ascii=False))
    else:
        print(render(result, now))
    return 0 if result["rule"] else 2


if __name__ == "__main__":
    sys.exit(main())
