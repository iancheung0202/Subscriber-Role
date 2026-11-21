import asyncio
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


def test_description_has_no_html_tags():
    page = api.render_response("Title", 'Run <b>/verify</b> <a href="x">here</a>.')
    assert 'content="Run /verify here."' in page


def test_notice_markdown_becomes_html(monkeypatch):
    monkeypatch.setenv("SITE_NOTICE", "Hi! [Add it](https://test.local/) now.")
    page = api.render_response("Title", "Content")
    assert '<p>Hi! <a href="https://test.local/">Add it</a> now.</p>' in page
