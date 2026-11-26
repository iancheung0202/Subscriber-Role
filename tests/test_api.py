import asyncio
import hashlib
import hmac
import time
import types

import api


def callback(**params):
    request = types.SimpleNamespace(query_params=params)
    return asyncio.run(api.callback.__wrapped__(request)).body.decode()


def test_cancelled_sign_in_is_explained():
    page = callback(error="access_denied", state="state")
    assert "<h1>Sign-In Cancelled</h1>" in page and api.RUN_VERIFY in page


def test_missing_code_is_an_invalid_link():
    assert "<h1>Invalid Link</h1>" in callback(state="state")


def test_tampered_state_is_an_invalid_link():
    assert "<h1>Invalid Link</h1>" in callback(code="code", state="1.2.3.bad")


def signed_state(age=0):
    data = f"1_2_3_{int(time.time()) - age}"
    return f"{data}.{hmac.new(b'secret', data.encode(), hashlib.sha256).hexdigest()}"


def test_fresh_link_is_accepted_and_old_link_expires():
    assert api.verify_signature(signed_state(), "secret") == (1, 2, 3)
    old = signed_state(api.LINK_LIFETIME_SECONDS + 1)
    assert api.verify_signature(old, "secret") is None
    assert "<h1>Invalid Link</h1>" in callback(code="code", state=old)


def test_empty_user_agent_entries_match_nothing(monkeypatch):
    monkeypatch.setenv("BLOCKED_USER_AGENTS", ",curl,")
    assert api.listed("BLOCKED_USER_AGENTS", "curl/8.0")
    assert not api.listed("BLOCKED_USER_AGENTS", "mozilla/5.0")
    monkeypatch.delenv("BLOCKED_USER_AGENTS")
    assert not api.listed("BLOCKED_USER_AGENTS", "mozilla/5.0")


def test_rate_limit_uses_the_visitor_address_behind_the_proxy():
    client = types.SimpleNamespace(host="172.17.0.1")
    proxied = types.SimpleNamespace(headers={"x-real-ip": "203.0.113.9"}, client=client)
    direct = types.SimpleNamespace(headers={}, client=client)
    assert api.client_address(proxied) == "203.0.113.9"
    assert api.client_address(direct) == "172.17.0.1"


def test_description_has_no_html_tags():
    page = api.render_response("Title", 'Run <b>/verify</b> <a href="x">here</a>.')
    assert 'content="Run /verify here."' in page


def test_notice_markdown_becomes_html(monkeypatch):
    monkeypatch.setenv("SITE_NOTICE", "Hi! [Add it](https://test.local/) now.")
    page = api.render_response("Title", "Content")
    assert '<p>Hi! <a href="https://test.local/">Add it</a> now.</p>' in page
