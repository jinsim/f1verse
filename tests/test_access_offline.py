# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 jinsim <https://github.com/jinsim>

"""Access failures, lifecycle transitions and request budgets without a network."""
import json
import urllib.error
import urllib.request

import pytest

from f1verse import http
from f1verse.session import Session


@pytest.fixture(autouse=True)
def isolated(monkeypatch, tmp_path):
    monkeypatch.setattr(http, "_cache_dir", tmp_path / "cache")
    monkeypatch.setattr(http, "_request_state", {})
    monkeypatch.setattr(http, "_request_log", {})
    monkeypatch.setattr(http, "_minute_log", {})
    monkeypatch.setattr(http, "_source_headers", {})


def test_a_live_body_is_refetched_before_becoming_immutable(monkeypatch):
    bodies = iter(['[1]', '[1, 2]'])
    monkeypatch.setattr(http, "_fetch", lambda url: next(bodies))
    url = "https://example.test/laps"
    assert http.get_json(url, ttl=60) == [1]
    assert http.get_json(url, ttl=None) == [1, 2]
    assert http.get_json(url, ttl=None) == [1, 2]
    assert len(http.revisions()) == 1


def test_stale_fallback_is_visible_and_a_successful_refresh_clears_it(monkeypatch):
    url = "https://api.openf1.org/v1/laps"
    monkeypatch.setattr(http, "_fetch", lambda u: '[1]')
    http.get_json(url)
    def denied(u):
        raise http.SourceUnavailable("api.openf1.org", "authentication_required", 401)
    monkeypatch.setattr(http, "_fetch", denied)
    assert http.get_json(url, ttl=0) == [1]
    assert http.entry_meta(url)["stale_on_error"]
    assert http.source_status()["openf1"]["status"] == "authentication_required"
    http._request_state.clear()  # restart: diagnostic survives in the cache sidecar
    assert http.entry_meta(url)["stale_on_error"]
    monkeypatch.setattr(http, "_fetch", lambda u: '[2]')
    assert http.get_json(url, ttl=0) == [2]
    assert not http.entry_meta(url)["stale_on_error"]


def test_401_is_an_actionable_error_without_disclosing_request_headers(monkeypatch):
    http.configure_source("livetiming", headers={"Authorization": "Bearer secret-test"})
    def denied(*args, **kwargs):
        raise urllib.error.HTTPError("https://livetiming.formula1.com/static/", 401,
                                     "credential text must not leak", {}, None)
    monkeypatch.setattr(urllib.request.OpenerDirector, "open", denied)
    with pytest.raises(http.SourceUnavailable) as err:
        http.get_text("https://livetiming.formula1.com/static/")
    assert err.value.status == "authentication_required"
    assert "secret-test" not in str(err.value)
    assert "secret-test" not in json.dumps(http.source_status())


def test_credentials_cannot_follow_a_cross_origin_redirect():
    handler = http._CredentialRedirect()
    req = urllib.request.Request("https://livetiming.formula1.com/static/")
    with pytest.raises(http.SourceUnavailable):
        handler.redirect_request(req, None, 302, "", {}, "https://other.test/")
    with pytest.raises(ValueError):
        http.configure_source("livetiming", headers={"Authorization": "a\nb"})


def test_minute_budget_counts_retries_without_blocking_other_hosts(monkeypatch):
    monkeypatch.setitem(http._MINUTE_BUDGET, "api.openf1.org", 2)
    for _ in range(2):
        http._spend("api.openf1.org")
    with pytest.raises(http.BudgetExhausted, match="60s"):
        http._spend("api.openf1.org")
    http._spend("api.jolpi.ca")
    assert len(http._request_log["api.openf1.org"]) == 2


class Growing(Session):
    @property
    def lifecycle(self):
        return self.state


@pytest.mark.parametrize("state,force,expected", [
    ("in_progress", False, 60), ("provisional", False, 60),
    ("final", True, 0), ("final", False, None)])
def test_all_accumulating_feeds_obey_lifecycle_and_force(monkeypatch, state, force, expected):
    from f1verse.sources import openf1
    calls = {}
    def read(endpoint, ttl="auto", **kw):
        calls[endpoint] = ttl
        return []
    monkeypatch.setattr(openf1, "get", read)
    race = object.__new__(Growing)
    race.session_key, race.state = 7, state
    race._load(force=force)
    assert set(calls) == {"drivers", "laps", "position", "session_result", "race_control", "stints", "pit"}
    assert set(calls.values()) == {expected}


def test_missing_optional_feed_preserves_results_and_names_the_gap(monkeypatch):
    from f1verse.sources import openf1
    def read(endpoint, **kw):
        if endpoint == "stints":
            raise http.SourceUnavailable("api.openf1.org", "not_found", 404)
        return []
    monkeypatch.setattr(openf1, "get", read)
    race = object.__new__(Growing)
    race.session_key, race.state = 7, "final"
    race._load()
    assert race.result == []
    assert race.availability()["stints"]["status"] == "not_found"
    assert race.availability()["pit"]["status"] == "available"


def test_raw_revisable_endpoints_do_not_assume_final_without_session_age(monkeypatch):
    from f1verse.sources import openf1
    seen = []
    monkeypatch.setattr(http, "get_json", lambda url, params, ttl: seen.append(ttl) or [])
    openf1.get("session_result", session_key=1)
    openf1.get("session_result", ttl=None, session_key=1)
    assert seen == [http.TTL_PROVISIONAL, http.TTL_FOREVER]
