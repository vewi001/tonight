import hashlib
import json

import httpx
import pytest

from backend.auto_update import UpdateError
import backend.catalog_discovery as discovery
import backend.catalog_download as download
from tests.test_catalog_download import content, update


def manifest(data):
    candidate = update(data)
    return dict(format_version=1,catalog_version=candidate.version,min_app_version='1.6.6',
                archive_url=candidate.url,size_bytes=len(data),sha256=candidate.sha256,
                published_at='2026-10-14T00:00:00Z')


def test_manifest_first_never_calls_api(tmp_path):
    data = content(tmp_path)
    seen = []
    def handler(request):
        seen.append(request)
        assert request.url.host=='raw.githubusercontent.com'
        return httpx.Response(200,json=manifest(data))
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = discovery.fetch_catalog_update(None,client=client)
        assert result.min_app_version=='1.6.6'
        assert discovery.fetch_catalog_update('1.0.0',client=client) is None
    assert len(seen)==2


@pytest.mark.parametrize('change',[{'format_version':True},{'size_bytes':True},{'sha256':'bad'},
    {'archive_url':'https://evil.example/a'},{'min_app_version':'01.0.0'},
    {'published_at':'today'},{'secret':'never allowed'}])
def test_bad_manifest_is_error_without_api(tmp_path,change):
    value = manifest(content(tmp_path)); value.update(change)
    seen = []
    with httpx.Client(transport=httpx.MockTransport(lambda r:seen.append(r) or httpx.Response(200,json=value))) as client:
        with pytest.raises(UpdateError):
            discovery.fetch_catalog_update(None,client=client)
    assert len(seen)==1


@pytest.mark.parametrize('body',[b'{"format_version":1,"format_version":1}',b'x'*16385,b'[]'])
def test_bounded_unique_manifest(body):
    with httpx.Client(transport=httpx.MockTransport(lambda r:httpx.Response(200,content=body))) as client:
        with pytest.raises(UpdateError): discovery.fetch_catalog_update(None,client=client)


def test_only_404_uses_api_fallback():
    from tests.test_catalog_discovery import release
    seen = []
    def handler(request):
        seen.append(request.url.host)
        return httpx.Response(404) if len(seen)==1 else httpx.Response(200,json=[release()])
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        assert discovery.fetch_catalog_update(None,client=client).version=='1.0.0'
    assert seen==['raw.githubusercontent.com','api.github.com']


@pytest.mark.parametrize('status',[403,429,503,302])
def test_manifest_network_failure_never_uses_api(status):
    seen=[]
    with httpx.Client(transport=httpx.MockTransport(lambda r:seen.append(r) or httpx.Response(status))) as client:
        with pytest.raises(UpdateError): discovery.fetch_catalog_update(None,client=client)
    assert len(seen)==1


class Broken(httpx.SyncByteStream):
    def __init__(self,data): self.data=data
    def __iter__(self):
        yield self.data
        raise httpx.ReadError('synthetic network failure')


def test_interrupted_stream_resumes_with_range(tmp_path,monkeypatch):
    data=content(tmp_path); prefix=data[:120]
    monkeypatch.setattr(download.time,'sleep',lambda _:None)
    seen=[]
    def handler(request):
        seen.append(request)
        if len(seen)==1: return httpx.Response(200,stream=Broken(prefix))
        assert request.headers['range']=='bytes=120-'
        return httpx.Response(206,headers={'Content-Range':f'bytes 120-{len(data)-1}/{len(data)}'},content=data[120:])
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result=download.download_catalog(update(data),tmp_path/'downloads',app_version='1.6.7',client=client)
    assert result.read_bytes()==data and len(seen)==2


def test_partial_survives_exhaustion_and_fresh_call(tmp_path,monkeypatch):
    data=content(tmp_path)
    monkeypatch.setattr(download.time,'sleep',lambda _:None)
    count=[0]
    def handler(request):
        count[0]+=1
        return httpx.Response(200,stream=Broken(data[:120])) if count[0]==1 else httpx.Response(503)
    destination=tmp_path/'downloads'
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(download.CatalogDownloadInterrupted):
            download.download_catalog(update(data),destination,app_version='1.6.7',client=client)
    assert not list(destination.glob('*.zip'))
    assert list(destination.glob('*.part'))[0].read_bytes()==data[:120]
    def resume(request):
        assert request.headers['range']=='bytes=120-'
        return httpx.Response(206,headers={'Content-Range':f'bytes 120-{len(data)-1}/{len(data)}'},content=data[120:])
    with httpx.Client(transport=httpx.MockTransport(resume)) as client:
        assert download.download_catalog(update(data),destination,app_version='1.6.7',client=client).read_bytes()==data


def test_range_ignored_restarts_without_appending(tmp_path,monkeypatch):
    data=content(tmp_path); seen=[]
    monkeypatch.setattr(download.time,'sleep',lambda _:None)
    def handler(request):
        seen.append(request)
        return httpx.Response(200,stream=Broken(data[:120])) if len(seen)==1 else httpx.Response(200,content=data)
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        assert download.download_catalog(update(data),tmp_path/'downloads',app_version='1.6.7',client=client).read_bytes()==data
    assert 'range' in seen[1].headers


@pytest.mark.parametrize('range_header',['bytes 119-999/1000','bytes 120-999/*','bad'])
def test_invalid_content_range_never_publishes(tmp_path,monkeypatch,range_header):
    data=content(tmp_path); seen=[]
    monkeypatch.setattr(download.time,'sleep',lambda _:None)
    def handler(request):
        seen.append(request)
        return httpx.Response(200,stream=Broken(data[:120])) if len(seen)==1 else httpx.Response(206,headers={'Content-Range':range_header},content=data[120:])
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(download.CatalogIntegrityUpdateError):
            download.download_catalog(update(data),tmp_path/'downloads',app_version='1.6.7',client=client)
    assert not list((tmp_path/'downloads').iterdir())


def test_manager_retry_reuses_destination_and_safe_progress(tmp_path,monkeypatch):
    import backend.catalog_manager as module
    from tests.test_catalog_manager import fixture
    manager,candidate=fixture(tmp_path,monkeypatch)
    destinations=[]
    def interrupted(update,destination,**kwargs):
        destinations.append(destination)
        raise download.CatalogDownloadInterrupted(50,100)
    monkeypatch.setattr(module,'download_catalog',interrupted)
    manager.check()
    status=manager.run_reserved(manager.reserve_download())
    assert status['download_bytes']==50 and status['can_resume']
    assert 'Можно продолжить' in status['message']
    manager.run_reserved(manager.reserve_download())
    assert destinations[0]==destinations[1]


def test_manifest_compatibility_checked_before_download(tmp_path,monkeypatch):
    import backend.catalog_manager as module
    from backend.database.db import initialize
    initialize(tmp_path/'data/tonight.db')
    candidate=discovery.select_catalog_manifest(dict(manifest(b'x'),min_app_version='9.0.0'),None)
    monkeypatch.setattr(module,'fetch_catalog_update',lambda current:candidate)
    manager=module.CatalogUpdateManager(tmp_path,'1.6.7')
    status=manager.check()
    assert status['phase']=='error' and status['available_version'] is None
    assert '9.0.0' in status['message']


def test_manifest_and_zip_minimum_must_agree(tmp_path):
    data=content(tmp_path)
    candidate=discovery.select_catalog_manifest(dict(manifest(data),min_app_version='1.6.5'),None)
    with httpx.Client(transport=httpx.MockTransport(lambda r:httpx.Response(200,content=data))) as client:
        with pytest.raises(download.CatalogIntegrityUpdateError):
            download.download_catalog(candidate,tmp_path/'downloads',app_version='1.6.7',client=client)


def test_complete_partial_verified_without_network(tmp_path):
    data=content(tmp_path); candidate=update(data)
    destination=tmp_path/'downloads'; destination.mkdir()
    (destination/(candidate.sha256+'.part')).write_bytes(data)
    with httpx.Client(transport=httpx.MockTransport(lambda r:pytest.fail('unexpected network'))) as client:
        assert download.download_catalog(candidate,destination,app_version='1.6.7',client=client).read_bytes()==data


def test_check_and_failed_download_leave_db_env_venv_unchanged(tmp_path,monkeypatch):
    from tests.test_catalog_manager import fixture
    import backend.catalog_manager as module
    manager,candidate=fixture(tmp_path,monkeypatch)
    (tmp_path/'.env').write_text('SYNTHETIC_MARKER=keep',encoding='utf-8')
    (tmp_path/'.venv').mkdir(); (tmp_path/'.venv/marker').write_bytes(b'keep')
    protected=[tmp_path/'data/tonight.db',tmp_path/'.env',tmp_path/'.venv/marker']
    before={p:p.read_bytes() for p in protected}
    def fail(*a,**k): raise download.CatalogDownloadInterrupted(40,100)
    monkeypatch.setattr(module,'download_catalog',fail)
    manager.check(); manager.run_reserved(manager.reserve_download())
    assert all(p.read_bytes()==value for p,value in before.items())


def test_check_handles_unsafe_resume_path(tmp_path,monkeypatch):
    from tests.test_catalog_manager import fixture
    import backend.catalog_manager as module
    manager,candidate=fixture(tmp_path,monkeypatch)
    monkeypatch.setattr(module,'checked',lambda *a:(_ for _ in ()).throw(OSError('private path')))
    status=manager.check()
    assert status['phase']=='error' and status['available_version'] is None
    assert 'private' not in str(status)


def test_restart_after_link_promotion_reconciles_only_own_pair(tmp_path):
    import os
    data=content(tmp_path); candidate=update(data)
    destination=tmp_path/'downloads'; destination.mkdir()
    partial=destination/(candidate.sha256+'.part'); partial.write_bytes(data)
    target=destination/candidate.name; os.link(partial,target)
    with httpx.Client(transport=httpx.MockTransport(lambda r:pytest.fail('unexpected network'))) as client:
        assert download.download_catalog(candidate,destination,app_version='1.6.7',client=client)==target
    assert target.read_bytes()==data and not partial.exists()


def test_manifest_builder_matches_verified_archive(tmp_path):
    from backend.catalog_manifest import build_catalog_manifest
    data=content(tmp_path)
    archive=tmp_path/'source.zip'; archive.write_bytes(data)
    destination=tmp_path/'latest.json'
    build_catalog_manifest(archive,destination,published_at='2026-10-14T00:00:00Z')
    assert json.loads(destination.read_bytes())==manifest(data)
    with pytest.raises(FileExistsError):
        build_catalog_manifest(archive,destination,published_at='2026-10-14T00:00:00Z')


def test_installer_preserves_manifest_minimum_and_rejects_disagreement(tmp_path):
    from backend.catalog_install import install_catalog
    from backend.catalog_recovery import CatalogInstallError
    from backend.database.db import initialize
    data=content(tmp_path)
    candidate=discovery.select_catalog_manifest(dict(manifest(data),min_app_version='1.6.5'),None)
    root=tmp_path/'app'; root.mkdir(); initialize(root/'data/tonight.db')
    archive=tmp_path/'archive.zip'; archive.write_bytes(data)
    with pytest.raises(CatalogInstallError): install_catalog(root,archive,candidate,app_version='1.6.7')


@pytest.mark.parametrize('status',[416,206])
def test_unexpected_range_or_416_does_not_publish(tmp_path,status):
    data=content(tmp_path)
    with httpx.Client(transport=httpx.MockTransport(lambda r:httpx.Response(status,content=data))) as client:
        with pytest.raises(UpdateError):
            download.download_catalog(update(data),tmp_path/'downloads',app_version='1.6.7',client=client)
    assert not list((tmp_path/'downloads').iterdir())


def test_foreign_hardlink_not_modified(tmp_path):
    import os
    data=content(tmp_path); candidate=update(data)
    destination=tmp_path/'downloads'; destination.mkdir()
    foreign=tmp_path/'foreign'; foreign.write_bytes(b'keep')
    os.link(foreign,destination/(candidate.sha256+'.part'))
    with httpx.Client(transport=httpx.MockTransport(lambda r:pytest.fail('network'))) as client:
        with pytest.raises(UpdateError): download.download_catalog(candidate,destination,app_version='1.6.7',client=client)
    assert foreign.read_bytes()==b'keep' and (destination/(candidate.sha256+'.part')).exists()
