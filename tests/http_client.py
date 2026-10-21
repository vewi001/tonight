"""Explicitly authorized local API tooling, including empty and binary writes.

Security tests use the unmodified FastAPI TestClient to exercise absent headers.
This client still enforces Host, Origin, evening code and main-computer checks.
"""
from fastapi.testclient import TestClient as BaseTestClient


class TestClient(BaseTestClient):
    __test__ = False

    def __init__(self, *args, headers=None, **kwargs):
        super().__init__(*args, headers={'X-Tonight-Request': '1', **(headers or {})}, **kwargs)
