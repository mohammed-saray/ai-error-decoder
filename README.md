# ai-error-decoder 🩺

**Paste an AI error, get a plain-English answer: what happened, whether retrying will work, when it resets in *your* timezone, and how to fix it.**

[![CI](https://github.com/mohammed2345353/ai-error-decoder/actions/workflows/ci.yml/badge.svg)](https://github.com/mohammed2345353/ai-error-decoder/actions/workflows/ci.yml)
![Python](https://img.shields.io/badge/python-3.9%2B-blue)
![Dependencies](https://img.shields.io/badge/dependencies-0-brightgreen)
[![License: MIT](https://img.shields.io/badge/license-MIT-yellow.svg)](LICENSE)

Covers **Anthropic / Claude / Claude Code**, **OpenAI / ChatGPT / Codex** and **Google Gemini / Gemini CLI**.

```text
$ pbpaste | ai-error-decoder
🔎 Gemini: quota exhausted (429 RESOURCE_EXHAUSTED)
   provider: Google Gemini API

Gemini enforces requests/minute (RPM), tokens/minute (TPM) and requests/day (RPD) per project and per
model. The same 429 can mean 'wait a few seconds' or 'come back tomorrow'. The quota id in Details tells you which one.

Retry? ⏳ only after the quota resets

Details:
  daily reset   2026-11-15 11:00 (UTC+0300) (in 16h 12m)  (midnight Pacific Time)
  quota         GenerateRequestsPerDayPerProjectPerModel-FreeTier (per day · FREE TIER · model gemini-2.5-pro)

What to do:
  1. Read the decoded quota in Details: *PerMinute* means wait for retryDelay; *PerDay* means the daily reset at midnight Pacific.
  2. If the metric says *free_tier* while you pay: the key may belong to a different project, or billing isn't linked ...
  ...
```

## The problem

The same HTTP `429` can mean very different things:

| You see | It actually means | Retry? |
|---|---|---|
| OpenAI `429 insufficient_quota` | you're **out of credit**. It's billing, not speed | ⛔ never |
| OpenAI `429 rate_limit_exceeded` | too many tokens/requests this minute | ✅ in seconds |
| Gemini `429 RESOURCE_EXHAUSTED` + `PerMinute` | per-minute cap | ✅ after `retryDelay` |
| Gemini `429 RESOURCE_EXHAUSTED` + `PerDay` | daily cap, resets at **midnight Pacific** | ⏳ tomorrow |
| Gemini quota `limit: 0` | this model isn't on your tier/project at all | ⛔ |
| Anthropic `529 overloaded_error` | Anthropic is busy, **not your fault** | ✅ backoff |
| Anthropic `429 rate_limit_error` | your tier's RPM / input TPM / output TPM | ✅ `retry-after` |
| Claude Code "usage limit reached" | Pro/Max 5-hour or weekly window, and API credit won't help | ⏳ reset |
| Codex `usage_limit_reached` | ChatGPT plan's 5h/weekly token window | ⏳ reset |

People lose hours on this: they retry billing errors in a loop, buy API credit to fix a
subscription limit, or can't work out why a paid Gemini key still says "free tier".
This tool reads the error (JSON body, headers, or plain message) and tells you which case you're in.

## Install

```bash
pipx install git+https://github.com/mohammed2345353/ai-error-decoder
```

## Usage

```bash
ai-error-decoder '{"error":{"type":"overloaded_error","message":"Overloaded"}}'
ai-error-decoder error.log                  # a file (headers + body work best)
some-command 2>&1 | ai-error-decoder        # stdin
ai-error-decoder --json < error.txt         # for scripts and bots
ai-error-decoder --list                     # all known error types
```

Exit code `0` when the error was recognized, `2` when it wasn't.

### Use it as a library

```python
from ai_error_decoder import decode

result = decode(error_text)
if result["rule"]["retry"] == "no":
    raise SystemExit(result["rule"]["fixes"][0])
```

## What it extracts

- `retry-after` / `retry-after-ms` headers, OpenAI "Please try again in 6m0s", Gemini `RetryInfo.retryDelay`
- OpenAI "Limit 30000, Used 29000, Requested 2000" and the limit kind (TPM/RPM/RPD)
- `anthropic-ratelimit-*-remaining` and `-reset` headers
- Gemini `QuotaFailure` violations: quota id, per-minute vs per-day, free tier, model, `limit: 0`
- Claude Code's legacy `usage limit reached|<unix time>` and Codex `resets_in_seconds` / `resets_at`
- The next **midnight Pacific** (Gemini daily reset), computed with correct DST rules and no tz database needed

## Limitations

- Provider messages change. Rules are regex-based and kept in one file ([`rules.py`](src/ai_error_decoder/rules.py)), so they're easy to fix. PRs welcome.
- Subscription limits (Claude Pro/Max, ChatGPT plans) aren't published as exact numbers. The advice is practical, not official.

## Roadmap

- [ ] Browser version (paste box) on GitHub Pages
- [ ] Mistral, Groq, OpenRouter, Azure OpenAI and Bedrock errors
- [ ] Arabic and Spanish output

## Related tools in this suite

Small, dependency-free tools for people fighting AI usage limits:

| Tool | What it does |
|---|---|
| [burnrate](https://github.com/mohammed2345353/burnrate) | Forecast Claude Code / Codex limits from local logs |
| [context-diet](https://github.com/mohammed2345353/context-diet) | Find the CLAUDE.md / AGENTS.md / GEMINI.md bloat you pay for on every message |
| [ai-handoff](https://github.com/mohammed2345353/ai-handoff) | Hit a limit? Move the task to another AI with a handoff file |
| **ai-error-decoder** | Explain 429 / 529 / quota errors from Anthropic, OpenAI and Gemini |
| [ratelimit-retry](https://github.com/mohammed2345353/ratelimit-retry) | Retry that respects provider rate-limit headers (JS) |
| [chat-export-md](https://github.com/mohammed2345353/chat-export-md) | ChatGPT / Claude / Gemini exports → Markdown |
| [mcp-token-audit](https://github.com/mohammed2345353/mcp-token-audit) | Measure how many tokens each MCP server's tools cost |
| [logslim](https://github.com/mohammed2345353/logslim) | Shrink logs and stack traces before pasting them into a chat |
| [chunkwise](https://github.com/mohammed2345353/chunkwise) | Split big files into token-budgeted chunks with continuation prompts |
| [ai-reset-clock](https://github.com/mohammed2345353/ai-reset-clock) | When does my quota reset? A countdown in your timezone |

## Contributing

Got an error it doesn't recognize? Open an issue with the **redacted** error text (remove keys and org ids).
See [CONTRIBUTING.md](CONTRIBUTING.md).

## License

[MIT](LICENSE)
