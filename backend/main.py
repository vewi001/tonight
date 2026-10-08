from __future__ import annotations

import asyncio
import io
import json
import secrets
import sqlite3
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
import qrcode
import qrcode.image.svg

from backend.api.realtime import manager
from backend.backups import MAX_IMPORTED_BACKUP_BYTES, create_backup, import_backup, list_backups, restore_backup
from backend.catalog_bundle import bootstrap_catalog
from backend.config import ASSET_ROOT, ROOT, settings
from backend.database.db import db_session, generate_access_code, initialize, loads
from backend.logging_filters import install_expected_disconnect_filter
from backend.models.schemas import AvoidSimilarIn, EveningFeedbackIn, FeedbackIn, JoinIn, PreferencesIn, PrivacyDeleteIn, RestoreBackupIn, SwipeIn, UserAction
from backend.network import active_port, invite_url, lan_ip
from backend.movies.catalog import get_movie, search_movies
from backend.movies.franchises import franchises
from backend.movies.genres import normalize_genres
from backend.movies.catalog_sync import refresh_catalog_if_due, sync_status
from backend.movies.media import genre_art, local_media, placeholder_svg
from backend.movies.seed import seed_movies
from backend.ollama.client import health as ollama_health, rerank
from backend.privacy import PrivacyDeleteError, delete_personal_data
from backend.recommendation.engine import recommend
from backend.recommendation.avoidance import add_avoidance, list_avoidances, remove_avoidance
from backend.recommendation.taste_profile import exclude_genre, profile_filters, reset_profile
from backend.recommendation.weekly import weekly_picks
from backend.release import APP_VERSION
from backend.sessions.service import (
    active_session, both_ready, choose_catalog_movie, choose_movie, choose_saved_movie, choose_specific_recommendation, confirm_watched, decline_selected_movie, ensure_participant,
    WATCHLIST_REASONS, get_deck, record_connection_restored, remove_saved_movie, save_movie_for_later, save_preferences, save_swipe, saved_movies, session_access_code, session_state, store_recommendations,
)
from backend.usage_metrics import usage_summary

STATIC = ASSET_ROOT / "frontend"
install_expected_disconnect_filter()


@asynccontextmanager
async def lifespan(_: FastAPI):
    initialize()
    bootstrap_catalog(ROOT)
    seed_movies()
    # Catalog metadata is refreshed separately from recommendations, so a slow
    # network can never block the evening flow.
    refresh_task = asyncio.create_task(_catalog_refresh_loop())
    try:
        yield
    finally:
        refresh_task.cancel()
        try:
            await refresh_task
        except asyncio.CancelledError:
            pass


async def _catalog_refresh_loop() -> None:
    """A server left open across Monday also notices the new weekly catalog."""
    while True:
        await asyncio.to_thread(refresh_catalog_if_due)
        await asyncio.sleep(6 * 60 * 60)


app = FastAPI(title="Tonight", version=APP_VERSION, lifespan=lifespan)


async def publish_state(session_id: int, event: str = "state") -> None:
    await manager.broadcast(session_id, {"type": event, "session": session_state(session_id)})


async def _refine_recommendations_in_background(
    session_id: int, candidates: list[dict], participants: dict,
) -> None:
    """AI may improve wording/order, but it must never delay the result screen."""
    try:
        enriched = await rerank(candidates, {"participants": participants})
        if enriched != candidates:
            store_recommendations(session_id, enriched)
            await publish_state(session_id, "recommendations_refined")
    except Exception:
        # The deterministic result was already saved. Optional AI must stay optional.
        return


async def finalize_recommendations(session_id: int) -> dict:
    """Persist a usable result first, then optionally refine it without blocking clients."""
    if not both_ready(session_id):
        raise ValueError("Оба участника должны закончить быстрые реакции")
    state = session_state(session_id)
    if state["recommendations"]:
        return state
    deterministic = recommend(session_id, settings.candidate_count)
    if not deterministic:
        raise ValueError("Фильтры слишком строгие — попробуйте ослабить ограничения")
    store_recommendations(session_id, deterministic)
    ready_state = session_state(session_id)
    await publish_state(session_id, "recommendations_ready")
    asyncio.create_task(
        _refine_recommendations_in_background(session_id, deterministic, state["participants"])
    )
    return ready_state


@app.get("/api/health")
async def health() -> dict:
    with db_session() as db:
        count = db.execute("SELECT COUNT(*) FROM movies").fetchone()[0]
    return {"ok": True, "database": True, "movies": count}


@app.get("/api/diagnostics")
async def diagnostics() -> dict:
    with db_session() as db:
        integrity = db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        movie_count = db.execute("SELECT COUNT(*) FROM movies").fetchone()[0]
    address = lan_ip()
    network_ready = address != "127.0.0.1"
    poster_dir = ROOT / "data" / "posters"
    local_poster_count = sum(1 for path in poster_dir.glob("*") if path.is_file()) if poster_dir.exists() else 0
    ollama = await ollama_health()
    checks = [
        {"id": "database", "state": "ready" if integrity else "action", "title": "База фильмов", "detail": "Готова" if integrity else "Перезапустите Tonight и попробуйте ещё раз."},
        {"id": "catalog", "state": "ready" if movie_count else "action", "title": "Каталог", "detail": f"Готово: {movie_count} фильмов" if movie_count else "Перезапустите Tonight, чтобы восстановить каталог."},
        {"id": "network", "state": "ready" if network_ready else "action", "title": "Домашняя сеть", "detail": "Телефон сможет подключиться по Wi-Fi." if network_ready else "Подключите этот компьютер к домашней Wi-Fi сети."},
        {"id": "images", "state": "ready", "title": "Обложки", "detail": f"Готово: {local_poster_count} загружено, остальные с запасными обложками."},
        {"id": "ollama", "state": "optional", "title": "Умные подсказки", "detail": "Подключены." if ollama["available"] and ollama["model_installed"] else "Необязательная функция: Tonight работает и без неё."},
    ]
    required_problem = next((check for check in checks if check["state"] == "action"), None)
    summary = {"ok": required_problem is None, "text": "Всё готово" if required_problem is None else required_problem["detail"]}
    technical_log = json.dumps(
        {
            "database": integrity,
            "catalog_movies": movie_count,
            "network_ready": network_ready,
            "local_images": local_poster_count,
            "ollama_available": ollama["available"],
            "ollama_model_ready": ollama["model_installed"],
        },
        ensure_ascii=False,
        sort_keys=True,
    )
    return {"summary": summary, "checks": checks, "technical_log": technical_log}


@app.get("/api/usage-summary")
async def local_usage_summary(request: Request) -> dict:
    _require_main_computer(request)
    return usage_summary()


@app.get("/api/movies/search")
async def search_catalog(q: str = "") -> dict:
    return {"items": search_movies(q)}


@app.get("/api/setup/status")
async def setup_status() -> dict:
    with db_session() as db:
        count = db.execute("SELECT COUNT(*) FROM movies").fetchone()[0]
        tmdb_count = db.execute("SELECT COUNT(*) FROM movies WHERE source LIKE '%tmdb%'").fetchone()[0]
    poster_dir = ROOT / "data" / "posters"
    poster_count = sum(1 for path in poster_dir.glob("*") if path.is_file()) if poster_dir.exists() else 0
    ollama = await ollama_health()
    return {
        "database": True, "catalog": count, "posters": poster_count, "tmdb_movies": tmdb_count, "ollama": ollama,
        "network": True, "catalog_sync": sync_status(), "model_command": f"ollama pull {settings.ollama_model}",
        "poster_command": "$env:TMDB_READ_TOKEN=\"ВАШ_TOKEN\"; .\\.venv\\Scripts\\python.exe scripts\\enrich_starter_catalog.py",
    }


def _is_loopback(host: str | None) -> bool:
    # Starlette's in-process test client is equivalent to localhost. Real
    # network clients arrive with their actual IP address.
    return host in {"127.0.0.1", "::1", "localhost", "testclient"}


def _require_main_computer(request: Request) -> None:
    if not _is_loopback(request.client.host if request.client else None):
        raise HTTPException(403, "Это действие доступно только на основном компьютере")


def _public_session_state(session: dict) -> dict:
    return {key: session[key] for key in ("id", "date", "title")}


def _has_evening_access(request: Request, session_id: int) -> bool:
    if _is_loopback(request.client.host if request.client else None):
        return True
    try:
        expected = session_access_code(session_id)
    except ValueError:
        return False
    supplied = request.headers.get("X-Tonight-Code", "")
    return bool(supplied) and secrets.compare_digest(supplied, expected)


def _is_public_remote_api(request: Request) -> bool:
    path = request.url.path
    if request.method == "GET" and path in {
        "/api/health", "/api/diagnostics", "/api/setup/status", "/api/invite",
        "/api/invite/qr.svg", "/api/sessions/active",
    }:
        return True
    if request.method == "POST" and path.startswith("/api/sessions/") and path.endswith("/join"):
        return True
    if request.method == "GET" and (path == "/api/movies/search" or path.startswith("/api/movies/")):
        return True
    return False


@app.middleware("http")
async def require_evening_code_for_remote_api(request: Request, call_next):
    path = request.url.path
    if not path.startswith("/api/") or _is_loopback(request.client.host if request.client else None) or _is_public_remote_api(request):
        return await call_next(request)
    session_id = None
    parts = path.split("/")
    if len(parts) > 3 and parts[2] == "sessions" and parts[3].isdigit():
        session_id = int(parts[3])
    if session_id is None:
        session = active_session(create=True)
        session_id = session["id"]
    if not _has_evening_access(request, session_id):
        return JSONResponse({"detail": "Введите код с экрана Tonight"}, status_code=403)
    return await call_next(request)


def _invite_details(include_access_code: bool = False) -> dict:
    address = lan_ip()
    port = active_port()
    session = active_session(create=True)
    details = {
        "url": invite_url(address, port),
        "display_url": f"{address}:{port}",
        "session": session if include_access_code else _public_session_state(session),
    }
    if include_access_code:
        details["access_code"] = session_access_code(session["id"])
    return details


@app.get("/api/invite")
async def invite(request: Request) -> dict:
    return _invite_details(_is_loopback(request.client.host if request.client else None))


@app.get("/api/invite/qr.svg")
async def invite_qr() -> Response:
    image = qrcode.make(_invite_details()["url"], image_factory=qrcode.image.svg.SvgPathImage)
    stream = io.BytesIO()
    image.save(stream)
    return Response(stream.getvalue(), media_type="image/svg+xml", headers={"Cache-Control": "no-store"})


@app.get("/api/sessions/active")
async def get_active_session(request: Request) -> dict:
    session = active_session(create=True)
    return session if _has_evening_access(request, session["id"]) else _public_session_state(session)


@app.post("/api/sessions/new")
async def new_session() -> dict:
    from datetime import date
    from backend.sessions.service import _title
    now = datetime.now().isoformat(timespec="seconds")
    with db_session() as db:
        cur = db.execute(
            "INSERT INTO sessions(session_date,title,status,access_code,created_at,updated_at) VALUES(?,?,?,?,?,?)",
            (date.today().isoformat(), _title(date.today()), "choosing", generate_access_code(), now, now),
        )
        session_id = cur.lastrowid
    return session_state(session_id)


@app.post("/api/sessions/{session_id}/restart")
async def restart_session(session_id: int) -> dict:
    """Start a clean evening without deleting the interrupted session or history."""
    from datetime import date
    from backend.sessions.service import _title

    now = datetime.now().isoformat(timespec="seconds")
    with db_session() as db:
        existing = db.execute("SELECT id,access_code FROM sessions WHERE id=?", (session_id,)).fetchone()
        if not existing:
            raise HTTPException(404, "Сессия не найдена")
        changed = db.execute(
            "UPDATE sessions SET status='abandoned',updated_at=? WHERE id=? AND status != 'abandoned'",
            (now, session_id),
        ).rowcount
        if not changed:
            replacement = db.execute(
                "SELECT id FROM sessions WHERE session_date=? AND status != 'abandoned' ORDER BY id DESC LIMIT 1",
                (date.today().isoformat(),),
            ).fetchone()
            if replacement:
                return session_state(replacement["id"], db)
        cur = db.execute(
            "INSERT INTO sessions(session_date,title,status,access_code,created_at,updated_at) VALUES(?,?,?,?,?,?)",
            (date.today().isoformat(), _title(date.today()), "choosing", existing["access_code"], now, now),
        )
        new_id = cur.lastrowid
    await publish_state(session_id, "session_restarted")
    return session_state(new_id)


@app.get("/api/sessions/{session_id}")
async def get_session(session_id: int) -> dict:
    try:
        return session_state(session_id)
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc


@app.post("/api/sessions/{session_id}/join")
async def join_session(session_id: int, payload: JoinIn, request: Request) -> dict:
    if not _is_loopback(request.client.host if request.client else None):
        try:
            valid = secrets.compare_digest(payload.access_code or "", session_access_code(session_id))
        except ValueError as exc:
            raise HTTPException(404, "Вечер не найден") from exc
        if not valid:
            raise HTTPException(403, "Введите код с экрана Tonight")
    ensure_participant(session_id, payload.user_id)
    await publish_state(session_id, "joined")
    return session_state(session_id)


@app.post("/api/sessions/{session_id}/connection-restored")
async def connection_restored(session_id: int, request: Request) -> dict:
    if _is_loopback(request.client.host if request.client else None):
        raise HTTPException(400, "Счётчик предназначен только для подключения телефона")
    try:
        count = record_connection_restored(session_id)
    except ValueError as exc:
        raise HTTPException(404, "Вечер не найден") from exc
    return {"ok": True, "count": count}


@app.post("/api/sessions/{session_id}/preferences")
async def preferences(session_id: int, payload: PreferencesIn) -> dict:
    save_preferences(session_id, payload)
    await publish_state(session_id, "preferences")
    return {"ok": True}


@app.get("/api/sessions/{session_id}/swipe/{user_id}")
async def swipe_deck(session_id: int, user_id: str) -> dict:
    if user_id not in {"lera", "nikita"}:
        raise HTTPException(400, "unknown user")
    movies, total = get_deck(session_id, user_id)
    return {"movies": movies, "total": total}


@app.post("/api/sessions/{session_id}/swipe")
async def swipe(session_id: int, payload: SwipeIn) -> dict:
    try:
        progress = save_swipe(session_id, payload.user_id, payload.movie_id, payload.reaction)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    if both_ready(session_id):
        try:
            await finalize_recommendations(session_id)
        except ValueError as exc:
            # The reaction itself succeeded. Return that progress and let the
            # recovery UI offer a clear retry/restart instead of trapping the
            # last card behind a 409 error.
            progress["recommendation_error"] = str(exc)
            await publish_state(session_id, "progress")
    else:
        await publish_state(session_id, "progress")
    # Return the authoritative snapshot so a browser that started with an old
    # eight-card deck immediately receives its newly appended cards.
    remaining, total = get_deck(session_id, payload.user_id)
    progress["movies"] = remaining
    progress["total"] = total
    return progress


@app.post("/api/sessions/{session_id}/recommend")
async def recover_recommendations(session_id: int) -> dict:
    """Resume an interrupted session whose two participants are already ready."""
    try:
        return await finalize_recommendations(session_id)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc


@app.post("/api/sessions/{session_id}/choose")
async def choose(session_id: int) -> dict:
    try:
        selected = choose_movie(session_id)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    await publish_state(session_id, "selected")
    return selected


@app.post("/api/sessions/{session_id}/choose-another")
async def choose_another(session_id: int) -> dict:
    try:
        selected = choose_movie(session_id, exclude_current=True)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    await publish_state(session_id, "selected")
    return selected


@app.post("/api/sessions/{session_id}/select/{movie_id}")
async def select_recommendation(session_id: int, movie_id: str) -> dict:
    try:
        selected = choose_specific_recommendation(session_id, movie_id)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    await publish_state(session_id, "selected")
    return selected


@app.post("/api/sessions/{session_id}/select-saved/{movie_id}")
async def select_saved(session_id: int, movie_id: str) -> dict:
    try:
        selected = choose_saved_movie(session_id, movie_id)
    except ValueError as exc:
        raise HTTPException(409, "Фильм уже удалён из списка или вечер устарел") from exc
    await publish_state(session_id, "selected")
    return selected


@app.post("/api/sessions/{session_id}/select-catalog/{movie_id}")
async def select_catalog(session_id: int, movie_id: str) -> dict:
    try:
        selected = choose_catalog_movie(session_id, movie_id)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    await publish_state(session_id, "selected")
    return selected


@app.post("/api/sessions/{session_id}/watched")
async def watched(session_id: int) -> dict:
    try:
        result = confirm_watched(session_id)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    await publish_state(session_id, "completed")
    return result


@app.post("/api/sessions/{session_id}/decline")
async def decline(session_id: int) -> dict:
    try:
        decline_selected_movie(session_id)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    await publish_state(session_id, "declined")
    return session_state(session_id)


@app.post("/api/sessions/{session_id}/avoid-similar")
async def avoid_similar(session_id: int, payload: AvoidSimilarIn) -> dict:
    state = session_state(session_id)
    if not state["selected"] or state["selected"]["id"] != payload.movie_id:
        raise HTTPException(409, "Можно отклонить только выбранный сейчас фильм")
    try:
        avoidance = add_avoidance(payload.user_id, payload.movie_id)
        decline_selected_movie(session_id)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    await publish_state(session_id, "avoid_similar")
    return {"session": session_state(session_id), "avoidance": avoidance}


@app.post("/api/history/{history_id}/feedback")
async def feedback(history_id: int, payload: FeedbackIn) -> dict:
    with db_session() as db:
        exists = db.execute("SELECT id FROM watch_history WHERE id=?", (history_id,)).fetchone()
        if not exists:
            raise HTTPException(404, "Просмотр не найден")
        db.execute(
            "INSERT OR REPLACE INTO feedback(history_id,user_id,rating,created_at) VALUES(?,?,?,?)",
            (history_id, payload.user_id, payload.rating, datetime.now().isoformat(timespec="seconds")),
        )
    return {"ok": True}


@app.post("/api/history/{history_id}/evening-feedback")
async def evening_feedback(history_id: int, payload: EveningFeedbackIn) -> dict:
    with db_session() as db:
        exists = db.execute("SELECT id FROM watch_history WHERE id=?", (history_id,)).fetchone()
        if not exists:
            raise HTTPException(404, "Просмотр не найден")
        db.execute(
            "INSERT OR REPLACE INTO evening_feedback(history_id,user_id,fit,created_at) VALUES(?,?,?,?)",
            (history_id, payload.user_id, int(payload.fit), datetime.now().isoformat(timespec="seconds")),
        )
    return {"ok": True}


@app.get("/api/history")
async def history() -> dict:
    with db_session() as db:
        rows = db.execute(
            """SELECT h.id history_id,h.session_id,h.watched_at,m.*,fl.rating lera_rating,fn.rating nikita_rating,
            el.fit lera_evening_fit,en.fit nikita_evening_fit
            FROM watch_history h JOIN movies m ON m.id=h.movie_id
            LEFT JOIN feedback fl ON fl.history_id=h.id AND fl.user_id='lera'
            LEFT JOIN feedback fn ON fn.history_id=h.id AND fn.user_id='nikita'
            LEFT JOIN evening_feedback el ON el.history_id=h.id AND el.user_id='lera'
            LEFT JOIN evening_feedback en ON en.history_id=h.id AND en.user_id='nikita'
            ORDER BY h.watched_at DESC"""
        ).fetchall()
    items = []
    for row in rows:
        movie = get_movie(row["id"])
        items.append({"history_id": row["history_id"], "session_id": row["session_id"], "watched_at": row["watched_at"], "movie": movie, "ratings": {"lera": row["lera_rating"], "nikita": row["nikita_rating"]}, "evening_feedback": {"lera": None if row["lera_evening_fit"] is None else bool(row["lera_evening_fit"]), "nikita": None if row["nikita_evening_fit"] is None else bool(row["nikita_evening_fit"])} })
    return {"items": items}


@app.get("/api/watchlist")
async def watchlist() -> dict:
    return {"items": saved_movies()}


@app.get("/api/weekly-picks")
async def get_weekly_picks() -> dict:
    return {"items": weekly_picks()}


@app.get("/api/franchises")
async def get_franchises() -> dict:
    return {"items": franchises()}


@app.post("/api/watchlist/{movie_id}")
async def save_watchlist_movie(movie_id: str, user_id: str | None = None, reason: str | None = None) -> dict:
    if reason is not None and reason not in WATCHLIST_REASONS:
        raise HTTPException(422, "Выберите одну из предложенных причин")
    try:
        return {"movie": save_movie_for_later(movie_id, user_id if user_id in {"lera", "nikita"} else None, reason)}
    except ValueError as exc:
        raise HTTPException(404, "Фильм не найден") from exc


@app.delete("/api/watchlist/{movie_id}")
async def delete_watchlist_movie(movie_id: str) -> dict:
    remove_saved_movie(movie_id)
    return {"ok": True}


@app.get("/api/taste")
async def taste() -> dict:
    from collections import defaultdict
    profiles: dict[str, dict[str, list[float]]] = {"lera": defaultdict(list), "nikita": defaultdict(list), "pair": defaultdict(list)}
    with db_session() as db:
        rows = db.execute(
            """SELECT f.rowid signal_rowid,f.user_id,f.rating,m.genres,h.id history_id FROM feedback f
            JOIN watch_history h ON h.id=f.history_id JOIN movies m ON m.id=h.movie_id"""
        ).fetchall()
        filters = {user: profile_filters(db, user) for user in ("lera", "nikita")}
    by_history: dict[int, list[tuple[int, list[str]]]] = defaultdict(list)
    for row in rows:
        genres = normalize_genres(loads(row["genres"], []))
        excluded, _, feedback_cutoff = filters[row["user_id"]]
        if row["signal_rowid"] > feedback_cutoff:
            for genre in genres:
                if genre not in excluded: profiles[row["user_id"]][genre].append(float(row["rating"]))
        by_history[row["history_id"]].append((row["rating"], genres))
    for pair_rows in by_history.values():
        if len(pair_rows) == 2:
            value = sum(item[0] for item in pair_rows) / 2
            for genre in set(pair_rows[0][1]) | set(pair_rows[1][1]): profiles["pair"][genre].append(value)
    result = {}
    for profile, genres in profiles.items():
        ranked = sorted(((genre, sum(values) / len(values), len(values)) for genre, values in genres.items()), key=lambda item: (-item[1], -item[2]))
        result[profile] = [{"genre": genre, "score": round(score, 1), "count": count} for genre, score, count in ranked if count >= 2][:6]
    return {
        "profiles": result,
        "enough_data": len(by_history) >= 3,
        "watched": len(by_history),
        "avoidances": {user: list_avoidances(user) for user in ("lera", "nikita")},
    }


@app.delete("/api/taste/avoidances/{rule_id}/{user_id}")
async def delete_avoidance(rule_id: int, user_id: str) -> dict:
    if user_id not in {"lera", "nikita"}:
        raise HTTPException(400, "Неизвестный пользователь")
    try:
        remove_avoidance(rule_id, user_id)
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc
    return {"ok": True}


@app.delete("/api/taste/genres/{genre}/{user_id}")
async def delete_taste_genre(genre: str, user_id: str) -> dict:
    if user_id not in {"lera", "nikita"}:
        raise HTTPException(400, "Неизвестный пользователь")
    try:
        return {"ok": True, "genre": exclude_genre(user_id, genre)}
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@app.post("/api/taste/reset/{user_id}")
async def reset_taste_profile(user_id: str) -> dict:
    if user_id not in {"lera", "nikita"}:
        raise HTTPException(400, "Неизвестный пользователь")
    reset_profile(user_id)
    return {"ok": True}


@app.post("/api/backup")
async def backup(request: Request) -> dict:
    _require_main_computer(request)
    target = create_backup(settings.db_path, ROOT / "data" / "backups")
    return {"ok": True, "file": str(target.relative_to(ROOT)), "name": target.name}


@app.get("/api/backups")
async def backups(request: Request) -> dict:
    _require_main_computer(request)
    return {"items": list_backups(ROOT / "data" / "backups")}


@app.get("/api/backups/{backup_name}/download")
async def download_backup(backup_name: str, request: Request):
    _require_main_computer(request)
    backup_dir = ROOT / "data" / "backups"
    try:
        path = next(item for item in backup_dir.glob("*.db") if item.name == backup_name)
    except StopIteration as exc:
        raise HTTPException(404, "Копия не найдена") from exc
    return FileResponse(path, media_type="application/vnd.sqlite3", filename=path.name)


@app.post("/api/backups/{backup_name}/restore")
async def restore(backup_name: str, payload: RestoreBackupIn, request: Request) -> dict:
    _require_main_computer(request)
    if not payload.confirmed:
        raise HTTPException(400, "Нужно подтвердить восстановление")
    try:
        safety = restore_backup(settings.db_path, ROOT / "data" / "backups", backup_name)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    initialize()
    bootstrap_catalog(ROOT)
    seed_movies()
    return {"ok": True, "safety_backup": safety.name}


@app.post("/api/backups/import")
async def import_and_restore_backup(request: Request, confirmed: bool = False) -> dict:
    """Restore a local export after validating it and making a safety copy."""
    _require_main_computer(request)
    if not confirmed:
        raise HTTPException(400, "Нужно подтвердить восстановление")
    declared_size = request.headers.get("content-length")
    if declared_size and declared_size.isdigit() and int(declared_size) > MAX_IMPORTED_BACKUP_BYTES:
        raise HTTPException(400, "Файл копии слишком большой")
    backup_dir = ROOT / "data" / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    staging = backup_dir / f".uploaded-{secrets.token_hex(12)}.db"
    total = 0
    try:
        with staging.open("xb") as output:
            async for chunk in request.stream():
                total += len(chunk)
                if total > MAX_IMPORTED_BACKUP_BYTES:
                    raise HTTPException(400, "Файл копии слишком большой")
                output.write(chunk)
        imported = import_backup(backup_dir, staging)
        safety = restore_backup(settings.db_path, backup_dir, imported.name)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    finally:
        staging.unlink(missing_ok=True)
    initialize()
    bootstrap_catalog(ROOT)
    seed_movies()
    return {"ok": True, "imported_backup": imported.name, "safety_backup": safety.name}


@app.post("/api/privacy/delete")
async def delete_all_personal_data(payload: PrivacyDeleteIn, request: Request) -> dict:
    _require_main_computer(request)
    confirmation = "УДАЛИТЬ ВСЕ ДАННЫЕ"
    if not secrets.compare_digest(payload.confirmation.encode("utf-8"), confirmation.encode("utf-8")):
        raise HTTPException(400, "Введите фразу подтверждения полностью")
    with db_session() as db:
        session_ids = [row[0] for row in db.execute("SELECT id FROM sessions").fetchall()]
    try:
        result = delete_personal_data(settings.db_path, ROOT / "data" / "backups")
    except PrivacyDeleteError as exc:
        raise HTTPException(409, str(exc)) from exc
    await manager.close_sessions(session_ids, {"type": "privacy_reset"})
    return {"ok": True, **result}


@app.get("/api/movies/{movie_id}/{kind}")
async def media(movie_id: str, kind: str):
    if kind not in {"poster", "backdrop"}:
        raise HTTPException(404)
    movie = get_movie(movie_id)
    if not movie:
        raise HTTPException(404)
    cached = local_media(movie_id, kind)
    if cached:
        return FileResponse(cached)
    generated_art = genre_art(movie["genres"])
    if generated_art:
        return FileResponse(generated_art, headers={"Cache-Control": "public, max-age=86400"})
    return Response(placeholder_svg(movie_id, movie["title"], movie["year"], movie["genres"], wide=kind == "backdrop"), media_type="image/svg+xml", headers={"Cache-Control": "public, max-age=86400"})


@app.websocket("/ws/session/{session_id}/{user_id}")
async def websocket_session(websocket: WebSocket, session_id: int, user_id: str, code: str | None = None):
    if user_id not in {"lera", "nikita"}:
        await websocket.close(code=1008)
        return
    # A browser can retain an old session id after the app has been unpacked
    # into a fresh folder/database. Do not accept that socket and then crash
    # while broadcasting a state that no longer exists.
    try:
        session_state(session_id)
    except ValueError:
        await websocket.close(code=1008)
        return
    if not _is_loopback(websocket.client.host if websocket.client else None):
        if not secrets.compare_digest(code or "", session_access_code(session_id)):
            await websocket.close(code=1008)
            return
    await manager.connect(session_id, user_id, websocket)
    await publish_state(session_id, "presence")
    try:
        while True:
            message = await websocket.receive_text()
            if message == "ping":
                await websocket.send_json({"type": "pong"})
    except (WebSocketDisconnect, OSError):
        # A sleeping phone, browser refresh, or brief Wi-Fi outage is a normal
        # disconnect. The browser reconnects and reloads authoritative state.
        pass
    except RuntimeError as exc:
        # Starlette can report a close/send race as RuntimeError. Suppress only
        # that socket lifecycle case and keep unrelated programming errors loud.
        message = str(exc).lower()
        if "websocket" not in message or not any(word in message for word in ("disconnect", "close", "send")):
            raise
    finally:
        manager.disconnect(session_id, user_id, websocket)
        try:
            await publish_state(session_id, "presence")
        except ValueError:
            # The state may be removed/replaced while this browser disconnects.
            return


app.mount("/assets", StaticFiles(directory=STATIC), name="assets")


@app.get("/{path:path}")
async def frontend(path: str):
    if path.startswith("api/"):
        raise HTTPException(404, "API endpoint not found")
    index = STATIC / "index.html"
    if not index.exists():
        return HTMLResponse("Tonight frontend is missing", status_code=503)
    return FileResponse(index)
