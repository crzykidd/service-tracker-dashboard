"""Image reference parser, its use at register, the backfill and the entry display (img-01)."""

import importlib.util
import pathlib

import pytest

import image_ref
from image_repo import effective_repo_url, image_ref_repo_url
from image_utils import resolve_image_metadata
from models import ServiceEntry

D = "sha256:" + "a" * 64


@pytest.mark.parametrize("raw,registry,repository,tag,digest,canonical", [
    ("nginx", "docker.io", "library/nginx", "latest", None, "docker.io/library/nginx:latest"),
    ("nginx:1.27", "docker.io", "library/nginx", "1.27", None, "docker.io/library/nginx:1.27"),
    ("library/nginx", "docker.io", "library/nginx", "latest", None, "docker.io/library/nginx:latest"),
    ("docker.io/nginx", "docker.io", "library/nginx", "latest", None, "docker.io/library/nginx:latest"),
    ("grafana/grafana:11", "docker.io", "grafana/grafana", "11", None, "docker.io/grafana/grafana:11"),
    ("index.docker.io/library/nginx:latest", "docker.io", "library/nginx", "latest", None,
     "docker.io/library/nginx:latest"),
    ("registry-1.docker.io/grafana/grafana", "docker.io", "grafana/grafana", "latest", None,
     "docker.io/grafana/grafana:latest"),
    ("lscr.io/linuxserver/sonarr:latest", "lscr.io", "linuxserver/sonarr", "latest", None,
     "lscr.io/linuxserver/sonarr:latest"),
    ("ghcr.io/org/team/app:1.2", "ghcr.io", "org/team/app", "1.2", None, "ghcr.io/org/team/app:1.2"),
    ("localhost:5000/app:1", "localhost:5000", "app", "1", None, "localhost:5000/app:1"),
    ("localhost/app", "localhost", "app", "latest", None, "localhost/app:latest"),
    ("registry.example.com:5000/a/b:tag", "registry.example.com:5000", "a/b", "tag", None,
     "registry.example.com:5000/a/b:tag"),
    (f"nginx@{D}", "docker.io", "library/nginx", None, D, f"docker.io/library/nginx@{D}"),
    (f"nginx:1.27@{D}", "docker.io", "library/nginx", "1.27", D, "docker.io/library/nginx:1.27"),
    ("quay.io/app:1", "quay.io", "app", "1", None, "quay.io/app:1"),
    ("GHCR.IO/Org/app", None, None, None, None, None),          # repository must be lowercase
    ("GHCR.IO/org/app:Dev", "ghcr.io", "org/app", "Dev", None, "ghcr.io/org/app:Dev"),
    ("  nginx  ", "docker.io", "library/nginx", "latest", None, "docker.io/library/nginx:latest"),
])
def test_parse(raw, registry, repository, tag, digest, canonical):
    ref = image_ref.parse(raw)
    if registry is None:
        assert ref is None
        return
    assert (ref.registry, ref.repository, ref.tag, ref.digest, ref.canonical) == (
        registry, repository, tag, digest, canonical)


@pytest.mark.parametrize("raw", [
    None, "", "   ", "a b", "nginx:", ":1", "/nginx", "nginx/", "ghcr.io//app", "nginx@sha256:xyz",
    "nginx@", "@" + D, "UPPER/case", "a//b", 42, ["nginx"], "nginx:bad tag", "-bad", "a" * 600,
])
def test_garbage_is_none_and_never_raises(raw):
    assert image_ref.parse(raw) is None


def test_owner_and_name_helpers():
    r = image_ref.parse("ghcr.io/org/team/app:1.2")
    assert (r.owner, r.name) == ("org/team", "app")
    r = image_ref.parse("quay.io/app:1")
    assert (r.owner, r.name) == (None, "app")
    r = image_ref.parse("nginx")
    assert (r.owner, r.name, r.is_docker_hub) == ("library", "nginx", True)


@pytest.mark.parametrize("raw,expected", [
    ("nginx", (None, None, "nginx", "latest")),
    ("library/nginx:1", (None, None, "nginx", "1")),
    ("grafana/grafana:11", (None, "grafana", "grafana", "11")),
    ("lscr.io/linuxserver/sonarr", ("lscr.io", "linuxserver", "sonarr", "latest")),
    ("ghcr.io/org/team/app:1.2", ("ghcr.io", "org/team", "app", "1.2")),
    ("localhost:5000/app:1", ("localhost:5000", None, "app", "1")),
    ("quay.io/app:1", ("quay.io", None, "app", "1")),
    (f"nginx@{D}", (None, None, "nginx", None)),
])
def test_resolve_image_metadata_columns(raw, expected, tmp_path):
    meta = resolve_image_metadata(image_raw=raw, image_icon_override="x.svg", image_dir=str(tmp_path),
                                  failed_icon_cache={"x.svg": __import__("datetime").datetime.now()},
                                  retry_interval=__import__("datetime").timedelta(days=1),
                                  logger=__import__("logging").getLogger("t"))
    assert (meta["registry"], meta["owner"], meta["image_name"], meta["image_tag"]) == expected
    assert meta["image_ref"] == image_ref.parse(raw).canonical


def test_nested_ghcr_and_port_links():
    assert image_ref_repo_url("ghcr.io/org/team/app:1.2") == (
        "https://github.com/users/org/packages/container/package/team%2Fapp")
    assert image_ref_repo_url("nginx:1") == "https://hub.docker.com/_/nginx"
    assert image_ref_repo_url("grafana/grafana") == "https://hub.docker.com/r/grafana/grafana"
    assert image_ref_repo_url("localhost:5000/app:1") is None
    assert image_ref_repo_url("registry.example.com:5000/a/b") is None
    assert image_ref_repo_url("quay.io/app:1") is None   # a Quay repo needs a namespace
    assert image_ref_repo_url("not a ref") is None


def test_effective_url_prefers_the_reference_then_the_columns():
    e = ServiceEntry(container_name="x", image_ref="ghcr.io/org/team/app:1",
                     image_registry="ghcr.io", image_owner="org", image_name="app")
    assert effective_repo_url(e).endswith("/package/team%2Fapp")
    e.image_ref = None
    assert effective_repo_url(e).endswith("/package/app")


# --- backfill ------------------------------------------------------------------------------

def _migration():
    path = pathlib.Path(__file__).resolve().parent.parent / "alembic/versions/a2c6e8f1b345_image_ref.py"
    spec = importlib.util.spec_from_file_location("mig_image_ref", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.mark.parametrize("cols,expected", [
    ((None, None, "nginx", None), "docker.io/library/nginx:latest"),
    ((None, "grafana", "grafana", "11"), "docker.io/grafana/grafana:11"),
    (("ghcr.io", "org", "app", "1"), "ghcr.io/org/app:1"),
    (("lscr.io", "linuxserver", "sonarr", "latest"), "lscr.io/linuxserver/sonarr:latest"),
    # mangled by the old parser: left for the next register
    ((None, "quay.io", "app", "1"), None),
    ((None, None, "localhost", "5000/app"), None),
    ((None, None, "nginx@sha256", "abc"), None),
    (("ghcr.io", None, "app", "1"), None),
    ((None, None, None, None), None),
])
def test_backfill_only_where_sound(cols, expected):
    assert _migration()._canonical(*cols) == expected


# --- register and display ------------------------------------------------------------------

def _register(client, image):
    return client.post("/api/v1/register", json={
        "container_name": "svc", "host": "h1", "image_name": image, },
        headers={"Authorization": "Bearer test-token"})


def test_register_writes_image_ref_and_overwrites_it(app, client, monkeypatch):
    import image_utils
    import routes_api
    monkeypatch.setattr(routes_api, "resolve_image_metadata", image_utils.resolve_image_metadata)
    monkeypatch.setattr(image_utils, "fetch_icon_if_missing", lambda *a, **k: "svc.svg")
    assert _register(client, "localhost:5000/app:1").status_code == 200
    with app.app_context():
        e = ServiceEntry.query.filter_by(container_name="svc").one()
        assert e.image_ref == "localhost:5000/app:1"
        assert (e.image_registry, e.image_name, e.image_tag) == ("localhost:5000", "app", "1")
    assert _register(client, "ghcr.io/org/team/app:2").status_code == 200
    with app.app_context():
        e = ServiceEntry.query.filter_by(container_name="svc").one()
        assert e.image_ref == "ghcr.io/org/team/app:2"
        assert e.image_owner == "org/team"
