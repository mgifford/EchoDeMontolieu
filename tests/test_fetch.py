import pytest

from echo_montolieu.fetch import USER_AGENT, PoliteFetcher, StopFetching


class Resp:
    def __init__(self, status=200, body=b"", headers=None):
        self.status_code = status
        self.content = body
        self.text = body.decode("utf-8", "ignore")
        self.headers = headers or {}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(self.status_code)


class FakeSession:
    def __init__(self, routes):
        self.routes, self.calls, self.headers = routes, [], {}

    def get(self, url, headers=None, timeout=None):
        self.calls.append((url, dict(headers or {})))
        r = self.routes[url]
        return r.pop(0) if isinstance(r, list) else r


class Clock:
    def __init__(self):
        self.t, self.slept = 1000.0, []

    def now(self):
        return self.t

    def sleep(self, s):
        self.slept.append(s)
        self.t += s


def make(tmp_path, routes, delay=10):
    clock = Clock()
    session = FakeSession(routes)
    f = PoliteFetcher(tmp_path, min_delay=delay, session=session,
                      sleep=clock.sleep, clock=clock.now)
    return f, session, clock


ROBOTS = "https://a.test/robots.txt"


def test_sends_user_agent_and_waits_between_requests(tmp_path):
    f, s, clock = make(tmp_path, {
        ROBOTS: Resp(200, b"User-agent: *\nDisallow: /wp-admin/\n"),
        "https://a.test/1": Resp(200, b"one"),
        "https://a.test/2": Resp(200, b"two"),
    })
    assert f.session.headers["User-Agent"] == USER_AGENT
    f.get("https://a.test/1")
    f.get("https://a.test/2")
    # robots, page 1, page 2 are three requests: two gaps of at least 10 s
    assert len(s.calls) == 3
    assert sum(clock.slept) >= 20


def test_robots_disallow_blocks_without_fetching(tmp_path):
    f, s, _ = make(tmp_path, {ROBOTS: Resp(200, b"User-agent: *\nDisallow: /private/\n")})
    with pytest.raises(PermissionError):
        f.get("https://a.test/private/x.pdf")
    assert [c[0] for c in s.calls] == [ROBOTS]


def test_crawl_delay_raises_the_gap(tmp_path):
    f, _, clock = make(tmp_path, {
        ROBOTS: Resp(200, b"User-agent: *\nCrawl-delay: 30\n"),
        "https://a.test/1": Resp(200, b"x"),
    }, delay=5)
    f.get("https://a.test/1")
    assert max(clock.slept) >= 30 - 1e-6


def test_conditional_request_and_304(tmp_path):
    f, s, _ = make(tmp_path, {
        ROBOTS: Resp(404),
        "https://a.test/p": [Resp(200, b"body", {"ETag": '"v1"', "Last-Modified": "Mon"}),
                             Resp(304)],
    })
    first = f.get("https://a.test/p")
    second = f.get("https://a.test/p")
    assert first.status == "fetched" and second.status == "not_modified"
    assert s.calls[-1][1] == {"If-None-Match": '"v1"', "If-Modified-Since": "Mon"}
    assert second.path.read_bytes() == b"body"
    assert second.retrieved_at == first.retrieved_at  # not re-stamped on 304


def test_cached_pdf_is_not_requested_again(tmp_path):
    f, s, _ = make(tmp_path, {ROBOTS: Resp(404), "https://a.test/a.pdf": Resp(200, b"%PDF")})
    f.get("https://a.test/a.pdf", revalidate=False)
    n = len(s.calls)
    again = f.get("https://a.test/a.pdf", revalidate=False)
    assert again.status == "cached" and len(s.calls) == n


@pytest.mark.parametrize("code", [429, 503])
def test_stops_on_rate_limit_or_server_error(tmp_path, code):
    f, _, _ = make(tmp_path, {ROBOTS: Resp(404),
                              "https://a.test/p": Resp(code, headers={"Retry-After": "120"})})
    with pytest.raises(StopFetching) as e:
        f.get("https://a.test/p")
    assert "120" in str(e.value)


def test_index_survives_restart(tmp_path):
    routes = {ROBOTS: Resp(404), "https://a.test/a.pdf": Resp(200, b"%PDF")}
    f, _, _ = make(tmp_path, routes)
    f.get("https://a.test/a.pdf")
    f2, s2, _ = make(tmp_path, {ROBOTS: Resp(404)})
    assert f2.get("https://a.test/a.pdf", revalidate=False).status == "cached"
    assert all(c[0] != "https://a.test/a.pdf" for c in s2.calls)


def test_connections_are_closed_not_kept_alive(tmp_path):
    f, _, _ = make(tmp_path, {ROBOTS: Resp(404)})
    assert f.session.headers["Connection"] == "close"


def test_network_error_becomes_a_clean_stop_not_a_crash(tmp_path):
    import requests

    class Boom(FakeSession):
        def get(self, url, headers=None, timeout=None):
            if url == "https://a.test/p":
                raise requests.ConnectionError("Remote end closed connection")
            return super().get(url, headers, timeout)

    clock = Clock()
    f = PoliteFetcher(tmp_path, session=Boom({ROBOTS: Resp(404)}),
                      sleep=clock.sleep, clock=clock.now)
    with pytest.raises(StopFetching, match="network error"):
        f.get("https://a.test/p")


def test_http_validators_are_exposed_on_every_path(tmp_path):
    f, _, _ = make(tmp_path, {ROBOTS: Resp(404),
                              "https://a.test/p": [Resp(200, b"x", {"ETag": '"v1"',
                                                                    "Last-Modified": "Mon"}),
                                                   Resp(304)]})
    first = f.get("https://a.test/p")
    assert (first.etag, first.last_modified) == ('"v1"', "Mon")
    again = f.get("https://a.test/p")
    assert again.status == "not_modified" and again.etag == '"v1"'
    assert f.get("https://a.test/p", revalidate=False).last_modified == "Mon"
