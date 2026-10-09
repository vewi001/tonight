from copy import deepcopy

import pytest
import httpx

from backend.auto_update import UpdateError
from backend.catalog_discovery import fetch_catalog_update, select_catalog_update


def release(version='1.0.0'):
    name = f'Tonight-catalog-{version}.zip'
    return {'tag_name':f'catalog-v{version}','draft':False,'prerelease':False,
            'assets':[{'name':name,'size':123,'digest':'sha256:'+'a'*64,
                       'browser_download_url':f'https://github.com/vewi001/tonight/releases/download/catalog-v{version}/{name}'}]}


def test_selects_numeric_catalog_version_independently_of_app_latest():
    values = [release('1.9.0'), {'tag_name':'v9.9.9','assets':[]}, release('1.10.0')]
    before = deepcopy(values)
    result = select_catalog_update(values,'1.8.0')
    assert result.version=='1.10.0' and result.name=='Tonight-catalog-1.10.0.zip'
    assert values==before


def test_first_install_and_repeat_or_older_version():
    assert select_catalog_update([release()],None).version=='1.0.0'
    assert select_catalog_update([release()],'1.0.0') is None
    assert select_catalog_update([release()],'2.0.0') is None


def test_draft_prerelease_wrong_tag_and_missing_asset_are_ignored():
    values = [dict(release('2.0.0'),draft=True), dict(release('3.0.0'),prerelease=True),
              dict(release('4.0.0'),tag_name='catalog-v04.0.0'),dict(release('5.0.0'),assets=[]),release()]
    assert select_catalog_update(values,None).version=='1.0.0'


@pytest.mark.parametrize('change',[
    {'size':True},{'size':0},{'digest':'sha256:bad'},
    {'browser_download_url':'https://github.com/other/tonight/releases/download/catalog-v1.0.0/Tonight-catalog-1.0.0.zip'},
    {'browser_download_url':'https://github.com/vewi001/tonight/releases/download/v1.0.0/Tonight-catalog-1.0.0.zip'}])
def test_untrusted_catalog_asset_is_rejected(change):
    value = release()
    value['assets'][0].update(change)
    with pytest.raises(UpdateError):
        select_catalog_update([value],None)


def test_duplicate_selected_asset_or_release_is_rejected():
    value = release()
    value['assets'].append(dict(value['assets'][0]))
    with pytest.raises(UpdateError):
        select_catalog_update([value],None)
    with pytest.raises(UpdateError):
        select_catalog_update([release(),release()],None)


def test_invalid_response_and_installed_version_are_safe_errors():
    with pytest.raises(UpdateError):
        select_catalog_update({},None)
    with pytest.raises(UpdateError):
        select_catalog_update([], 'private invalid value')


def test_catalog_fetch_paginates_release_list_without_credentials():
    seen = []
    def handler(request):
        seen.append(request)
        assert request.url.path=='/repos/vewi001/tonight/releases'
        assert request.url.params['per_page']=='100'
        return httpx.Response(200,json=[{'tag_name':'v1.6.5'}]*100 if request.url.params['page']=='1' else [release('1.10.0')])
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        assert fetch_catalog_update(None,client=client).version=='1.10.0'
    assert len(seen)==2
    assert all('authorization' not in request.headers and 'cookie' not in request.headers for request in seen)


@pytest.mark.parametrize('status',[403,429,503])
def test_catalog_fetch_network_error_is_safe_and_retryable(status):
    with httpx.Client(transport=httpx.MockTransport(lambda request:httpx.Response(status))) as client:
        with pytest.raises(UpdateError):
            fetch_catalog_update(None,client=client)


def test_missing_public_releases_are_empty_but_malformed_response_is_error():
    with httpx.Client(transport=httpx.MockTransport(lambda request:httpx.Response(404))) as client:
        assert fetch_catalog_update(None,client=client) is None
    with httpx.Client(transport=httpx.MockTransport(lambda request:httpx.Response(200,json={}))) as client:
        with pytest.raises(UpdateError):
            fetch_catalog_update(None,client=client)


def test_catalog_fetch_page_limit_is_not_reported_as_up_to_date():
    seen = []
    def handler(request):
        seen.append(request)
        return httpx.Response(200,json=[{'tag_name':'v1.6.5'}]*100)
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(UpdateError):
            fetch_catalog_update(None,client=client)
    assert len(seen)==10
