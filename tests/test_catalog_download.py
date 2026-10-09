import hashlib
from contextlib import closing

import httpx
import pytest

from backend.auto_update import AvailableUpdate, UpdateError
from backend.catalog_download import download_catalog
from backend.catalog_package import build_catalog_package
from backend.database.db import connect, initialize


def content(tmp_path,version='1.0.0'):
    data = tmp_path/'source'
    initialize(data/'tonight.db')
    with closing(connect(data/'tonight.db')) as db:
        db.execute("INSERT OR IGNORE INTO movies(id,title,year,genres) VALUES('one','Film',2020,'[]')")
        db.commit()
    path = build_catalog_package(data,tmp_path/f'fixture-{version}.zip',version=version,
                                 min_app_version='1.6.6',created_at='2026-10-09T18:00:00Z')
    return path.read_bytes()


def update(data):
    name = 'Tonight-catalog-1.0.0.zip'
    return AvailableUpdate('1.0.0',name,len(data),hashlib.sha256(data).hexdigest(),
                           'https://github.com/vewi001/tonight/releases/download/catalog-v1.0.0/'+name)


def test_incompatible_download_exposes_only_a_validated_required_app_version(tmp_path):
    from backend.catalog_download import CatalogCompatibilityUpdateError
    data = content(tmp_path)
    with httpx.Client(transport=httpx.MockTransport(lambda request:httpx.Response(200,content=data))) as client:
        with pytest.raises(CatalogCompatibilityUpdateError) as error:
            download_catalog(update(data),tmp_path/'downloads',app_version='1.6.5',client=client)
    assert error.value.minimum == '1.6.6'
    assert not list((tmp_path/'downloads').iterdir())


def test_wrong_digest_has_a_typed_safe_retry_reason(tmp_path):
    from backend.catalog_download import CatalogIntegrityUpdateError
    data = content(tmp_path)
    candidate = update(data)
    candidate = AvailableUpdate(candidate.version,candidate.name,candidate.size,'0'*64,candidate.url)
    with httpx.Client(transport=httpx.MockTransport(lambda request:httpx.Response(200,content=data))) as client:
        with pytest.raises(CatalogIntegrityUpdateError):
            download_catalog(candidate,tmp_path/'downloads',app_version='1.6.6',client=client)
    assert not list((tmp_path/'downloads').iterdir())


def test_verified_catalog_download_redirect_and_no_credentials(tmp_path):
    data = content(tmp_path)
    seen = []
    def handler(request):
        seen.append(request)
        if request.url.host=='github.com':
            return httpx.Response(302,headers={'Location':'https://release-assets.githubusercontent.com/catalog.zip'})
        return httpx.Response(200,content=data)
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = download_catalog(update(data),tmp_path/'downloads',app_version='1.6.6',client=client)
    assert result.read_bytes()==data
    assert list(result.parent.iterdir())==[result]
    assert all('authorization' not in item.headers and 'cookie' not in item.headers for item in seen)


@pytest.mark.parametrize('failure',['hash','short','long','version','compatibility','redirect','http','zip'])
def test_failed_catalog_download_never_leaves_installable_file(tmp_path,failure):
    data = content(tmp_path,version='2.0.0' if failure=='version' else '1.0.0')
    selected = update(data)
    if failure=='hash':
        selected = AvailableUpdate(selected.version,selected.name,selected.size,'0'*64,selected.url)
    delivered = data[:-1] if failure=='short' else data+b'extra' if failure=='long' else data
    if failure=='zip':
        delivered = b'not a ZIP'
        selected = update(delivered)
    def handler(request):
        if failure=='redirect':
            return httpx.Response(302,headers={'Location':'http://localhost/private'})
        return httpx.Response(503 if failure=='http' else 200,content=delivered)
    destination = tmp_path/'downloads'
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(UpdateError):
            download_catalog(selected,destination,app_version='1.6.5' if failure=='compatibility' else '1.6.6',client=client)
    assert not list(destination.iterdir())


def test_existing_output_is_preserved_and_invalid_source_never_requested(tmp_path):
    data = content(tmp_path)
    selected = update(data)
    destination = tmp_path/'downloads'
    destination.mkdir()
    old = destination/selected.name
    old.write_bytes(b'keep')
    requested = []
    with httpx.Client(transport=httpx.MockTransport(lambda request: requested.append(request))) as client:
        with pytest.raises(UpdateError):
            download_catalog(selected,destination,app_version='1.6.6',client=client)
        with pytest.raises(UpdateError):
            download_catalog(AvailableUpdate('1.0.0','../outside',1,'a'*64,'https://example.com/a'),
                             destination,app_version='1.6.6',client=client)
    assert old.read_bytes()==b'keep' and not requested


def test_linked_download_directory_is_rejected_before_network_or_write(tmp_path,monkeypatch):
    import backend.catalog_download as download
    destination = tmp_path/'linked'
    monkeypatch.setattr(download,'_is_link',lambda path:path==destination)
    requested = []
    with httpx.Client(transport=httpx.MockTransport(lambda request: requested.append(request))) as client:
        with pytest.raises(UpdateError):
            download_catalog(update(b'zip'),destination,app_version='1.6.6',client=client)
    assert not destination.exists() and not requested
