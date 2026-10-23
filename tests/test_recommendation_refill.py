import asyncio
from pathlib import Path
import shutil
import subprocess

import pytest

from backend.database.db import db_session, loads
from backend.main import app
from backend.models.schemas import PreferencesIn
from backend.recommendation.engine import recommend
from backend.sessions.service import (
    active_session, choose_movie, choose_specific_recommendation,
    decline_selected_movie, ensure_participant, save_preferences,
    session_state, store_recommendations,
)
from tests.http_client import TestClient


def ready_evening():
    sid = active_session()['id']
    for user in ('lera', 'nikita'):
        ensure_participant(sid, user)
        save_preferences(sid, PreferencesIn(
            user_id=user, moods=['cozy'], energy='medium',
            max_runtime=150, min_year=1980, disliked_genres=['хоррор'],
        ))
    with db_session() as db:
        db.execute('UPDATE participants SET ready=1,progress=20 WHERE session_id=?', (sid,))
    initial = recommend(sid)
    assert len(initial) == 7
    store_recommendations(sid, initial)
    return sid, initial


def test_declining_entire_batch_refills_without_repeating_or_losing_answers():
    sid, initial = ready_evening()
    with db_session() as db:
        answers = [tuple(r) for r in db.execute('SELECT * FROM participants')]
    for movie in initial:
        choose_specific_recommendation(sid, movie['id'])
        decline_selected_movie(sid)
    state = session_state(sid)
    assert state['status'] == 'recommended' and state['selected'] is None
    assert state['recommendations']
    assert not {m['id'] for m in initial} & {m['id'] for m in state['recommendations']}
    assert all(m['runtime'] <= 150 and m['year'] >= 1980 and 'хоррор' not in m['genres']
               for m in state['recommendations'])
    with db_session() as db:
        assert [tuple(r) for r in db.execute('SELECT * FROM participants')] == answers
        assert not db.execute('SELECT * FROM watch_history').fetchall()


def test_choose_another_crosses_multiple_batches_without_repeats():
    sid, _ = ready_evening()
    client = TestClient(app)
    selected = client.post(f'/api/sessions/{sid}/choose').json()
    seen = {selected['id']}
    for _ in range(16):
        response = client.post(f'/api/sessions/{sid}/choose-another')
        assert response.status_code == 200, response.text
        movie = response.json()
        assert movie['id'] not in seen
        assert movie['runtime'] <= 150 and movie['year'] >= 1980
        seen.add(movie['id'])
    with db_session() as db:
        rejected = loads(db.execute('SELECT rejected_movies FROM sessions WHERE id=?', (sid,)).fetchone()[0], [])
    assert set(rejected) == seen - {movie['id']}


def test_decline_api_returns_the_next_batch_on_the_last_rejection():
    sid, initial = ready_evening()
    client = TestClient(app)
    for movie in initial:
        assert client.post(f"/api/sessions/{sid}/select/{movie['id']}").status_code == 200
        response = client.post(f'/api/sessions/{sid}/decline')
        assert response.status_code == 200
    assert response.json()['recommendations']
    assert not {m['id'] for m in initial} & {m['id'] for m in response.json()['recommendations']}


def test_already_empty_saved_batch_can_be_chosen_without_starting_over():
    sid, initial = ready_evening()
    from backend.database.db import dumps
    with db_session() as db:
        db.execute('UPDATE sessions SET rejected_movies=? WHERE id=?',
                   (dumps([m['id'] for m in initial]), sid))
    assert not session_state(sid)['recommendations']
    selected = choose_movie(sid)
    assert selected['id'] not in {m['id'] for m in initial}


def test_real_catalog_exhaustion_keeps_all_rejections_and_returns_to_results():
    sid, initial = ready_evening()
    from backend.database.db import dumps
    only = initial[0]
    with db_session() as db:
        db.execute('UPDATE movies SET release_status=NULL WHERE id!=?', (only['id'],))
        db.execute('UPDATE sessions SET recommendations=? WHERE id=?', (dumps([only]), sid))
    choose_specific_recommendation(sid, only['id'])
    with pytest.raises(ValueError):
        choose_movie(sid, exclude_current=True)
    state = session_state(sid)
    assert state['status'] == 'recommended' and state['selected'] is None
    assert state['recommendations'] == []
    with db_session() as db:
        assert loads(db.execute('SELECT rejected_movies FROM sessions WHERE id=?', (sid,)).fetchone()[0], []) == [only['id']]
        assert not db.execute('SELECT * FROM watch_history').fetchall()


def test_an_old_ai_result_cannot_replace_the_new_batch(monkeypatch):
    import backend.main as main
    sid, initial = ready_evening()
    next_batch = recommend(sid, 14)[7:]
    assert next_batch

    async def late_result(*args):
        store_recommendations(sid, next_batch)
        return list(reversed(initial))

    monkeypatch.setattr(main, 'rerank', late_result)
    asyncio.run(main._refine_recommendations_in_background(sid, initial, {}))
    assert {m['id'] for m in session_state(sid)['recommendations']} == {m['id'] for m in next_batch}


def test_choose_another_cannot_decline_a_movie_already_being_watched():
    sid, _ = ready_evening()
    selected = choose_movie(sid)
    with db_session() as db:
        db.execute("UPDATE sessions SET status='watching' WHERE id=?", (sid,))
    with pytest.raises(ValueError):
        choose_movie(sid, exclude_current=True)
    state = session_state(sid)
    assert state['status'] == 'watching' and state['selected']['id'] == selected['id']


def test_restoring_an_empty_evening_and_catalog_exhaustion_in_the_browser():
    if not shutil.which('node'):
        pytest.skip('Node required')
    script = r'''
const fs=require('fs'),vm=require('vm'),assert=require('assert');
const storage={getItem:()=>null,setItem:()=>{},removeItem:()=>{}};
const sandbox={document:{querySelector:()=>({})},localStorage:storage,sessionStorage:storage,
 location:{hostname:'localhost'},AbortController,setInterval:()=>1,setTimeout:()=>1,
 clearTimeout:()=>{},requestAnimationFrame:()=>{},URLSearchParams,URL};
vm.createContext(sandbox);
vm.runInContext(fs.readFileSync('frontend/app.js','utf8').replace(/\ninit\(\);\s*$/,''),sandbox);
vm.runInContext(`render=()=>{};shell=x=>x;toast=()=>{};
let requests=[];
const empty={id:3,status:'recommended',selected:null,recommendations:[],participants:{lera:{ready:true},nikita:{ready:true}}};
state.user='lera';state.session=structuredCloneForTest(empty);
api=async(path,options)=>{requests.push([path,options?.method]);return {...empty,recommendations:[{id:'new-film'}]};};`,
 Object.assign(sandbox,{structuredCloneForTest:x=>JSON.parse(JSON.stringify(x))}));
const run=code=>vm.runInContext(code,sandbox);
(async()=>{
 await run('continueSession()');
 assert.equal(run('requests.length'),1);
 assert.equal(run('requests[0][0]'),'/api/sessions/3/recommend');
 assert.equal(run('requests[0][1]'),'POST');
 assert.equal(run('state.view'),'results');
 assert.equal(run('state.session.recommendations[0].id'),'new-film');
 // A real exhausted catalog is a stable empty result, with explicit retry.
 run(`state.session=structuredCloneForTest(empty);requests=[];api=async(path)=>{requests.push(path);return structuredCloneForTest(empty)};`);
 await run('continueSession()');
 assert.equal(run('requests.length'),1);
 assert.match(run('renderNoAvailableMovies()'),/Повторить подбор/);
 assert.match(run('renderNoAvailableMovies()'),/отклонённых фильмов/);
 assert(!run('renderNoAvailableMovies()').includes('начните новый вечер'));
 // The last skipped movie must disappear even when there is no next candidate.
 run(`state.view='selected';state.session={...empty,status:'selected',selected:{id:'last'}};
 api=async(path)=>{if(path.endsWith('/choose-another'))throw new Error('Нет вариантов');return structuredCloneForTest(empty)};`);
 await run('chooseAnother()');
 assert.equal(run('state.view'),'results');
 assert.equal(run('state.session.selected'),null);
})().catch(e=>{console.error(e);process.exitCode=1});
'''
    result = subprocess.run(['node', '-e', script], cwd=Path(__file__).resolve().parents[1],
                            capture_output=True, text=True, encoding='utf-8')
    assert result.returncode == 0, result.stdout + result.stderr
