"""Range parameters are built by hand, not by urlencode.

These APIs express ranges as ``date>=value``. Passing that through
``urlencode`` produces ``date%3E%3D=value`` — a different parameter name,
answered with 404. This test pins the hand-built form.
"""
import urllib.parse
from datetime import datetime, timezone

from f1verse import http


def test_range_operator_is_preserved(tmp_path, monkeypatch):
    seen = {}

    def fake_fetch(url):
        seen["url"] = url
        return "{}"

    monkeypatch.setattr(http, "_fetch", fake_fetch)
    http.enable_cache(tmp_path)
    http.get_json("https://example.test/car_data",
                  {"session_key": 1, "date>=": "2026-08-23T13:46:09+00:00"},
                  ttl=0)

    decoded = urllib.parse.unquote(seen["url"])
    assert "date>=2026-08-23T13:46:09" in decoded
    assert "date>==" not in seen["url"]      # the doubled-equals bug
    assert "session_key=1" in seen["url"]    # ordinary params still encoded


def test_retry_after_supports_seconds_dates_and_caps(monkeypatch):
    monkeypatch.setattr(http.time, "time", lambda: 1_000.0)
    future = datetime.fromtimestamp(1_010.0, timezone.utc)
    header = future.strftime("%a, %d %b %Y %H:%M:%S GMT")
    assert http._retry_delay("3.5", 0) == 3.5
    assert http._retry_delay("-5", 0) == 0
    assert http._retry_delay("999", 0) == 120
    assert http._retry_delay(header, 0) == 10
