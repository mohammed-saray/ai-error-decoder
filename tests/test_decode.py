import json
import unittest
from datetime import datetime, timedelta, timezone

from ai_error_decoder.decode import decode, next_pacific_midnight, pacific_offset, parse_duration

NOW = datetime(2026, 11, 14, 12, 0, tzinfo=timezone.utc)

GEMINI_DAILY = json.dumps({"error": {"code": 429, "status": "RESOURCE_EXHAUSTED",
    "message": "You exceeded your current quota, please check your plan and billing details.",
    "details": [
        {"@type": "type.googleapis.com/google.rpc.QuotaFailure", "violations": [{
            "quotaMetric": "generativelanguage.googleapis.com/generate_content_free_tier_requests",
            "quotaId": "GenerateRequestsPerDayPerProjectPerModel-FreeTier",
            "quotaDimensions": {"model": "gemini-2.5-pro", "location": "global"}, "quotaValue": "50"}]},
        {"@type": "type.googleapis.com/google.rpc.RetryInfo", "retryDelay": "37s"}]}})

GEMINI_MINUTE = GEMINI_DAILY.replace("PerDay", "PerMinute")


def rid(text):
    r = decode(text, NOW)["rule"]
    return r["id"] if r else None


class TimeTests(unittest.TestCase):
    def test_durations(self):
        self.assertEqual(parse_duration("6m0s"), 360)
        self.assertEqual(parse_duration("1h2m3.5s"), 3723.5)
        self.assertEqual(parse_duration("20ms"), 0.02)
        self.assertEqual(parse_duration("37s"), 37)
        self.assertEqual(parse_duration("12"), 12)
        self.assertIsNone(parse_duration("soon"))

    def test_pacific(self):
        self.assertEqual(pacific_offset(datetime(2026, 7, 1, tzinfo=timezone.utc)), timedelta(hours=-7))
        self.assertEqual(pacific_offset(datetime(2026, 12, 1, tzinfo=timezone.utc)), timedelta(hours=-8))
        # 2026-11-14 12:00 UTC = 04:00 PST -> next midnight PST = 2026-11-15 08:00 UTC
        self.assertEqual(next_pacific_midnight(NOW), datetime(2026, 11, 15, 8, 0, tzinfo=timezone.utc))
        summer = datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc)
        self.assertEqual(next_pacific_midnight(summer), datetime(2026, 7, 2, 7, 0, tzinfo=timezone.utc))


class DecodeTests(unittest.TestCase):
    def test_gemini_daily_vs_minute(self):
        r = decode(GEMINI_DAILY, NOW)
        self.assertEqual(r["rule"]["id"], "gemini-quota")
        self.assertEqual(r["provider"], "google")
        self.assertEqual(r["rule"]["retry"], "after-reset")
        q = r["details"]["quotas"][0]
        self.assertEqual((q["window"], q["free_tier"], q["model"]), ("day", True, "gemini-2.5-pro"))
        self.assertEqual(r["details"]["retry_after_s"], 37)
        self.assertIn("daily_reset", r["details"])
        m = decode(GEMINI_MINUTE, NOW)
        self.assertEqual(m["rule"]["retry"], "yes")
        self.assertEqual(m["details"]["quotas"][0]["window"], "minute")

    def test_gemini_zero_limit(self):
        r = decode(GEMINI_DAILY.replace('"50"', '"0"'), NOW)
        self.assertTrue(r["details"]["zero_limit"])
        self.assertEqual(r["rule"]["retry"], "no")

    def test_openai(self):
        self.assertEqual(rid('{"error":{"message":"You exceeded your current quota, please check your plan and '
                             'billing details.","type":"insufficient_quota","code":"insufficient_quota"}}'),
                         "openai-insufficient-quota")
        text = ("Error code: 429 - {'error': {'message': 'Rate limit reached for gpt-4o in organization org-x on "
                "tokens per min (TPM): Limit 30000, Used 29000, Requested 2000. Please try again in 6m0s.', "
                "'type': 'tokens', 'code': 'rate_limit_exceeded'}}")
        r = decode(text, NOW)
        self.assertEqual(r["rule"]["id"], "openai-rate-limit")
        self.assertEqual(r["details"]["retry_after_s"], 360)
        self.assertEqual((r["details"]["limit"], r["details"]["used"]), (30000, 29000))
        self.assertEqual(rid("This model's maximum context length is 128000 tokens."), "openai-context-length")

    def test_anthropic(self):
        self.assertEqual(rid('{"type":"error","error":{"type":"overloaded_error","message":"Overloaded"}}'),
                         "anthropic-overloaded")
        r = decode('HTTP 429\nretry-after: 15\nanthropic-ratelimit-input-tokens-remaining: 0\n'
                   '{"type":"error","error":{"type":"rate_limit_error","message":"This request would exceed '
                   'your organization\'s rate limit of 50,000 input tokens per minute."}}', NOW)
        self.assertEqual(r["rule"]["id"], "anthropic-rate-limit")
        self.assertEqual(r["details"]["retry_after_s"], 15)
        self.assertEqual(r["details"]["remaining"]["input-tokens"], 0)
        self.assertEqual(rid("Your credit balance is too low to access the Anthropic API."), "anthropic-credit-low")
        self.assertEqual(rid('{"error":{"type":"invalid_request_error","message":"prompt is too long: 210000 tokens > 200000 maximum"}}'),
                         "anthropic-prompt-too-long")

    def test_subscriptions(self):
        r = decode("Claude AI usage limit reached|1794686400", NOW)
        self.assertEqual(r["rule"]["id"], "claude-subscription-limit")
        self.assertTrue(r["details"]["resets_at"].startswith("2026-11-14"))
        self.assertEqual(rid("You've hit your limit · resets 5pm (Asia/Baghdad)"), "claude-subscription-limit")
        r = decode('{"type":"usage_limit_reached","plan_type":"plus","resets_in_seconds":3600}', NOW)
        self.assertEqual(r["rule"]["id"], "codex-usage-limit")
        self.assertEqual(r["details"]["resets_at"], (NOW + timedelta(hours=1)).isoformat())
        self.assertEqual(rid("You have exhausted your daily quota on this model. Switching to gemini-2.5-flash"),
                         "gemini-cli-daily")

    def test_location_and_generic(self):
        self.assertEqual(rid('{"error":{"code":400,"message":"User location is not supported for the API use.",'
                             '"status":"FAILED_PRECONDITION"}}'), "gemini-location")
        self.assertEqual(rid("HTTP 429 Too Many Requests"), "generic-429")
        self.assertIsNone(rid("everything is fine"))

    def test_cli(self):
        from ai_error_decoder import cli
        self.assertEqual(cli.main([GEMINI_DAILY, "--json"]), 0)
        self.assertEqual(cli.main(["hello"]), 2)
        self.assertEqual(cli.main(["--list"]), 0)


if __name__ == "__main__":
    unittest.main()
