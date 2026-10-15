"""Explicit user-configured HTTPS mirror; signed metadata stays on GitHub."""
import os
from contextlib import nullcontext
import httpx
from urllib.parse import urlsplit

PUBLIC_CONFIG_URL = 'https://raw.githubusercontent.com/vewi001/tonight/main/app/mirror.json'
_public_mirror = {}
PREFIX = 'https://github.com/vewi001/tonight/releases/download/'


def mirror_base():
    value = os.getenv('TONIGHT_DOWNLOAD_MIRROR', '').strip().rstrip('/') or (_public_mirror.get('url') if _public_mirror.get('kind')=='https' else '')
    if not value:
        return None
    try:
        parts = urlsplit(value)
        if (parts.scheme != 'https' or not parts.hostname or parts.username or parts.password or
                parts.query or parts.fragment or parts.port not in (None, 443) or
                any(segment in {'.', '..'} for segment in parts.path.split('/')) or '%' in value or '\\' in value):
            raise ValueError('Invalid mirror URL')
    except ValueError:
        raise ValueError('Зеркало должно быть публичным HTTPS-адресом без ключей и параметров.') from None
    return value


def mirror_url_allowed(url):
    try:
        base = mirror_base()
    except ValueError:
        return False
    return bool(base and url.startswith(base + '/')) or yandex_download_allowed(url)


def yandex_download_allowed(url):
    parts = urlsplit(url)
    host = parts.hostname or ''
    return (parts.scheme=='https' and not parts.username and not parts.password and parts.port in (None,443)
            and (host=='downloader.disk.yandex.ru' or host.endswith('.downloader.disk.yandex.ru')
                 or host.endswith('.storage.yandex.net')))


def validate_yandex_folder(value):
    parts = urlsplit(value)
    if (parts.scheme!='https' or parts.hostname not in {'disk.yandex.ru','disk.yandex.com','yadi.sk'}
            or not parts.path.startswith('/d/') or len(parts.path)<=3 or parts.username or parts.password
            or parts.port not in (None,443) or parts.query or parts.fragment):
        raise ValueError('Укажите публичную ссылку на папку Яндекс Диска.')
    return value.rstrip('/')


def refresh_public_mirror(*, client=None):
    global _public_mirror
    try:
        with nullcontext(client) if client is not None else httpx.Client(timeout=5,trust_env=False) as session:
            with session.stream('GET',PUBLIC_CONFIG_URL,headers={'User-Agent':'Tonight-updater'},follow_redirects=False) as response:
                if response.status_code!=200:
                    return
                body=bytearray()
                for chunk in response.iter_bytes(1024):
                    body.extend(chunk)
                    if len(body)>4096:raise ValueError('Mirror configuration too large')
                import json
                config=json.loads(body)
        if not isinstance(config,dict) or type(config.get('format_version')) is not int or config['format_version']!=1:
            raise ValueError('Invalid mirror configuration')
        if config.get('kind')=='none' and set(config)=={'format_version','kind'}:
            _public_mirror={}
        elif config.get('kind')=='yandex-disk' and set(config)=={'format_version','kind','url'}:
            validate_yandex_folder(config['url']);_public_mirror=config
        elif config.get('kind')=='https' and set(config)=={'format_version','kind','url'}:
            # Apply the same validation as the explicit environment override.
            previous=_public_mirror;_public_mirror=config
            try:mirror_base()
            except ValueError:_public_mirror=previous;raise
        else:raise ValueError('Invalid mirror configuration')
    except (httpx.HTTPError,ValueError,TypeError):
        pass  # A mirror outage must never block GitHub delivery.


def download_sources(url, *, client=None):
    if not url.startswith(PREFIX):
        return [url]
    sources=[]
    folder=os.getenv('TONIGHT_YANDEX_MIRROR','').strip() or (_public_mirror.get('url') if _public_mirror.get('kind')=='yandex-disk' else '')
    try:
        if folder:
            validate_yandex_folder(folder)
            with nullcontext(client) if client is not None else httpx.Client(timeout=10,trust_env=False) as session:
                response=session.get('https://cloud-api.yandex.net/v1/disk/public/resources/download',
                    params={'public_key':folder,'path':'/'+url[len(PREFIX):]},
                    headers={'User-Agent':'Tonight-updater'},follow_redirects=False)
                if response.status_code==200 and len(response.content)<=16384:
                    link=response.json().get('href')
                    if isinstance(link,str) and yandex_download_allowed(link):sources.append(link)
        base=mirror_base()
        if base:sources.append(base+'/'+url[len(PREFIX):])
    except (httpx.HTTPError,ValueError,TypeError,AttributeError):
        pass
    return sources+[url]
