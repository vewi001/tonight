"""Validate browser boundaries before URL reconstruction, routing or filesystem I/O."""
from __future__ import annotations

import ipaddress
import re
import socket
from urllib.parse import unquote, urlsplit

from starlette.responses import JSONResponse

from backend.network import lan_ip


def authority(value: str) -> tuple[str, int | None] | None:
    if not value or re.search(r'[\s/\\?#@%]', value):
        return None
    try:
        parsed = urlsplit('//' + value)
        host, port = parsed.hostname, parsed.port
        if not host or parsed.username or parsed.password:
            return None
        if ':' in host:
            ipaddress.IPv6Address(host)
        elif not re.fullmatch(r'[A-Za-z0-9.-]+', host):
            return None
        return host.lower(), port
    except ValueError:
        return None


def same_origin(origin: str, host: str, scheme: str) -> bool:
    try:
        parsed = urlsplit(origin)
        if parsed.path or parsed.query or parsed.fragment or parsed.scheme != scheme:
            return False
        supplied, target = authority(parsed.netloc), authority(host)
        if not supplied or not target:
            return False
        default = 443 if scheme == 'https' else 80
        return (supplied[0], supplied[1] or default) == (target[0], target[1] or default)
    except ValueError:
        return False


def unsafe_path(path: str) -> bool:
    # Check before StaticFiles normalizes/join/resolves a Windows path. Also
    # reject nested encodings so another layer cannot reinterpret one later.
    for _ in range(4):
        if ('\\' in path or ':' in path or '\x00' in path or '//' in path
                or any(part in {'.', '..'} for part in path.split('/'))):
            return True
        decoded = unquote(path)
        if decoded == path:
            return False
        path = decoded
    return True


class RequestBoundary:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope['type'] not in {'http', 'websocket'}:
            return await self.app(scope, receive, send)
        headers = scope.get('headers', [])
        hosts = [value.decode('latin-1') for name, value in headers if name.lower() == b'host']
        origins = [value.decode('latin-1') for name, value in headers if name.lower() == b'origin']
        host = authority(hosts[0]) if len(hosts) == 1 else None
        # Host names controlled by a foreign DNS zone must not acquire local
        # privileges through rebinding. No DNS resolution of supplied input.
        allowed = {'localhost', '127.0.0.1', '::1', socket.gethostname().lower(), lan_ip()}
        server_host = (scope.get('server') or ('', 0))[0].lower()
        if server_host not in {'0.0.0.0', '::', ''}:
            allowed.add(server_host)
        denied = not host or host[0] not in allowed
        path = scope.get('path', '')
        if unsafe_path(path):
            denied = True
        if path.startswith('/api/') or scope['type'] == 'websocket':
            scheme = 'https' if scope['scheme'] in {'https', 'wss'} else 'http'
            if origins and (len(origins) != 1 or not same_origin(origins[0], hosts[0] if hosts else '', scheme)):
                denied = True
            values = {name.lower(): value for name, value in headers}
            if values.get(b'sec-fetch-site') == b'cross-site':
                denied = True
            if scope['type'] == 'http' and scope['method'] not in {'GET', 'HEAD', 'OPTIONS'}:
                content_type = values.get(b'content-type', b'').split(b';')[0].strip().lower()
                # JSON is a non-simple browser request; no CORS permission is
                # granted. Binary/empty requests use an explicit custom header.
                if (content_type != b'application/json' and values.get(b'x-tonight-request') != b'1'
                        and values.get(b'x-tonight-update') != b'1'):
                    denied = True
        if denied:
            if scope['type'] == 'websocket':
                await send({'type': 'websocket.close', 'code': 1008})
            else:
                await JSONResponse({'detail': 'Откройте Tonight по его локальному адресу и повторите действие.'}, status_code=403)(scope, receive, send)
            return
        await self.app(scope, receive, send)
