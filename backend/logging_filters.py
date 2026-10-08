from __future__ import annotations

import logging


class ExpectedWebSocketDisconnectFilter(logging.Filter):
    """Hide only the noisy Windows timeout produced by a vanished client."""

    _messages = {"data transfer failed", "keepalive ping failed"}

    def filter(self, record: logging.LogRecord) -> bool:
        if record.getMessage() not in self._messages or not record.exc_info:
            return True
        error = record.exc_info[1]
        return not (
            isinstance(error, OSError)
            and (getattr(error, "winerror", None) == 121 or getattr(error, "errno", None) == 121)
        )


def install_expected_disconnect_filter() -> None:
    logger = logging.getLogger("uvicorn.error")
    if not any(isinstance(item, ExpectedWebSocketDisconnectFilter) for item in logger.filters):
        logger.addFilter(ExpectedWebSocketDisconnectFilter())
