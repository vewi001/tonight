from __future__ import annotations

from collections import defaultdict

from fastapi import WebSocket


class ConnectionManager:
    def __init__(self) -> None:
        self.connections: dict[int, dict[str, set[WebSocket]]] = defaultdict(lambda: defaultdict(set))

    async def connect(self, session_id: int, user_id: str, websocket: WebSocket) -> None:
        await websocket.accept()
        self.connections[session_id][user_id].add(websocket)

    def disconnect(self, session_id: int, user_id: str, websocket: WebSocket) -> None:
        users = self.connections.get(session_id)
        if not users:
            return
        sockets = users.get(user_id)
        if sockets is not None:
            sockets.discard(websocket)
            if not sockets:
                users.pop(user_id, None)
        if not users:
            self.connections.pop(session_id, None)

    def presence(self, session_id: int) -> dict[str, bool]:
        users = self.connections.get(session_id, {})
        return {user: bool(users.get(user)) for user in ("lera", "nikita")}

    async def broadcast(self, session_id: int, payload: dict) -> None:
        payload = {**payload, "presence": self.presence(session_id)}
        dead: list[tuple[str, WebSocket]] = []
        for user, sockets in self.connections.get(session_id, {}).items():
            for socket in list(sockets):
                try:
                    await socket.send_json(payload)
                except Exception:
                    dead.append((user, socket))
        for user, socket in dead:
            self.disconnect(session_id, user, socket)

    async def close_sessions(self, session_ids: list[int], payload: dict) -> None:
        """Notify and close every socket whose persisted session was removed."""
        for session_id in session_ids:
            users = self.connections.pop(session_id, {})
            for sockets in users.values():
                for socket in list(sockets):
                    try:
                        await socket.send_json(payload)
                        await socket.close(code=1000)
                    except Exception:
                        # Deletion is authoritative even when a sleeping phone
                        # disappears before receiving the final notification.
                        pass


manager = ConnectionManager()

