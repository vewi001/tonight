import hashlib
import io
import json
import zipfile

import httpx
import pytest

import backend.auto_update as module
from backend.auto_update import AvailableUpdate, UpdateDownloadInterrupted, UpdateError, UpdateManager, download_update


def package():
    output = io.BytesIO()
    with zipfile.ZipFile(output, 'w') as archive:
        archive.writestr('tonight-release.json', json.dumps({
            'product': 'Tonight', 'format': 1, 'version': '1.7.2', 'files': ['Tonight.exe']}))
        archive.writestr('Tonight.exe', bytes(range(256)) * 400)
    data = output.getvalue()
    return data, AvailableUpdate('1.7.2', 'Tonight-update-1.7.2.zip', len(data),
        hashlib.sha256(data).hexdigest(),
        'https://github.com/vewi001/tonight/releases/download/v1.7.2/Tonight-update-1.7.2.zip')


class BrokenStream(httpx.SyncByteStream):
    def __init__(self, data):
        self.data = data

    def __iter__(self):
        yield self.data
        raise httpx.ReadError('Disconnected')


@pytest.fixture(autouse=True)
def immediate_retries(monkeypatch):
    monkeypatch.setattr(module.time, 'sleep', lambda _: None)


def partial(tmp_path, update, content):
    tmp_path.mkdir(exist_ok=True)
    path = tmp_path / (update.sha256 + '.part')
    path.write_bytes(content)
    return path


def test_interruption_retries_from_stable_origin_with_range_and_no_duplicate_bytes(tmp_path):
    data, update = package()
    requests, progress = [], []

    def handler(request):
        requests.append(request)
        if request.url.host == 'github.com':
            return httpx.Response(302, headers={'Location': 'https://release-assets.githubusercontent.com/download'})
        if 'range' not in request.headers:
            return httpx.Response(200, stream=BrokenStream(data[:12345]))
        assert request.headers['range'] == 'bytes=12345-'
        return httpx.Response(206, content=data[12345:], headers={
            'Content-Range': f'bytes 12345-{len(data)-1}/{len(data)}'})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = download_update(update, tmp_path, client=client, progress=lambda n, t: progress.append(n))
    assert result.read_bytes() == data
    assert [r.url.host for r in requests] == ['github.com', 'release-assets.githubusercontent.com'] * 2
    assert all('authorization' not in r.headers and 'cookie' not in r.headers for r in requests)
    assert progress[-1] == len(data) and 12345 in progress
    assert not list(tmp_path.glob('*.part'))


def test_failed_transfer_retains_bytes_and_new_manager_can_resume_after_restart(tmp_path, monkeypatch):
    data, update = package()
    monkeypatch.setattr(module, 'fetch_latest_update', lambda _: update)
    manager = UpdateManager(tmp_path, '1.7.1', install_supported=True)
    manager.check()
    manager.reserve_download()

    def failing(request):
        offset = int(request.headers.get('range', 'bytes=0-')[6:-1])
        headers = {'Content-Range': f'bytes {offset}-{len(data)-1}/{len(data)}'} if offset else {}
        return httpx.Response(206 if offset else 200, headers=headers, stream=BrokenStream(data[offset:offset+100]))

    with httpx.Client(transport=httpx.MockTransport(failing)) as client:
        with pytest.raises(UpdateDownloadInterrupted) as error:
            download_update(update, tmp_path / 'Updates', client=client)
    assert error.value.received == 300
    assert not list((tmp_path / 'Updates').glob('*.zip'))
    manager.fail(str(error.value))
    restarted = UpdateManager(tmp_path, '1.7.1', install_supported=True)
    status = restarted.check()
    assert status['can_resume'] and status['download_bytes'] == 300

    def success(request):
        assert request.headers['range'] == 'bytes=300-'
        return httpx.Response(206, content=data[300:], headers={
            'Content-Range': f'bytes 300-{len(data)-1}/{len(data)}'})

    with httpx.Client(transport=httpx.MockTransport(success)) as client:
        result = download_update(update, tmp_path / 'Updates', client=client)
    assert result.read_bytes() == data


def test_server_ignoring_range_restarts_instead_of_appending(tmp_path):
    data, update = package()
    partial(tmp_path, update, data[:100])
    with httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(200, content=data))) as client:
        assert download_update(update, tmp_path, client=client).read_bytes() == data


@pytest.mark.parametrize('response', ['wrong_start', 'wrong_end', 'wrong_total', 'missing_range', 'encoding'])
def test_untrusted_range_or_encoding_never_publishes_a_package(tmp_path, response):
    data, update = package()
    partial(tmp_path, update, data[:100])
    bounds = {'wrong_start': f'bytes 99-{len(data)-1}/{len(data)}',
              'wrong_end': f'bytes 100-{len(data)-2}/{len(data)}',
              'wrong_total': f'bytes 100-{len(data)-1}/{len(data)+1}'}
    headers = {'Content-Range': bounds.get(response, f'bytes 100-{len(data)-1}/{len(data)}')}
    if response == 'missing_range':
        headers = {}
    if response == 'encoding':
        headers['Content-Encoding'] = 'gzip'
    with httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(206, stream=httpx.ByteStream(data[100:]), headers=headers))) as client:
        with pytest.raises(UpdateError):
            download_update(update, tmp_path, client=client)
    assert not list(tmp_path.iterdir())


def test_tampered_saved_bytes_fail_full_hash_even_with_valid_range(tmp_path):
    data, update = package()
    partial(tmp_path, update, b'x' * 100)
    headers = {'Content-Range': f'bytes 100-{len(data)-1}/{len(data)}'}
    with httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(206, content=data[100:], headers=headers))) as client:
        with pytest.raises(UpdateError):
            download_update(update, tmp_path, client=client)
    assert not list(tmp_path.iterdir())


def test_complete_partial_and_verified_cached_zip_need_no_network(tmp_path):
    data, update = package()
    partial(tmp_path, update, data)
    def no_network(_):
        pytest.fail('Already complete package should not be downloaded')
    with httpx.Client(transport=httpx.MockTransport(no_network)) as client:
        result = download_update(update, tmp_path, client=client)
        assert download_update(update, tmp_path, client=client) == result
    assert result.read_bytes() == data


def test_changed_release_digest_cannot_reuse_old_partial(tmp_path):
    data, update = package()
    old = tmp_path / ('0' * 64 + '.part')
    old.write_bytes(b'old release')
    def handler(request):
        assert 'range' not in request.headers
        return httpx.Response(200, content=data)
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        assert download_update(update, tmp_path, client=client).read_bytes() == data
    assert old.read_bytes() == b'old release'


def test_download_rejects_linked_directory_before_network_or_write(tmp_path, monkeypatch):
    _, update = package()
    linked = tmp_path / 'linked'
    monkeypatch.setattr(module, '_is_link', lambda p: p == linked)
    with httpx.Client(transport=httpx.MockTransport(lambda _: pytest.fail('Network should not be used'))) as client:
        with pytest.raises(UpdateError):
            download_update(update, linked, client=client)
    assert not linked.exists()
