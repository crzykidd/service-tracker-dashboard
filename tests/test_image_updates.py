"""Image update check (img-02): registry client, tag and digest models, the engine, the
register field, the management API, retention and export. No real network: a fake registry
is injected as the client's transport."""

import hashlib
import json
from datetime import datetime, timedelta
from urllib.parse import urlsplit

import pytest
import requests
from requests.structures import CaseInsensitiveDict

import api_keys
import image_tags
import image_update
import registry_client
from extensions import db
from image_ref import parse
from models import ImageReference, ServiceEntry
from registry_client import MANIFEST_ACCEPT, RateLimited, RegistryClient, RegistryError

D1 = "sha256:" + "a" * 64
D2 = "sha256:" + "b" * 64
D3 = "sha256:" + "c" * 64


# --- a fake registry -----------------------------------------------------------------------


class Resp:
    def __init__(self, status=200, headers=None, body=None, content=b""):
        self.status_code = status
        self.headers = CaseInsensitiveDict(headers or {})
        self._body = body
        self.content = content

    def json(self):
        if self._body is None:
            raise ValueError("no json")
        return self._body


class FakeRegistry:
    """Serves /v2 manifests and tag lists for any host. `calls` records every request."""

    def __init__(self):
        self.calls = []
        self.digests = {}        # (host, repo, tag) -> digest
        self.tags = {}           # (host, repo) -> [tags]
        self.page_size = 1000
        self.auth_hosts = set()  # hosts that demand a Bearer token
        self.token_calls = 0
        self.rate_limited = {}   # host -> Retry-After
        self.no_digest_header = set()   # hosts whose HEAD carries no Docker-Content-Digest
        self.bodies = {}         # (host, repo, tag) -> manifest body for GET
        self.fail_hosts = set()  # hosts that refuse connections
        self.not_found = set()   # (host, repo)

    def __call__(self, method, url, headers=None, params=None, timeout=None, allow_redirects=False):
        from urllib.parse import urlparse
        u = urlparse(url)
        self.calls.append({"method": method, "url": url, "host": u.hostname, "path": u.path,
                           "headers": dict(headers or {}), "params": dict(params or {}), "timeout": timeout})
        host = u.hostname
        if host in self.fail_hosts:
            raise requests.ConnectionError("boom: secret-internal-detail")
        if host in self.rate_limited:
            return Resp(429, {"Retry-After": str(self.rate_limited[host])})
        if host == "auth.example":
            self.token_calls += 1
            return Resp(200, body={"token": f"tok{self.token_calls}", "expires_in": 300})
        if host in self.auth_hosts and (headers or {}).get("Authorization", "").startswith("Bearer tok") is False:
            return Resp(401, {"WWW-Authenticate": (
                'Bearer realm="https://auth.example/token",service="reg.example",'
                'scope="repository:x:pull"')})
        parts = u.path.split("/")      # ['', 'v2', ...repo, 'manifests'|'tags', ...]
        if "manifests" in parts:
            i = parts.index("manifests")
            repo, tag = "/".join(parts[2:i]), parts[i + 1]
            if (host, repo) in self.not_found or (host, repo, tag) not in self.digests:
                return Resp(404)
            digest = self.digests[(host, repo, tag)]
            hdrs = {} if host in self.no_digest_header else {"Docker-Content-Digest": digest}
            if method == "GET":
                body = self.bodies.get((host, repo, tag), b"{}")
                return Resp(200, hdrs, content=body)
            return Resp(200, hdrs)
        if "tags" in parts:
            repo = "/".join(parts[2:parts.index("tags")])
            if (host, repo) in self.not_found or (host, repo) not in self.tags:
                return Resp(404)
            tags = self.tags[(host, repo)]
            last = (params or {}).get("last")
            start = tags.index(last) + 1 if last else 0
            n = int((params or {}).get("n", self.page_size))
            size = min(n, self.page_size)
            page = tags[start:start + size]
            headers_out = {}
            if start + size < len(tags):
                headers_out["Link"] = f'</v2/{repo}/tags/list?last={page[-1]}&n={n}>; rel="next"'
            return Resp(200, headers_out, body={"name": repo, "tags": page})
        return Resp(404)

    def count(self, method=None, path_part=None):
        return len([c for c in self.calls if (method is None or c["method"] == method)
                    and (path_part is None or path_part in c["path"])])


@pytest.fixture
def reg(monkeypatch):
    fake = FakeRegistry()
    monkeypatch.setattr(image_update, "_HTTP_OVERRIDE", fake)
    image_update.reset_state()
    yield fake
    image_update.reset_state()


def client_for(fake, now=None):
    kwargs = {"now": now} if now else {}
    return RegistryClient("service-tracker-dashboard/9.9.9", http=fake, **kwargs)


# --- registry client -----------------------------------------------------------------------


def test_head_sends_all_four_accept_types_and_the_user_agent():
    fake = FakeRegistry()
    fake.digests[("ghcr.io", "org/app", "1.0")] = D1
    assert client_for(fake).head_manifest("ghcr.io", "org/app", "1.0") == D1
    call = fake.calls[0]
    assert call["method"] == "HEAD" and call["path"] == "/v2/org/app/manifests/1.0"
    assert call["headers"]["Accept"] == MANIFEST_ACCEPT
    assert MANIFEST_ACCEPT.split(", ") == [
        "application/vnd.oci.image.index.v1+json",
        "application/vnd.docker.distribution.manifest.list.v2+json",
        "application/vnd.oci.image.manifest.v1+json",
        "application/vnd.docker.distribution.manifest.v2+json"]
    assert call["headers"]["User-Agent"] == "service-tracker-dashboard/9.9.9"
    assert call["timeout"] == (5, 10)


def test_a_multi_arch_tag_returns_the_index_digest_as_the_registry_sends_it():
    fake = FakeRegistry()
    fake.digests[("registry-1.docker.io", "library/nginx", "latest")] = D2     # the index digest
    assert client_for(fake).head_manifest("docker.io", "library/nginx", "latest") == D2


def test_docker_hub_is_mapped_to_its_api_host():
    fake = FakeRegistry()
    fake.digests[("registry-1.docker.io", "library/nginx", "1.2")] = D1
    client_for(fake).head_manifest("docker.io", "library/nginx", "1.2")
    assert fake.calls[0]["host"] == "registry-1.docker.io"
    assert registry_client.api_host("ghcr.io") == "ghcr.io"


def test_bearer_challenge_is_read_from_the_header_and_the_token_is_cached():
    fake = FakeRegistry()
    fake.auth_hosts.add("ghcr.io")
    fake.digests[("ghcr.io", "org/app", "1.0")] = D1
    fake.digests[("ghcr.io", "org/app", "2.0")] = D2
    c = client_for(fake)
    assert c.head_manifest("ghcr.io", "org/app", "1.0") == D1
    token_call = [x for x in fake.calls if x["host"] == "auth.example"][0]
    assert token_call["method"] == "GET" and token_call["path"] == "/token"
    assert token_call["params"]["service"] == "reg.example"
    assert "Authorization" not in token_call["headers"]            # anonymous
    retried = [x for x in fake.calls if x["host"] == "ghcr.io"][-1]
    assert retried["headers"]["Authorization"] == "Bearer tok1"
    assert c.head_manifest("ghcr.io", "org/app", "2.0") == D2
    assert fake.token_calls == 1                                      # cached for the scope


def test_a_token_realm_that_is_not_https_is_refused():
    def http(method, url, headers=None, params=None, timeout=None, allow_redirects=False):
        return Resp(401, {"WWW-Authenticate": 'Bearer realm="http://evil.example/token",service="x"'})

    with pytest.raises(RegistryError) as exc:
        RegistryClient(http=http).head_manifest("ghcr.io", "o/a", "1")
    assert exc.value.message == registry_client.ERR_UNEXPECTED


def test_basic_challenge_is_a_login_error():
    def http(method, url, headers=None, params=None, timeout=None, allow_redirects=False):
        return Resp(401, {"WWW-Authenticate": 'Basic realm="r"'})

    with pytest.raises(RegistryError) as exc:
        RegistryClient(http=http).head_manifest("ghcr.io", "o/a", "1")
    assert exc.value.message == registry_client.ERR_LOGIN


def test_head_without_a_digest_header_is_an_error_on_docker_hub_and_a_hashed_get_elsewhere():
    fake = FakeRegistry()
    fake.no_digest_header = {"registry-1.docker.io", "quay.io"}
    fake.digests[("registry-1.docker.io", "library/x", "1")] = D1
    with pytest.raises(RegistryError) as exc:
        client_for(fake).head_manifest("docker.io", "library/x", "1")
    assert exc.value.message == registry_client.ERR_NO_DIGEST
    assert fake.count("GET") == 0                                    # a GET counts as a Hub pull

    fake.calls.clear()
    fake.digests[("quay.io", "o/x", "1")] = D1
    fake.bodies[("quay.io", "o/x", "1")] = b'{"schemaVersion":2}'
    expected = "sha256:" + hashlib.sha256(b'{"schemaVersion":2}').hexdigest()
    assert client_for(fake).head_manifest("quay.io", "o/x", "1") == expected
    assert [c["method"] for c in fake.calls] == ["HEAD", "GET"]
    assert fake.calls[1]["headers"]["Accept"] == MANIFEST_ACCEPT


def test_tag_pagination_follows_link_headers():
    fake = FakeRegistry()
    fake.page_size = 3
    fake.tags[("ghcr.io", "o/a")] = [f"1.{i}" for i in range(8)]
    tags, truncated = client_for(fake).list_tags("ghcr.io", "o/a")
    assert tags == [f"1.{i}" for i in range(8)] and truncated is False
    assert fake.count("GET") == 3


def test_tag_pagination_is_capped_at_ten_pages():
    fake = FakeRegistry()
    fake.page_size = 2
    fake.tags[("ghcr.io", "o/a")] = [f"1.{i}" for i in range(100)]
    tags, truncated = client_for(fake).list_tags("ghcr.io", "o/a")
    assert fake.count("GET") == registry_client.MAX_TAG_PAGES == 10
    assert len(tags) == 20 and truncated is True


def test_429_honours_retry_after_and_pauses_only_that_registry():
    fake = FakeRegistry()
    fake.rate_limited["ghcr.io"] = 120
    fake.digests[("quay.io", "o/a", "1")] = D1
    c = client_for(fake, now=lambda: 1000.0)
    with pytest.raises(RateLimited) as exc:
        c.head_manifest("ghcr.io", "o/a", "1")
    assert exc.value.retry_after == 120
    assert c.paused_until("ghcr.io") == 1120.0
    n = len(fake.calls)
    with pytest.raises(RateLimited):
        c.head_manifest("ghcr.io", "o/b", "2")                        # paused: no request at all
    assert len(fake.calls) == n
    assert c.head_manifest("quay.io", "o/a", "1") == D1               # another registry is fine


def test_retry_after_parsing():
    assert registry_client.parse_retry_after("30") == 30
    assert registry_client.parse_retry_after(None) == registry_client.DEFAULT_RETRY_AFTER
    assert registry_client.parse_retry_after("junk") == registry_client.DEFAULT_RETRY_AFTER
    assert registry_client.parse_retry_after("999999999") == registry_client.MAX_RETRY_AFTER


def test_a_connection_error_is_retried_once_and_never_leaks_exception_text():
    fake = FakeRegistry()
    fake.fail_hosts.add("ghcr.io")
    with pytest.raises(RegistryError) as exc:
        client_for(fake).head_manifest("ghcr.io", "o/a", "1")
    assert fake.count() == 2
    assert exc.value.message == registry_client.ERR_UNREACHABLE
    assert "secret-internal-detail" not in str(exc.value)


def test_404_is_a_fixed_message():
    fake = FakeRegistry()
    with pytest.raises(RegistryError) as exc:
        client_for(fake).head_manifest("ghcr.io", "o/a", "9")
    assert exc.value.message == registry_client.ERR_NOT_FOUND


def test_tag_list_redirects_never_forward_the_token_to_another_host():
    seen = []

    def http(method, url, headers=None, params=None, timeout=None, allow_redirects=False):
        seen.append((url, dict(headers or {})))
        if url.startswith("https://lscr.io/"):
            if "Authorization" not in headers:
                return Resp(401, {"WWW-Authenticate": 'Bearer realm="https://auth.example/t",service="s"'})
            return Resp(302, {"Location": "https://cdn.example/tags"})
        if urlsplit(url).hostname == "auth.example":
            return Resp(200, body={"token": "secret-token"})
        return Resp(200, body={"tags": ["1.0"]})

    tags, _ = RegistryClient(http=http).list_tags("lscr.io", "linuxserver/x")
    assert tags == ["1.0"]
    cdn = [h for u, h in seen if urlsplit(u).hostname == "cdn.example"][0]
    assert "Authorization" not in cdn


# --- tag model -----------------------------------------------------------------------------


@pytest.mark.parametrize("tag,skeleton,version", [
    ("1.4.2", "N.N.N", (1, 4, 2)),
    ("v1.4.2", "vN.N.N", (1, 4, 2)),
    ("16.4-alpine", "N.N-alpine", (16, 4)),
    ("16.4-alpine3.20", "N.N-alpineN.N", (16, 4, 3, 20)),
    ("4.0.14.2939-ls263", "N.N.N.N-lsN", (4, 0, 14, 2939, 263)),
    ("1.5.0-rc1", "N.N.N-rcN", (1, 5, 0, 1)),
])
def test_the_design_table_of_tag_shapes(tag, skeleton, version):
    assert image_tags.tag_shape(tag) == (skeleton, version)


@pytest.mark.parametrize("tag", ["latest", "stable", "", None, "x" * 200 + "1"])
def test_tags_without_a_digit_or_too_long_have_no_shape(tag):
    assert image_tags.tag_shape(tag) is None


def test_candidates_share_the_skeleton_and_exclude_prereleases_and_variants():
    tags = ["1.4.2", "1.4.3", "1.5.0", "2.0.0", "2.0.0-rc1", "1.5.0-alpine", "latest", "v2.0.0", "1.3.9"]
    assert image_tags.newer_candidates("1.4.2", tags) == ["1.4.3", "1.5.0", "2.0.0"]
    # an rc runner sees later rcs (same skeleton) but not final releases
    assert image_tags.newer_candidates("1.0.0-rc1", ["1.0.0-rc2", "1.0.0", "1.1.0"]) == ["1.0.0-rc2"]


def test_variants_never_jump_and_v_prefix_is_kept():
    tags = ["16.4-alpine", "16.5-alpine", "16.5-bookworm", "17.0-alpine", "16.5"]
    assert image_tags.newer_candidates("16.4-alpine", tags) == ["16.5-alpine", "17.0-alpine"]
    assert image_tags.newer_candidates("v1.2.3", ["v1.2.4", "1.2.5"]) == ["v1.2.4"]


def test_linuxserver_build_numbers_and_calendar_versions():
    ls = ["4.0.14.2939-ls263", "4.0.14.2939-ls264", "4.0.15.1-ls1", "4.0.14.2938-ls999"]
    assert image_tags.newer_candidates("4.0.14.2939-ls263", ls) == ["4.0.14.2939-ls264", "4.0.15.1-ls1"]
    cal = ["2024.11.01", "2024.12.15", "2025.1.2", "2024.2.3"]
    assert image_tags.newer_candidates("2024.11.01", cal) == ["2024.12.15", "2025.1.2"]


def test_embedded_suffix_versions_are_compared():
    assert image_tags.newer_candidates("16.4-alpine3.20", ["16.4-alpine3.21"]) == ["16.4-alpine3.21"]


def test_candidates_are_capped_at_fifty_highest():
    tags = [f"1.{i}" for i in range(1, 120)]
    out = image_tags.newer_candidates("1.0", tags)
    assert len(out) == 50 and out[-1] == "1.119" and out[0] == "1.70"


@pytest.mark.parametrize("scope,expected,kind", [
    ("any", "2.0.0", "major"),
    ("minor", "1.9.0", "minor"),       # same first component
    ("patch", "1.4.9", "patch"),       # same first two
])
def test_scope_and_classification(scope, expected, kind):
    pool = ["1.4.3", "1.4.9", "1.9.0", "2.0.0"]
    assert image_tags.choose_latest("1.4.2", pool, scope) == (expected, kind)


def test_build_kind_and_none_in_scope():
    assert image_tags.choose_latest("4.0.14.2939-ls263", ["4.0.14.2939-ls264"], "any")[1] == "build"
    assert image_tags.choose_latest("1.4.2", ["2.0.0"], "patch") == (None, None)


def test_pattern_replaces_the_skeleton_rule():
    tags = ["1.4.2", "1.5.0", "1.5.1-beta", "2.0.0", "v3.0.0"]
    assert image_tags.newer_candidates("1.4.2", tags, r"\d+\.\d+\.\d+") == ["1.5.0", "2.0.0"]
    assert image_tags.newer_candidates("1.4.2", tags, r"1\..*") == ["1.5.0", "1.5.1-beta"]


@pytest.mark.parametrize("pattern,ok", [
    (None, True), ("", True), (r"\d+\.\d+\.\d+", True), (r"v?\d+(-alpine)?", True),
    (r"(\d{2})+", True),
    ("(", False), ("x" * 201, False),
    (r"(a+)+", False), (r"(\d+\.)+x", False), (r"(a*)*b", False), (r"(?:a|b+)*", False),
])
def test_pattern_validation(pattern, ok):
    assert (image_tags.validate_tag_pattern(pattern) is None) is ok


# --- digest model --------------------------------------------------------------------------


def test_pick_the_repo_digest_for_the_entrys_repository():
    ref = parse("ghcr.io/org/app:latest")
    digests = [f"nginx@{D1}", f"ghcr.io/org/app@{D2}", f"ghcr.io/org/other@{D3}"]
    assert image_tags.pick_running_digest(digests, ref) == D2
    assert image_tags.pick_running_digest([f"index.docker.io/library/nginx@{D1}"], "docker.io/library/nginx:1") == D1
    assert image_tags.pick_running_digest([f"nginx@{D1}"], "docker.io/library/nginx:1") == D1
    assert image_tags.pick_running_digest([f"ghcr.io/org/other@{D3}"], ref) is None
    assert image_tags.pick_running_digest([], ref) is None
    assert image_tags.pick_running_digest(["garbage"], ref) is None


@pytest.mark.parametrize("tag,policy,model", [
    ("latest", "auto", "digest"), ("stable", "auto", "digest"), ("", "auto", "digest"),
    ("16", "auto", "digest"), ("v3", "auto", "digest"), ("2024", "auto", "digest"),
    ("1.4", "auto", "tags"), ("1.4.2", "auto", "tags"), ("16.4-alpine", "auto", "tags"),
    ("2024.11.01", "auto", "tags"), ("16", "tags", "tags"), ("1.4.2", "digest", "digest"),
])
def test_model_choice(tag, policy, model):
    assert image_tags.choose_model(policy, tag) == model


def _facts(**kw):
    base = dict(image_ref="docker.io/library/nginx:latest", policy="auto", scope=None, pattern=None,
                running_digest=D1, has_image_info=True)
    base.update(kw)
    return image_tags.EntryFacts(**base)


NOW = datetime(2026, 11, 21, 12, 0)


def test_digest_states():
    ev = image_tags.evaluate
    # no running digest: an old notifier (no image_info) vs a local build (image_info, no digest)
    old = ev(_facts(running_digest=None, has_image_info=False), None)
    assert old.state == "unknown" and "notifier" in old.reason
    local = ev(_facts(running_digest=None, has_image_info=True), None)
    assert local.state == "unknown" and "local build" in local.reason
    assert ev(_facts(), None).reason == image_tags.REASON_NOT_CHECKED
    same = ev(_facts(), image_tags.RefFacts(remote_digest=D1, checked_at=NOW))
    assert same.state == "current"
    new = ev(_facts(), image_tags.RefFacts(remote_digest=D2, checked_at=NOW))
    assert (new.state, new.kind, new.latest) == ("update", "digest", "sha256:" + "b" * 12)
    err = ev(_facts(), image_tags.RefFacts(last_error="registry unreachable"))
    assert (err.state, err.reason) == ("error", "registry unreachable")
    assert ev(_facts(image_ref="docker.io/library/nginx@" + D1), None).state == "pinned"
    assert ev(_facts(policy="off"), None).state == "off"
    assert ev(_facts(image_ref=None), None).state is None


def test_tag_states_scope_pattern_and_the_rebuilt_note():
    ev = image_tags.evaluate
    base = _facts(image_ref="docker.io/library/app:1.4.2", running_digest=None, has_image_info=False)
    facts = image_tags.RefFacts(checked_at=NOW, remote_digest=None, candidates={
        "tags": ["1.4.3", "1.9.0", "2.0.0"], "tags_total": 9, "patterns": {r"1\..*": ["1.4.3", "1.9.0"]}})
    assert ev(base, facts).latest == "2.0.0"
    assert ev(base, facts, default_scope="minor").latest == "1.9.0"
    assert ev(_facts(**{**base.__dict__, "scope": "patch"}), facts).latest == "1.4.3"
    withp = ev(_facts(**{**base.__dict__, "pattern": r"1\..*"}), facts)
    assert (withp.state, withp.latest) == ("update", "1.9.0")
    pending = ev(_facts(**{**base.__dict__, "pattern": "other"}), facts)
    assert pending.state == "unknown" and pending.reason == image_tags.REASON_PATTERN_PENDING
    cur = image_tags.RefFacts(checked_at=NOW, candidates={"tags": [], "patterns": {}})
    assert ev(base, cur).state == "current"
    # rebuilt in place: still current, with a muted note (never an update)
    rebuilt = ev(_facts(**{**base.__dict__, "running_digest": D1}),
                 image_tags.RefFacts(checked_at=NOW, remote_digest=D2, candidates={"tags": []}))
    assert rebuilt.state == "current" and rebuilt.rebuilt is True
    nov = ev(_facts(image_ref="docker.io/library/app:1.4.2", policy="tags"), None)
    assert nov.state == "unknown"
    assert ev(_facts(image_ref="docker.io/library/app:stable", policy="tags"), None).reason == \
        image_tags.REASON_NO_VERSION


# --- helpers for the engine tests ----------------------------------------------------------


def enable(on=True):
    image_update.save_settings(enabled=on)
    db.session.commit()


def add_entry(name="svc", ref="docker.io/library/nginx:1.4.2", host="h1", digest=None, info=None, **kw):
    e = ServiceEntry(host=host, container_name=name, source="notifier", last_updated=datetime.now(),
                     image_ref=ref, image_running_digest=digest, image_info=info, **kw)
    db.session.add(e)
    db.session.commit()
    return e.id


def run_all(app, **plan):
    plan.setdefault("everything", True)
    return image_update.execute(app, image_update.RunPlan("test", **plan))


def entry(id_):
    return db.session.get(ServiceEntry, id_)


def refresh():
    db.session.expire_all()


# --- engine --------------------------------------------------------------------------------


def test_off_by_default_makes_no_registry_request(app, reg):
    with app.app_context():
        add_entry()
        assert image_update.effective_enabled() == (False, "default")
        assert run_all(app) is None
        assert image_update.run_scheduled(app) is None
        assert reg.calls == []


def test_env_var_wins_over_the_stored_setting(app, monkeypatch):
    with app.app_context():
        enable(False)
        monkeypatch.setenv("STD_IMAGE_UPDATE_ENABLED", "true")
        assert image_update.effective_enabled() == (True, "env")
        monkeypatch.setenv("STD_IMAGE_UPDATE_ENABLED", "no")
        enable(True)
        assert image_update.effective_enabled() == (False, "env")
        monkeypatch.setenv("STD_IMAGE_UPDATE_ENABLED", "garbage")
        assert image_update.effective_enabled() == (True, "ui")


def test_a_full_run_finds_a_newer_tag_and_a_changed_digest(app, reg):
    reg.tags[("registry-1.docker.io", "library/nginx")] = ["1.4.2", "1.4.3", "1.5.0", "latest"]
    reg.digests[("registry-1.docker.io", "library/redis", "latest")] = D2
    with app.app_context():
        enable()
        a = add_entry("web", "docker.io/library/nginx:1.4.2")
        b = add_entry("cache", "docker.io/library/redis:latest", digest=D1, info={"id": "x"})
        c = add_entry("same", "docker.io/library/redis:latest", host="h2", digest=D2, info={"id": "x"})
        summaries = run_all(app)
        assert summaries[0].provider == "registry" and summaries[0].checked == 2
        refresh()
        ea, eb, ec = entry(a), entry(b), entry(c)
        assert (ea.image_update_state, ea.image_update_latest, ea.image_update_kind) == ("update", "1.5.0", "minor")
        assert ea.image_update_provider == "registry" and ea.image_update_since is not None
        assert (eb.image_update_state, eb.image_update_kind) == ("update", "digest")
        assert ec.image_update_state == "current"
        row = ImageReference.query.filter_by(ref="docker.io/library/nginx:1.4.2").one()
        assert row.candidates["tags"] == ["1.4.3", "1.5.0"]
        assert row.candidates["tags_total"] == 4 and row.checked_at is not None
        saved = image_update.last_run()
        assert saved["refs"] == 2 and saved["updates"] == 2 and saved["checked"] == 2


def test_references_and_repositories_are_deduplicated(app, reg):
    reg.tags[("ghcr.io", "o/app")] = ["1.0.0", "1.1.0", "2.0.0"]
    reg.digests[("ghcr.io", "o/app", "1.0.0")] = D1
    reg.digests[("ghcr.io", "o/app", "1.1.0")] = D1
    with app.app_context():
        enable()
        for i in range(3):                                        # three containers, one reference
            add_entry(f"a{i}", "ghcr.io/o/app:1.0.0", host=f"h{i}", digest=D1)
        add_entry("b", "ghcr.io/o/app:1.1.0", digest=D1)          # same repository, another tag
        run_all(app)
        assert reg.count("GET", "/tags/list") == 1                # one tag list per repository
        assert reg.count("HEAD") == 2                             # one HEAD per distinct tag
        assert ImageReference.query.count() == 2


def test_since_is_kept_while_the_update_stays_and_cleared_when_it_goes(app, reg):
    reg.digests[("quay.io", "o/a", "latest")] = D2
    with app.app_context():
        enable()
        e = add_entry("x", "quay.io/o/a:latest", digest=D1, info={})
        run_all(app)
        refresh()
        first = entry(e).image_update_since
        assert first is not None
        run_all(app)
        refresh()
        assert entry(e).image_update_since == first
        reg.digests[("quay.io", "o/a", "latest")] = D1
        run_all(app)
        refresh()
        assert (entry(e).image_update_state, entry(e).image_update_since) == ("current", None)
        assert ImageReference.query.one().remote_digest_changed_at is not None


def test_unknown_entries_cost_no_request(app, reg):
    with app.app_context():
        enable()
        add_entry("old", "docker.io/library/redis:latest")        # moving tag, no running digest
        add_entry("pin", "docker.io/library/redis@" + D1)          # pinned by digest
        add_entry("off", "docker.io/library/nginx:1.4.2", image_update_policy="off")
        run_all(app)
        assert reg.calls == []
        refresh()
        states = {e.container_name: (e.image_update_state, e.image_update_detail) for e in ServiceEntry.query.all()}
        assert states["old"][0] == "unknown" and "notifier" in states["old"][1]["reason"]
        assert states["pin"][0] == "pinned" and states["off"][0] == "off"


def test_error_backoff_and_per_entry_check_now_ignores_it(app, reg):
    reg.tags[("ghcr.io", "o/app")] = ["1.0.0", "1.1.0"]
    reg.fail_hosts.add("ghcr.io")
    with app.app_context():
        enable()
        e = add_entry("x", "ghcr.io/o/app:1.0.0")
        s = run_all(app)[0]
        assert s.errors == 1
        refresh()
        row = ImageReference.query.one()
        assert row.failures == 1 and row.last_error == "registry unreachable"
        assert "boom" not in row.last_error
        assert abs((row.next_check_at - row.last_error_at) - timedelta(days=1)) < timedelta(seconds=5)
        assert entry(e).image_update_state == "error"
        # not due: the next daily run skips it (1 day = retry on the next run via the slack)
        row.next_check_at = datetime.utcnow() + timedelta(days=3)
        db.session.commit()
        n = len(reg.calls)
        assert run_all(app)[0].refs == 0 and len(reg.calls) == n
        # per-entry Check now ignores the backoff
        reg.fail_hosts.clear()
        assert run_all(app, everything=False, refs=frozenset({"ghcr.io/o/app:1.0.0"}))[0].checked == 1
        refresh()
        row = ImageReference.query.one()
        assert (row.failures, row.last_error, row.next_check_at) == (0, None, None)
        assert entry(e).image_update_state == "update"


def test_backoff_doubles_and_is_capped_at_seven_days():
    assert [image_update._backoff(n).days for n in (1, 2, 3, 4, 5, 9)] == [1, 2, 4, 7, 7, 7]


def test_a_429_pauses_the_registry_for_the_rest_of_the_run(app, reg):
    reg.rate_limited["ghcr.io"] = 7200
    with app.app_context():
        enable()
        for i in range(3):
            add_entry(f"s{i}", f"ghcr.io/o/app{i}:1.0.0")
        run_all(app)
        refresh()
        # the first request hit the limit; the rest of that registry's references were paused
        assert reg.count() <= 3
        rows = ImageReference.query.all()
        assert all(r.last_error == registry_client.ERR_RATE_LIMITED for r in rows)
        assert all(r.next_check_at - r.last_error_at >= timedelta(seconds=7000) for r in rows)


def test_the_run_budget_leaves_unfinished_references_for_next_time(app, reg, monkeypatch):
    reg.tags[("ghcr.io", "o/app")] = ["1.0.0", "1.1.0"]
    monkeypatch.setattr(image_update, "RUN_BUDGET_SECONDS", -1)
    with app.app_context():
        enable()
        add_entry("x", "ghcr.io/o/app:1.0.0")
        s = run_all(app)[0]
        assert s.skipped == 1 and reg.calls == []
        refresh()
        row = ImageReference.query.one()
        assert row.checked_at is None and row.last_error is None and row.failures == 0


def test_the_worker_pool_and_host_limits():
    assert image_update.MAX_WORKERS == 4 and registry_client.MAX_PER_HOST == 2
    assert image_update.RUN_BUDGET_SECONDS == 1800


def test_tag_pattern_candidates_are_stored_and_a_pattern_change_is_recomputed_locally(app, reg):
    reg.tags[("ghcr.io", "o/app")] = ["1.0.0", "1.1.0", "2.0.0", "2.0.0-rc1"]
    with app.app_context():
        enable()
        e = add_entry("x", "ghcr.io/o/app:1.0.0", image_tag_pattern=r"1\..*")
        run_all(app)
        refresh()
        assert entry(e).image_update_latest == "1.1.0"
        # a scope change needs no registry call
        n = len(reg.calls)
        x = entry(e)
        x.image_tag_pattern = None
        x.image_update_scope = "minor"
        image_update.recompute_entry(x)
        assert x.image_update_latest == "1.1.0" and len(reg.calls) == n
        x.image_tag_pattern = "other.*"
        ev = image_update.recompute_entry(x)
        assert ev.state == "unknown" and ev.reason == image_tags.REASON_PATTERN_PENDING


def test_tag_model_survives_a_failing_head_but_digest_model_does_not(app, reg):
    reg.tags[("ghcr.io", "o/app")] = ["1.0.0", "1.1.0"]       # no manifests registered: HEAD 404s
    with app.app_context():
        enable()
        e = add_entry("x", "ghcr.io/o/app:1.0.0", digest=D1)
        d = add_entry("y", "ghcr.io/o/other:latest", digest=D1, info={})
        run_all(app)
        refresh()
        assert entry(e).image_update_state == "update"
        assert entry(d).image_update_state == "error"


# --- throttles, nudge, first run, retention ----------------------------------------------------


def test_check_now_is_refused_while_the_check_is_off(app, reg):
    with app.app_context():
        with pytest.raises(image_update.CheckRequestError) as exc:
            image_update.request_check(app)
        assert exc.value.status == 409


def test_global_check_now_once_an_hour_and_per_reference_every_fifteen_minutes(app, reg, monkeypatch):
    clock = [1000.0]
    monkeypatch.setattr(image_update.time, "monotonic", lambda: clock[0])
    with app.app_context():
        enable()
        a = add_entry("a", "ghcr.io/o/a:1.0.0")
        add_entry("b", "ghcr.io/o/b:1.0.0")
        assert image_update.request_check(app) == 2
        clock[0] += 3599
        with pytest.raises(image_update.CheckRequestError) as exc:
            image_update.request_check(app)
        assert exc.value.status == 429 and exc.value.retry_after == 1
        clock[0] += 2
        assert image_update.request_check(app) == 2                # an hour has passed
        assert image_update.request_check(app, entry(a)) == 1
        clock[0] += 899
        with pytest.raises(image_update.CheckRequestError) as exc:
            image_update.request_check(app, entry(a))
        assert exc.value.status == 429
        clock[0] += 2
        assert image_update.request_check(app, entry(a)) == 1
        with pytest.raises(image_update.CheckRequestError) as exc:
            image_update.request_check(app, entry(add_entry("m", None)))
        assert exc.value.status == 409


def test_register_nudge_is_debounced_to_once_per_five_minutes(app, reg, monkeypatch):
    clock = [1000.0]
    monkeypatch.setattr(image_update.time, "monotonic", lambda: clock[0])
    with app.app_context():
        assert image_update.maybe_nudge(app) is False               # off: never
        enable()
        assert image_update.maybe_nudge(app) is True
        assert image_update.maybe_nudge(app) is False
        clock[0] += 301
        assert image_update.maybe_nudge(app) is True
        assert image_update._PENDING["new"] is True


def test_a_nudged_run_checks_only_never_checked_references(app, reg):
    reg.tags[("ghcr.io", "o/old")] = ["1.0.0"]
    reg.tags[("ghcr.io", "o/new")] = ["1.0.0", "1.1.0"]
    with app.app_context():
        enable()
        add_entry("old", "ghcr.io/o/old:1.0.0")
        run_all(app)
        add_entry("new", "ghcr.io/o/new:1.0.0")
        reg.calls.clear()
        run_all(app, everything=False, new=True)
        assert {c["path"] for c in reg.calls} == {"/v2/o/new/tags/list"}


def test_a_run_in_progress_keeps_the_request_pending(app, reg):
    with app.app_context():
        enable()
        add_entry()
        assert image_update._RUN_LOCK.acquire(blocking=False)
        try:
            assert run_all(app) is None
            image_update.request_check(app)
            assert image_update._PENDING["everything"] is True
        finally:
            image_update._RUN_LOCK.release()


def test_enabling_schedules_a_first_run_unless_one_ran_in_the_last_day(app, reg):
    with app.app_context():
        assert image_update.on_settings_changed(app, was_enabled=False) is False      # still off
        enable()
        assert image_update.on_settings_changed(app, was_enabled=True) is False
        assert image_update.on_settings_changed(app, was_enabled=False) is True
        assert image_update._PENDING["everything"] is True
        image_update.reset_state()
        from settings_store import KEY_IMAGE_UPDATE_LAST_RUN, set_image_update_value
        set_image_update_value(KEY_IMAGE_UPDATE_LAST_RUN, {"at": image_update._iso(datetime.utcnow())})
        db.session.commit()
        assert image_update.on_settings_changed(app, was_enabled=False) is False


def test_first_run_is_24_hours_after_the_persisted_last_run(app):
    from settings_store import KEY_IMAGE_UPDATE_LAST_RUN, set_image_update_value
    with app.app_context():
        now = datetime(2026, 11, 21, 12, 0)
        enable()
        assert image_update.first_run_time(now) == now + timedelta(seconds=image_update.FIRST_RUN_DELAY_SECONDS)
        set_image_update_value(KEY_IMAGE_UPDATE_LAST_RUN, {"at": "2026-11-21T06:00:00Z"})
        db.session.commit()
        assert image_update.first_run_time(now) == datetime(2026, 11, 22, 6, 0)
        enable(False)
        set_image_update_value(KEY_IMAGE_UPDATE_LAST_RUN, {})
        db.session.commit()
        assert image_update.first_run_time(now) == now + timedelta(hours=24)
    assert image_update.INTERVAL_HOURS == 24


def test_retention_deletes_rows_not_wanted_for_thirty_days(app):
    with app.app_context():
        now = datetime(2026, 11, 21)
        for ref, age in (("a/b:1", 31), ("a/c:1", 29)):
            db.session.add(ImageReference(ref=ref, registry_name="r", repository="x", tag="1",
                                          last_wanted_at=now - timedelta(days=age)))
        db.session.commit()
        assert image_update.prune_references(now) == 0              # off: results are kept
        enable()
        assert image_update.prune_references(now) == 1
        assert [r.ref for r in ImageReference.query.all()] == ["a/c:1"]


def test_the_retention_job_runs_the_prune(app):
    import jobs
    with app.app_context():
        enable()
        db.session.add(ImageReference(ref="a/b:1", registry_name="r", repository="x", tag="1",
                                      last_wanted_at=datetime.utcnow() - timedelta(days=40)))
        db.session.commit()
    jobs.purge_deleted_entries(app)
    with app.app_context():
        assert ImageReference.query.count() == 0


def test_a_stored_result_survives_switching_the_check_off(app, reg):
    reg.tags[("ghcr.io", "o/app")] = ["1.0.0", "1.1.0"]
    with app.app_context():
        enable()
        e = add_entry("x", "ghcr.io/o/app:1.0.0")
        run_all(app)
        enable(False)
        refresh()
        x = entry(e)
        assert x.image_update_state == "update"                     # stored
        assert image_update.effective_state(x) == "off"             # shown as off while disabled
        enable(True)
        assert image_update.effective_state(x) == "update"


# --- the register field ----------------------------------------------------------------------


@pytest.fixture
def real_resolver(monkeypatch):
    import image_utils
    import routes_api
    monkeypatch.setattr(routes_api, "resolve_image_metadata", image_utils.resolve_image_metadata)
    monkeypatch.setattr(image_utils, "fetch_icon_if_missing", lambda *a, **k: "svc.svg")


def post(register, image="nginx:latest", info="__absent__", **extra):
    body = {"image_name": image, **extra}
    if info != "__absent__":
        body["image_info"] = info
    return register(body)


def stored(app, name="svc1"):
    with app.app_context():
        e = ServiceEntry.query.filter_by(container_name=name).one()
        return (e.image_ref, e.image_running_digest, e.image_info, e.image_update_state,
                (e.image_update_detail or {}).get("reason"))


def test_register_stores_image_info_and_picks_the_matching_digest(app, register, real_resolver):
    info = {"id": "sha256:" + "1" * 64, "repo_digests": [f"quay.io/x/nginx@{D3}", f"nginx@{D1}"],
            "created": "2026-11-01T00:00:00Z", "version": "1.27.2", "revision": "abc",
            "source": "https://github.com/nginx/nginx"}
    assert post(register, info=info).status_code == 200
    ref, digest, saved, state, reason = stored(app)
    assert ref == "docker.io/library/nginx:latest" and digest == D1
    assert saved == {"id": "sha256:" + "1" * 64, "created": "2026-11-01T00:00:00Z", "version": "1.27.2",
                     "revision": "abc", "source": "https://github.com/nginx/nginx"}     # no repo_digests
    assert state == "unknown" and reason == image_tags.REASON_NOT_CHECKED


def test_register_ignores_a_non_http_source_label(app, register, real_resolver):
    assert post(register, info={"source": "git@github.com:o/r.git", "version": "1"}).status_code == 200
    assert stored(app)[2] == {"version": "1"}


def test_absent_and_null_image_info_keep_the_stored_values(app, register, real_resolver):
    post(register, info={"repo_digests": [f"nginx@{D1}"], "version": "1"})
    for kwargs in ({}, {"info": None}):
        assert post(register, **kwargs).status_code == 200
        _, digest, saved, _, _ = stored(app)
        assert digest == D1 and saved == {"version": "1"}


def test_present_image_info_replaces_the_stored_values(app, register, real_resolver):
    post(register, info={"repo_digests": [f"nginx@{D1}"], "version": "1", "revision": "r"})
    post(register, info={"repo_digests": [f"nginx@{D2}"]})
    _, digest, saved, _, _ = stored(app)
    assert digest == D2 and saved == {}                              # replaced, not merged
    post(register, info={})
    assert stored(app)[1] is None


def test_a_changed_image_without_image_info_clears_the_digest_values(app, register, real_resolver):
    post(register, info={"repo_digests": [f"nginx@{D1}"], "version": "1"})
    post(register, image="nginx:latest")                             # same image: kept
    assert stored(app)[1] == D1
    post(register, image="nginx:1.27")                               # image changed, no image_info
    _, digest, saved, _, _ = stored(app)
    assert digest is None and saved is None
    post(register, info={"repo_digests": [f"nginx@{D2}"]}, image="nginx:1.27")
    assert stored(app)[1] == D2
    post(register, info={"repo_digests": [f"nginx@{D3}"]}, image="redis:7")   # image + info: info wins
    assert stored(app)[1] is None                                    # nginx digest is not redis's


@pytest.mark.parametrize("info", [
    {"repo_digests": ["nginx@sha256:short"]},
    {"repo_digests": ["nginx@sha512:" + "a" * 64]},
    {"repo_digests": ["no-at-sign"]},
    {"repo_digests": [f"{'x' * 256}@{D1}"]},
    {"repo_digests": [f"nginx@{D1}"] * 21},
    {"surprise": "x"},
    {"version": "v" * 129},
])
def test_bad_image_info_is_a_400(register, info):
    resp = post(register, info=info)
    assert resp.status_code == 400
    assert resp.get_json()["error"] == "Invalid register payload"


def test_twenty_digests_are_accepted(register):
    assert post(register, info={"repo_digests": [f"r{i}@{D1}" for i in range(20)]}).status_code == 200


def test_an_old_payload_still_works_and_stays_unknown(app, register, real_resolver):
    assert post(register, image="nginx:latest").status_code == 200   # no image_info at all
    ref, digest, saved, state, reason = stored(app)
    assert digest is None and saved is None
    assert state == "unknown" and "notifier" in reason


def test_a_version_tag_with_an_old_notifier_is_ready_for_the_tag_model(app, register, real_resolver):
    post(register, image="nginx:1.27.2")
    assert stored(app)[3:] == ("unknown", image_tags.REASON_NOT_CHECKED)


def test_register_recomputes_from_the_stored_reference_without_the_network(app, register, real_resolver, reg):
    with app.app_context():
        enable()
        db.session.add(ImageReference(
            ref="docker.io/library/nginx:latest", registry_name="docker.io", repository="library/nginx",
            tag="latest", remote_digest=D2, checked_at=datetime.utcnow(), last_wanted_at=datetime.utcnow()))
        db.session.commit()
    post(register, info={"repo_digests": [f"nginx@{D1}"]})
    assert stored(app)[3] == "update"
    post(register, info={"repo_digests": [f"nginx@{D2}"]})
    assert stored(app)[3] == "current"
    assert reg.calls == []


def test_register_nudges_a_run_only_for_an_unchecked_reference_and_only_when_enabled(app, register,
                                                                                     real_resolver, monkeypatch):
    calls = []
    monkeypatch.setattr(image_update, "maybe_nudge", lambda a: calls.append(1))
    post(register, image="nginx:1.27.2")
    assert calls == []                           # off: never nudged
    with app.app_context():
        enable()
    post(register, image="nginx:1.27.3")
    assert calls == [1]


# --- management API ------------------------------------------------------------------------


@pytest.fixture
def keys(app):
    with app.app_context():
        _, read = api_keys.create_key("r", "read")
        _, write = api_keys.create_key("w", "write")
        db.session.commit()
    return {"Authorization": f"Bearer {read}"}, {"Authorization": f"Bearer {write}"}


def test_meta_advertises_the_features_and_the_revision_row(client):
    body = client.get("/api/v1/meta").get_json()
    assert {"image_updates", "image_info"} <= set(body["features"])
    from api_version import API_REVISION_HISTORY
    row = [r for r in API_REVISION_HISTORY if r[0] == 5]
    assert len(row) == 1 and "image_info" in row[0][2]


def test_settings_get_put_and_defaults(app, client, keys):
    read, write = keys
    body = client.get("/api/v1/settings/image-updates", headers=read).get_json()
    assert body["enabled"] is False and body["enabled_origin"] == "default"
    assert body["scope"] == "any" and body["interval_hours"] == 24
    assert body["last_run"] is None and body["next_run"] is None
    assert client.put("/api/v1/settings/image-updates", json={"enabled": True}, headers=read).status_code == 403
    r = client.put("/api/v1/settings/image-updates", json={"enabled": True, "scope": "minor"}, headers=write)
    assert r.status_code == 200 and r.get_json()["enabled"] is True and r.get_json()["scope"] == "minor"
    assert r.get_json()["enabled_origin"] == "ui"
    assert client.put("/api/v1/settings/image-updates", json={"interval_hours": 1}, headers=write).status_code == 400
    assert client.put("/api/v1/settings/image-updates", json={}, headers=write).status_code == 400
    assert client.put("/api/v1/settings/image-updates", json={"scope": "huge"}, headers=write).status_code == 400


def test_env_pinned_switch_cannot_be_changed(client, keys, monkeypatch):
    _, write = keys
    monkeypatch.setenv("STD_IMAGE_UPDATE_ENABLED", "true")
    r = client.put("/api/v1/settings/image-updates", json={"enabled": False}, headers=write)
    assert r.status_code == 409 and "STD_IMAGE_UPDATE_ENABLED" in r.get_json()["error"]
    assert client.put("/api/v1/settings/image-updates", json={"enabled": True}, headers=write).status_code == 200
    assert client.get("/api/v1/settings/image-updates", headers=write).get_json()["enabled_origin"] == "env"


def test_a_scope_change_recomputes_entries_locally(app, client, keys):
    _, write = keys
    with app.app_context():
        enable()
        e = add_entry("x", "ghcr.io/o/app:1.0.0")
        db.session.add(ImageReference(
            ref="ghcr.io/o/app:1.0.0", registry_name="ghcr.io", repository="o/app", tag="1.0.0",
            candidates={"tags": ["1.1.0", "2.0.0"], "patterns": {}}, checked_at=datetime.utcnow(),
            last_wanted_at=datetime.utcnow()))
        db.session.commit()
    client.put("/api/v1/settings/image-updates", json={"scope": "any"}, headers=write)
    client.put("/api/v1/settings/image-updates", json={"scope": "minor"}, headers=write)
    with app.app_context():
        assert entry(e).image_update_latest == "1.1.0"


def seed(app):
    with app.app_context():
        enable()
        a = add_entry("web", "ghcr.io/o/app:1.0.0", digest=None)
        b = add_entry("db", "docker.io/library/redis:latest", digest=D1, info={"version": "7"})
        m = ServiceEntry(host=None, container_name="manual", source="manual", last_updated=datetime.now())
        db.session.add(m)
        db.session.add(ImageReference(
            ref="ghcr.io/o/app:1.0.0", registry_name="ghcr.io", repository="o/app", tag="1.0.0",
            candidates={"tags": ["1.2.0"], "tags_total": 5, "patterns": {}}, checked_at=datetime.utcnow(),
            last_wanted_at=datetime.utcnow()))
        db.session.commit()
        for e in ServiceEntry.query.filter(ServiceEntry.image_ref.isnot(None)):
            image_update.recompute_entry(e)
        db.session.commit()
        return a, b, m.id


def test_entry_responses_carry_the_image_update_block(app, client, keys):
    read, _ = keys
    a, b, m = seed(app)
    block = client.get(f"/api/v1/entries/{a}", headers=read).get_json()["image_update"]
    assert block["state"] == "update" and block["latest"] == "1.2.0" and block["kind"] == "minor"
    assert block["policy"] == "auto" and block["scope"] is None and block["tag_pattern"] is None
    assert block["ref"] == "ghcr.io/o/app:1.0.0" and block["provider"] == "registry"
    assert block["checked_at"].endswith("Z") and block["since"].endswith("Z") and block["error"] is None
    assert block["model"] == "tags" and block["rebuilt"] is False
    items = {e["name"]: e for e in client.get("/api/v1/entries", headers=read).get_json()["items"]}
    assert items["web"]["image_update"]["state"] == "update"
    assert items["db"]["image_update"]["state"] == "unknown" and items["db"]["image_update"]["running_digest"] == D1
    assert items["manual"]["image_update"] is None
    detail = client.get(f"/api/v1/entries/{b}", headers=read).get_json()
    assert detail["notifier"]["image_info"] == {"version": "7"}


def test_entry_shows_off_while_the_check_is_disabled(app, client, keys):
    read, write = keys
    a, _, _ = seed(app)
    client.put("/api/v1/settings/image-updates", json={"enabled": False}, headers=write)
    assert client.get(f"/api/v1/entries/{a}", headers=read).get_json()["image_update"]["state"] == "off"
    assert client.get("/api/v1/image-updates?state=update", headers=read).get_json()["total"] == 0


def test_image_updates_list_and_state_filter(app, client, keys):
    read, _ = keys
    seed(app)
    body = client.get("/api/v1/image-updates", headers=read).get_json()
    assert body["total"] == 2 and {i["ref"] for i in body["items"]} == {
        "ghcr.io/o/app:1.0.0", "docker.io/library/redis:latest"}
    item = [i for i in body["items"] if i["ref"].split("/", 1)[0] == "ghcr.io"][0]
    assert item["entries"][0]["name"] == "web" and item["tags_total"] == 5 and item["checked_at"].endswith("Z")
    only = client.get("/api/v1/image-updates?state=update", headers=read).get_json()
    assert [i["ref"] for i in only["items"]] == ["ghcr.io/o/app:1.0.0"]
    assert client.get("/api/v1/image-updates?state=bogus", headers=read).status_code == 400
    assert client.get("/api/v1/image-updates?limit=1", headers=read).get_json()["limit"] == 1


def test_run_route_returns_202_and_throttles_with_429(app, client, keys, reg):
    read, write = keys
    a, _, m = seed(app)
    assert client.post("/api/v1/image-updates/run", headers=read).status_code == 403
    r = client.post("/api/v1/image-updates/run", headers=write)
    assert r.status_code == 202 and r.get_json()["ok"] is True and r.get_json()["queued"] == 2
    again = client.post("/api/v1/image-updates/run", headers=write)
    assert again.status_code == 429 and int(again.headers["Retry-After"]) > 0
    assert again.get_json()["details"]["retry_after_seconds"] > 0
    one = client.post("/api/v1/image-updates/run", json={"entry_id": a}, headers=write)
    assert one.status_code == 202 and one.get_json()["queued"] == 1
    assert client.post("/api/v1/image-updates/run", json={"entry_id": a}, headers=write).status_code == 429
    assert client.post("/api/v1/image-updates/run", json={"entry_id": m}, headers=write).status_code == 409
    assert client.post("/api/v1/image-updates/run", json={"entry_id": 9999}, headers=write).status_code == 404
    assert client.post("/api/v1/image-updates/run", json={"nope": 1}, headers=write).status_code == 400


def test_run_route_is_refused_while_the_check_is_off(app, client, keys, reg):
    _, write = keys
    seed(app)
    client.put("/api/v1/settings/image-updates", json={"enabled": False}, headers=write)
    assert client.post("/api/v1/image-updates/run", headers=write).status_code == 409


def test_patch_the_operator_fields_and_recompute(app, client, keys):
    _, write = keys
    a, b, m = seed(app)
    r = client.patch(f"/api/v1/entries/{a}", json={"image_update_scope": "patch"}, headers=write)
    assert r.status_code == 200 and r.get_json()["image_update"]["scope"] == "patch"
    assert r.get_json()["image_update"]["state"] == "current"          # 1.2.0 is not a patch bump
    r = client.patch(f"/api/v1/entries/{a}", json={"image_update_scope": None, "image_update_policy": "off"},
                     headers=write)
    assert r.get_json()["image_update"]["state"] == "off" and r.get_json()["image_update"]["scope"] is None
    r = client.patch(f"/api/v1/entries/{a}", json={"image_update_policy": "auto", "image_tag_pattern": r"1\.\d"},
                     headers=write)
    assert r.status_code == 200 and r.get_json()["image_update"]["tag_pattern"] == r"1\.\d"
    assert r.get_json()["image_update"]["reason"] == image_tags.REASON_PATTERN_PENDING
    r = client.patch(f"/api/v1/entries/{a}", json={"image_tag_pattern": None}, headers=write)
    assert r.get_json()["image_update"]["tag_pattern"] is None and r.get_json()["image_update"]["state"] == "update"


@pytest.mark.parametrize("body", [
    {"image_update_policy": "sometimes"},
    {"image_update_policy": None},
    {"image_update_scope": "huge"},
    {"image_tag_pattern": "("},
    {"image_tag_pattern": "(a+)+"},
    {"image_tag_pattern": "x" * 201},
])
def test_patch_rejects_bad_operator_values(app, client, keys, body):
    _, write = keys
    a, _, _ = seed(app)
    r = client.patch(f"/api/v1/entries/{a}", json=body, headers=write)
    assert r.status_code == 400
    assert any(next(iter(body)) in str(d.get("loc")) for d in r.get_json()["details"])


def test_patch_rejects_image_update_settings_on_a_manual_entry_and_computed_fields(app, client, keys):
    _, write = keys
    a, _, m = seed(app)
    assert client.patch(f"/api/v1/entries/{m}", json={"image_update_policy": "off"}, headers=write).status_code == 400
    r = client.patch(f"/api/v1/entries/{a}", json={"image_update": {"state": "update"}}, headers=write)
    assert r.status_code == 400 and "image_update" in str(r.get_json())


def test_the_new_routes_are_registered_in_the_openapi_table():
    import mgmt_openapi
    ops = {(o.method, o.path): o for o in mgmt_openapi.OPERATIONS}
    assert ops[("GET", "/image-updates")].scope == "read"
    assert ops[("POST", "/image-updates/run")].scope == "write" and ops[("POST", "/image-updates/run")].status == 202
    assert ops[("GET", "/settings/image-updates")].scope == "read"
    assert ops[("PUT", "/settings/image-updates")].scope == "write"


def test_the_spec_documents_the_image_update_block(client):
    spec = client.get("/api/v1/openapi.json").get_json()
    assert "ImageUpdateOut" in spec["components"]["schemas"]
    assert "429" in spec["paths"]["/image-updates/run"]["post"]["responses"]
    assert spec["components"]["schemas"]["EntryPatch"]["properties"]["image_tag_pattern"]


# --- export and import ---------------------------------------------------------------------


def test_operator_fields_round_trip_through_export_and_import(app, client, keys):
    read, write = keys
    with app.app_context():
        e = add_entry("x", "ghcr.io/o/app:1.0.0", image_update_policy="tags", image_update_scope="minor",
                      image_tag_pattern=r"1\..*", digest=D1, info={"version": "1"})
        add_entry("plain", "ghcr.io/o/plain:1.0.0", host="h2")
    resp = client.get("/api/v1/export?format=json", headers=read)
    doc = json.loads(resp.data)
    recs = {r["identity"]["container_name"]: r for r in doc["entries"]}
    assert (recs["x"]["image_update_policy"], recs["x"]["image_update_scope"],
            recs["x"]["image_tag_pattern"]) == ("tags", "minor", r"1\..*")
    assert not ({"image_update_policy", "image_update_scope", "image_tag_pattern"} & set(recs["plain"]))
    text = resp.get_data(as_text=True)
    assert D1 not in text and "image_running_digest" not in text and "image_update_state" not in text
    with app.app_context():
        x = entry(e)
        x.image_update_policy, x.image_update_scope, x.image_tag_pattern = "auto", None, None
        db.session.commit()
    sel = {"entry:docker:h1/x": {"apply": True}}
    plan = client.post("/api/v1/import/plan", headers=write, json={"document": doc, "selection": sel}).get_json()
    row = [r for r in plan["rows"] if r["rid"] == "entry:docker:h1/x"][0]
    assert {"image_update_policy", "image_update_scope", "image_tag_pattern"} <= {f["field"] for f in row["fields"]}
    r = client.post("/api/v1/import/apply", headers=write,
                    json={"document": doc, "selection": sel, "fingerprint": plan["fingerprint"]})
    assert r.status_code == 200, r.get_json()
    with app.app_context():
        x = entry(e)
        assert (x.image_update_policy, x.image_update_scope, x.image_tag_pattern) == ("tags", "minor", r"1\..*")
        assert x.image_running_digest == D1                          # observed values are untouched


def test_an_import_with_a_bad_pattern_is_rejected(app, client, keys):
    _, write = keys
    with app.app_context():
        add_entry("x", "ghcr.io/o/app:1.0.0")
    from tests.test_import_engine import docker_rec, minimal
    doc = minimal(entries=[docker_rec("x", image_tag_pattern="(a+)+", image_update_policy="sometimes")])
    plan = client.post("/api/v1/import/plan", headers=write, json={"document": doc}).get_json()
    text = json.dumps(plan)
    assert "image_update_policy must be one of" in text and "repeat inside a repeat" in text
