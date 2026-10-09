from __future__ import annotations

import hashlib
import json
import zipfile

import httpx
import pytest

from backend.auto_update import UpdateError, download_update, fetch_latest_update, select_update


def payload(content=b"zip", version="1.6.5"):
    name = f"Tonight-update-{version}.zip"
    return {"tag_name": f"v{version}", "draft": False, "prerelease": False, "assets": [{
        "name": name, "size": len(content), "digest": "sha256:" + hashlib.sha256(content).hexdigest(),
        "browser_download_url": f"https://github.com/vewi001/tonight/releases/download/v{version}/{name}",
    }]}


def package(tmp_path, version="1.6.5"):
    path = tmp_path / "fixture.zip"
    with zipfile.ZipFile(path, "w") as bundle:
        bundle.writestr("tonight-release.json", json.dumps({"product": "Tonight", "format": 1,
            "version": version, "files": ["Tonight.exe"]}))
        bundle.writestr("Tonight.exe", b"new program")
    return path.read_bytes()


def test_version_comparison_is_numeric_and_ignores_same_or_older():
    assert select_update(payload(version="1.6.10"), "1.6.9").version == "1.6.10"
    assert select_update(payload(), "1.6.5") is None
    assert select_update(payload(), "1.7.0") is None


@pytest.mark.parametrize("field,value", [("draft", True), ("prerelease", True), ("tag_name", "v1.6.5-rc1")])
def test_non_stable_releases_are_not_offered(field, value):
    data = payload(); data[field] = value
    assert select_update(data, "1.6.4") is None


def test_portable_only_release_is_not_an_update():
    data = payload(); data["assets"][0]["name"] = "Tonight-portable-1.6.5.zip"
    assert select_update(data, "1.6.4") is None


@pytest.mark.parametrize("field,value", [("size", 0), ("size", True), ("size", 600 * 1024 * 1024),
    ("digest", None), ("digest", "sha256:bad"),
    ("browser_download_url", "https://example.com/file.zip"),
    ("browser_download_url", "https://github.com/other/tonight/releases/download/v1.6.5/Tonight-update-1.6.5.zip")])
def test_unsafe_release_metadata_is_rejected(field, value):
    data = payload(); data["assets"][0][field] = value
    with pytest.raises(UpdateError): select_update(data, "1.6.4")


def test_check_uses_only_public_request_without_credentials():
    seen = []
    def handler(request):
        seen.append(request)
        return httpx.Response(200, json=payload())
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        assert fetch_latest_update("1.6.4", client=client).version == "1.6.5"
    assert str(seen[0].url) == "https://api.github.com/repos/vewi001/tonight/releases/latest"
    assert "authorization" not in seen[0].headers and "cookie" not in seen[0].headers


@pytest.mark.parametrize("status", [403, 429, 503])
def test_unavailable_github_has_a_simple_retryable_error(status):
    with httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(status))) as client:
        with pytest.raises(UpdateError): fetch_latest_update("1.6.4", client=client)


def test_no_published_release_is_a_normal_empty_result():
    with httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(404))) as client:
        assert fetch_latest_update("1.6.4", client=client) is None


def test_corrupt_zip_contents_fail_even_with_matching_github_hash(tmp_path):
    content = package(tmp_path).replace(b"new program", b"bad program")
    update = select_update(payload(content), "1.6.4")
    with httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(200, content=content))) as client:
        with pytest.raises(UpdateError): download_update(update, tmp_path / "Updates", client=client)
    assert not list((tmp_path / "Updates").iterdir())


def test_verified_download_accepts_github_redirect_and_valid_manifest(tmp_path):
    content = package(tmp_path); update = select_update(payload(content), "1.6.4")
    def handler(request):
        if request.url.host == "github.com":
            return httpx.Response(302, headers={"Location": "https://release-assets.githubusercontent.com/file.zip"})
        return httpx.Response(200, content=content)
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        path = download_update(update, tmp_path / "Updates", client=client)
    assert path.read_bytes() == content
    assert not list(path.parent.glob("*.part"))


@pytest.mark.parametrize("kind", ["hash", "short", "long", "manifest", "redirect", "http"])
def test_failed_download_never_leaves_installable_package(tmp_path, kind):
    content = package(tmp_path); data = payload(content); delivered = content
    if kind == "hash": data["assets"][0]["digest"] = "sha256:" + "0" * 64
    if kind == "short": delivered = content[:-1]
    if kind == "long": delivered = content + b"extra"
    if kind == "manifest":
        delivered = package(tmp_path, "1.6.6"); data = payload(delivered)
    def handler(request):
        if kind == "redirect": return httpx.Response(302, headers={"Location": "http://localhost/private"})
        return httpx.Response(503 if kind == "http" else 200, content=delivered)
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(UpdateError): download_update(select_update(data, "1.6.4"), tmp_path / "Updates", client=client)
    assert not list((tmp_path / "Updates").glob("*.zip"))
    assert not list((tmp_path / "Updates").glob("*.part"))
