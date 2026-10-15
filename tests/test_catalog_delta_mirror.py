import json
import sqlite3
import zipfile
from pathlib import Path

import httpx
import pytest
from PIL import Image

from backend.catalog_delta import build_catalog_delta, delta_manifest
from backend.catalog_package import build_catalog_package, read_catalog_package, CatalogPackageError
from backend.catalog_discovery import select_catalog_delta, select_catalog_manifest
from backend.catalog_manifest import build_catalog_manifest
from backend.catalog_install import install_catalog
from backend.catalog_recovery import CatalogInstallError
from backend.database.db import initialize
from backend.catalog_download import download_catalog
from backend import download_sources as sources


def fixture_packages(tmp_path):
    source = tmp_path / 'source'
    source.mkdir()
    with sqlite3.connect(source / 'tonight.db') as db:
        db.execute('CREATE TABLE movies(id TEXT,title TEXT,year INTEGER,genres TEXT,tmdb_id INTEGER)')
        db.execute("INSERT INTO movies VALUES('old','Old',2000,'[]',101)")
    (source / 'posters').mkdir()
    Image.new('RGB', (8, 8), 'red').save(source / 'posters/old.jpg')
    base = build_catalog_package(source, tmp_path / 'base.zip', version='1.0.0', min_app_version='1.6.8',
        created_at='2026-10-10T00:00:00Z', include_media=True, media_rights_reviewed=True)
    with sqlite3.connect(source / 'tonight.db') as db:
        db.execute("UPDATE movies SET title='Updated' WHERE id='old'")
        db.execute("INSERT INTO movies VALUES('new','New',2020,'[]',202)")
    Image.new('RGB', (8, 8), 'blue').save(source / 'posters/new.jpg')
    target = build_catalog_package(source, tmp_path / 'target.zip', version='1.1.0', min_app_version='1.6.8',
        created_at='2026-10-15T00:00:00Z', include_media=True, media_rights_reviewed=True)
    delta = build_catalog_delta(base, target, tmp_path / 'delta.zip')
    def full_offer(archive, filename):
        output = build_catalog_manifest(archive, tmp_path / filename, published_at='2026-10-15T00:00:00Z')
        return select_catalog_manifest(json.loads(output.read_text()), None)
    base_offer, full = full_offer(base, 'base.json'), full_offer(target, 'full.json')
    index = {'format_version': 1, 'deltas': [delta_manifest(delta, '2026-10-15T00:00:00Z')]}
    return base, base_offer, target, full, delta, index


def test_delta_delivers_changes_and_new_images_and_preserves_personal_data(tmp_path):
    base, base_offer, target, full, delta, index = fixture_packages(tmp_path)
    with zipfile.ZipFile(delta) as archive:
        assert 'posters/new.jpg' in archive.namelist()
        assert 'posters/old.jpg' not in archive.namelist()
    offer = select_catalog_delta(index, full, '1.0.0')
    assert offer.base_version == '1.0.0'
    root = tmp_path / 'installed'
    initialize(root / 'data/tonight.db')
    install_catalog(root, base, base_offer, app_version='1.8.0')
    with sqlite3.connect(root / 'data/tonight.db') as db:
        db.execute("INSERT INTO watchlist(movie_id,saved_at,saved_by) VALUES('old','today','lera')")
    old_poster = root / 'data/posters/old.jpg'
    old_poster.write_bytes(b'custom local poster')
    install_catalog(root, delta, offer, app_version='1.8.0')
    with sqlite3.connect(root / 'data/tonight.db') as db:
        assert db.execute("SELECT value FROM app_meta WHERE key='catalog_version'").fetchone()[0] == '1.1.0'
        assert db.execute("SELECT movie_id,saved_by FROM watchlist").fetchone() == ('old', 'lera')
        assert db.execute('SELECT count(*) FROM movies').fetchone()[0] == 2
    assert old_poster.read_bytes() == b'custom local poster'
    assert (root / 'data/posters/new.jpg').is_file()
    assert select_catalog_delta(index, full, None) is full
    assert select_catalog_delta(index, full, '0.9.0') is full


def test_wrong_base_and_old_app_cannot_install_delta(tmp_path):
    _, _, _, full, delta, index = fixture_packages(tmp_path)
    offer = select_catalog_delta(index, full, '1.0.0')
    root = tmp_path / 'installed'
    initialize(root / 'data/tonight.db')
    with pytest.raises(CatalogInstallError):
        install_catalog(root, delta, offer, app_version='1.8.0')
    with sqlite3.connect(root / 'data/tonight.db') as db:
        assert db.execute('SELECT count(*) FROM movies').fetchone()[0] == 0
        assert db.execute("SELECT count(*) FROM app_meta WHERE key='catalog_version'").fetchone()[0] == 0
    with pytest.raises(CatalogPackageError):
        read_catalog_package(delta, app_version='1.7.1')


def test_delta_index_rejects_duplicate_or_untrusted_archive(tmp_path):
    _, _, _, full, _, index = fixture_packages(tmp_path)
    index['deltas'].append(index['deltas'][0].copy())
    with pytest.raises(ValueError):
        select_catalog_delta(index, full, '1.0.0')
    index['deltas'] = index['deltas'][:1]
    index['deltas'][0]['archive_url'] = 'https://example.com/unsafe.zip'
    with pytest.raises(ValueError):
        select_catalog_delta(index, full, '1.0.0')


def test_delta_downloader_accepts_only_pinned_delta_identity(tmp_path):
    _, _, _, full, delta, index = fixture_packages(tmp_path)
    offer = select_catalog_delta(index, full, '1.0.0')
    with httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(200, content=delta.read_bytes()))) as client:
        downloaded = download_catalog(offer, tmp_path / 'downloads', app_version='1.8.0', client=client)
    assert downloaded.read_bytes() == delta.read_bytes()


@pytest.fixture
def clean_mirror(monkeypatch):
    monkeypatch.delenv('TONIGHT_YANDEX_MIRROR', raising=False)
    monkeypatch.delenv('TONIGHT_DOWNLOAD_MIRROR', raising=False)
    monkeypatch.setattr(sources, '_public_mirror', {})


def test_yandex_shared_folder_resolves_file_without_credentials(clean_mirror, monkeypatch):
    monkeypatch.setenv('TONIGHT_YANDEX_MIRROR', 'https://disk.yandex.ru/d/shared-folder')
    url = sources.PREFIX + 'v1.8.0/Tonight-update-1.8.0.zip'
    def handler(request):
        assert request.url.host == 'cloud-api.yandex.net'
        assert request.url.params['path'] == '/v1.8.0/Tonight-update-1.8.0.zip'
        assert 'authorization' not in request.headers and 'cookie' not in request.headers
        return httpx.Response(200, json={'href': 'https://downloader.disk.yandex.ru/disk/file?temporary=1'})
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = sources.download_sources(url, client=client)
    assert result == ['https://downloader.disk.yandex.ru/disk/file?temporary=1', url]


@pytest.mark.parametrize('href', ['http://localhost/private', 'https://downloader.disk.yandex.ru.evil.test/file', 'https://user:pass@downloader.disk.yandex.ru/file'])
def test_yandex_untrusted_download_link_falls_back_to_github(clean_mirror, monkeypatch, href):
    monkeypatch.setenv('TONIGHT_YANDEX_MIRROR', 'https://disk.yandex.ru/d/shared-folder')
    url = sources.PREFIX + 'v1.8.0/Tonight-update-1.8.0.zip'
    with httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(200, json={'href': href}))) as client:
        assert sources.download_sources(url, client=client) == [url]


def test_public_mirror_config_can_enable_or_disable_yandex(clean_mirror):
    config = {'format_version': 1, 'kind': 'yandex-disk', 'url': 'https://disk.yandex.ru/d/shared-folder'}
    with httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(200, json=config))) as client:
        sources.refresh_public_mirror(client=client)
    assert sources._public_mirror == config
    with httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(200, json={'format_version': 1, 'kind': 'none'}))) as client:
        sources.refresh_public_mirror(client=client)
    assert sources._public_mirror == {}


def test_unavailable_https_mirror_automatically_falls_back_to_github(tmp_path, clean_mirror, monkeypatch):
    from test_app_download_resume import package
    import backend.auto_update as download
    monkeypatch.setenv('TONIGHT_DOWNLOAD_MIRROR', 'https://mirror.example/tonight')
    monkeypatch.setattr(download.time, 'sleep', lambda _: None)
    data, update = package()
    seen = []
    def handler(request):
        seen.append(request.url.host)
        return httpx.Response(404) if request.url.host == 'mirror.example' else httpx.Response(200, content=data)
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        assert download.download_update(update, tmp_path, client=client).read_bytes() == data
    assert seen == ['mirror.example', 'github.com']
