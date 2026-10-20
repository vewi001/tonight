from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
import json

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from backend.main import app
from backend.database.db import db_session, dumps, loads, initialize
from backend.sessions import movie_match as mm
from backend.sessions.service import active_session


A, B, C = 'a'*64, 'b'*64, 'c'*64


def browser(token, remote=True):
    return TestClient(app, client=('192.168.1.50' if remote else '127.0.0.1', 50000), headers={'X-Match-Token': token})


def create(profile=None):
    a = browser(A, False)
    r = a.post('/api/sessions/new?movie_match=true'+('&profile='+profile if profile else ''))
    assert r.status_code == 200, r.text
    return a, r.json()


def get(client, sid):
    r = client.get(f'/api/sessions/{sid}/match')
    assert r.status_code == 200, r.text
    return r.json()


def act(client, sid, op, **extra):
    version = get(client, sid)['version']
    return client.post(f'/api/sessions/{sid}/match', json={'op': op, 'version': version, **extra})


def pair():
    a, room = create()
    b = browser(B)
    assert b.post('/api/movie-match/join', json={'room': room['room']}).status_code == 200
    sid = room['id']
    assert act(a, sid, 'ready').status_code == 200
    assert act(b, sid, 'ready').json()['phase'] == 'voting'
    return a, b, sid


def match(a, b, sid):
    mid = get(a, sid)['card']['id']
    assert act(a, sid, 'vote', movie_id=mid, vote='yes').json()['matches'] == []
    assert act(b, sid, 'vote', movie_id=mid, vote='yes').json()['matches'][0]['id'] == mid
    return mid


def test_complete_two_participant_flow_requires_two_explicit_votes_and_final_confirmations():
    a, b, sid = pair()
    mid = match(a, b, sid)
    assert act(a, sid, 'propose', movie_id=mid).json()['phase'] == 'voting'
    assert act(a, sid, 'confirm', movie_id=mid).json()['phase'] == 'voting'
    final = act(b, sid, 'confirm', movie_id=mid).json()
    assert final['phase'] == 'finished' and final['final']['id'] == mid
    assert act(a, sid, 'save', movie_id=mid).json()['saved'] == [mid]
    assert get(b, sid)['saved'] == []
    with db_session() as db:
        for table in ['watchlist', 'feedback', 'swipes', 'viewer_movie_actions', 'watch_history']:
            assert db.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0] == 0
    assert act(a, sid, 'close').json()['phase'] == 'closed'
    assert get(b, sid)['phase'] == 'closed'
    assert act(b, sid, 'vote', movie_id=mid, vote='yes').status_code == 410


def test_third_browser_cannot_claim_or_read_or_change_a_vote_even_with_evening_code():
    a, b, sid = pair()
    room = get(a, sid)
    c = browser(C)
    assert c.post('/api/movie-match/join', json={'room': room['room']}).status_code == 409
    assert c.get(f'/api/sessions/{sid}/match').status_code == 403
    assert c.post(f'/api/sessions/{sid}/match', json={'op':'vote','version':room['version'],'movie_id':room['card']['id'],'vote':'yes'}).status_code == 403
    # Legacy endpoints must not bypass the new seat authorization on loopback.
    for client in [a, b, browser(C, False)]:
        assert client.get(f'/api/sessions/{sid}').status_code == 403
        assert client.post(f'/api/sessions/{sid}/join',json={'user_id':'lera'}).status_code == 403
        assert client.post(f'/api/sessions/{sid}/choose').status_code == 403
    assert c.get('/api/history').status_code == 403
    assert c.get('/api/taste/lera').status_code == 403


def test_same_browser_and_new_tab_rejoin_same_seat_without_consuming_second_seat():
    a, room = create()
    for _ in range(3):
        same = browser(A).post('/api/movie-match/join',json={'room':room['room']}).json()
        assert same['me'] == 0 and len(same['people']) == 1
    assert browser(B).post('/api/movie-match/join',json={'room':room['room']}).json()['me'] == 1


def test_votes_survive_database_reopen_refresh_and_request_retry():
    a, b, sid = pair()
    before = get(a, sid)
    mid = before['card']['id']
    payload = {'op':'vote','version':before['version'],'movie_id':mid,'vote':'yes'}
    assert a.post(f'/api/sessions/{sid}/match',json=payload).status_code == 200
    initialize()
    restored = browser(A, False)
    for _ in range(3):
        assert restored.post(f'/api/sessions/{sid}/match',json=payload).json()['people'][0]['progress'] == 1
    payload['vote'] = 'no'
    assert restored.post(f'/api/sessions/{sid}/match',json=payload).status_code == 409
    assert get(b, sid)['people'][0]['progress'] == 1
    assert get(restored, sid)['card']['id'] != mid


def test_simultaneous_votes_and_conflicting_tabs_are_atomic():
    a, b, sid = pair()
    snapshot = get(a, sid)
    mid = snapshot['card']['id']
    action = mm.Action(op='vote',version=snapshot['version'],movie_id=mid,vote='yes')
    with ThreadPoolExecutor(4) as pool:
        results = list(pool.map(lambda token:mm.act(sid,token,action),[A,B,A,B]))
    assert get(a,sid)['people'] == [{'joined':True,'ready':True,'progress':1}]*2
    assert len(get(a,sid)['matches']) == 1
    assert all(r['version'] >= snapshot['version'] for r in results)


def test_independent_readiness_from_one_snapshot_merges_and_retries():
    a, room = create()
    b = browser(B)
    assert b.post('/api/movie-match/join', json={'room': room['room']}).status_code == 200
    sid = room['id']
    before = get(a, sid)
    payload = {'op': 'ready', 'version': before['version']}
    path = f'/api/sessions/{sid}/match'
    assert a.post(path, json=payload).status_code == 200
    assert get(b, sid)['filters'] == before['filters']
    assert b.post(path, json=payload).json()['phase'] == 'voting'
    for client in (a, b):
        assert client.post(path, json=payload).status_code == 200
    assert all(p['ready'] for p in get(a, sid)['people'])


def test_parallel_readiness_is_atomic_including_duplicate_tabs():
    a, room = create()
    browser(B).post('/api/movie-match/join', json={'room': room['room']})
    action = mm.Action(op='ready', version=get(a, room['id'])['version'])
    with ThreadPoolExecutor(4) as pool:
        results = list(pool.map(lambda token: mm.act(room['id'], token, action), [A, B, A, B]))
    assert get(a, room['id'])['phase'] == 'voting'
    assert all(r['phase'] in {'lobby', 'voting'} for r in results)


def test_final_consent_merges_with_votes_and_same_proposal_confirmation():
    a, b, sid = pair()
    mid = match(a, b, sid)
    proposed = act(a, sid, 'propose', movie_id=mid).json()
    other = proposed['card']['id']
    confirmation = mm.Action(op='confirm', version=proposed['version'], movie_id=mid)
    vote = mm.Action(op='vote', version=proposed['version'], movie_id=other, vote='yes')
    with ThreadPoolExecutor(4) as pool:
        # A's consent was explicit at proposal time; both tabs may confirm it.
        jobs = [pool.submit(mm.act, sid, A, vote), pool.submit(mm.act, sid, A, confirmation),
                pool.submit(mm.act, sid, B, confirmation), pool.submit(mm.act, sid, B, confirmation)]
        # A vote can arrive after the final decision; it merges without
        # reopening it or requiring the user to resend an independent answer.
        for job in jobs:
            job.result()
    final = get(b, sid)
    assert final['phase'] == 'finished' and final['final']['id'] == mid
    assert final['confirmed'] == [0, 1]


def test_same_movie_reproposal_does_not_accept_old_consent_and_future_versions():
    a, b, sid = pair()
    mid = match(a, b, sid)
    old = act(a, sid, 'propose', movie_id=mid).json()
    act(a, sid, 'cancel')
    current = act(a, sid, 'propose', movie_id=mid).json()
    path = f'/api/sessions/{sid}/match'
    assert b.post(path, json={'op':'confirm', 'version':old['version'], 'movie_id':mid}).status_code == 409
    assert b.post(path, json={'op':'confirm', 'version':current['version']+100, 'movie_id':mid}).status_code == 409
    assert get(b, sid)['phase'] == 'voting'


def test_changing_conditions_back_still_invalidates_earlier_readiness():
    a, room = create()
    b = browser(B)
    b.post('/api/movie-match/join', json={'room':room['room']})
    sid = room['id']
    old = get(a, sid)
    act(a, sid, 'ready')
    act(b, sid, 'filters', filters={**old['filters'], 'max_runtime':90})
    restored = act(b, sid, 'filters', filters=old['filters']).json()
    assert not any(p['ready'] for p in restored['people'])
    assert a.post(f'/api/sessions/{sid}/match', json={'op':'ready','version':old['version']}).status_code == 409


@pytest.mark.parametrize('vote',['no','watched'])
def test_negative_or_watched_vote_never_creates_a_match_or_reveals_private_vote(vote):
    a,b,sid=pair()
    mid=get(a,sid)['card']['id']
    assert act(a,sid,'vote',movie_id=mid,vote=vote).status_code==200
    if vote == 'no':
        assert act(b,sid,'vote',movie_id=mid,vote='yes').json()['matches']==[]
    body=json.dumps(get(b,sid))
    assert '"votes"' not in body and '"key"' not in body and A not in body
    assert 'moods' not in body and 'ranking_factors' not in body


def test_unilateral_filter_change_pauses_voting_and_requires_both_to_accept():
    a,b,sid=pair()
    mid=match(a,b,sid)
    old=get(a,sid)
    filters={**old['filters'],'max_runtime':90,'min_rating':7,'min_year':2000,'max_year':2025,'included_genres':['комедия'],'exclude_watched':False}
    changed=act(a,sid,'filters',filters=filters).json()
    assert changed['phase']=='lobby'
    assert all(not p['ready'] for p in changed['people'])
    assert get(b,sid)['filters']==filters
    assert a.post(f'/api/sessions/{sid}/match',json={'op':'ready','version':old['version']}).status_code==409
    assert act(a,sid,'vote',movie_id=mid,vote='no').status_code==409
    assert act(a,sid,'ready').status_code==200
    ready=act(b,sid,'ready')
    assert ready.status_code==200,ready.text
    card=ready.json()['card']
    assert card['runtime']<=90 and card['rating']>=7 and 2000<=card['year']<=2025
    assert 'комедия' in card['genres']
    # A delayed packet from the old conditions cannot vote in the new round.
    assert a.post(f'/api/sessions/{sid}/match',json={'op':'vote','version':old['version'],'movie_id':card['id'],'vote':'yes'}).status_code==409
    assert get(a,sid)['people'][0]['progress']==1


def test_impossible_filters_are_explained_without_fake_matches_or_relaxation():
    a,b,sid=pair()
    filters={**get(a,sid)['filters'],'max_runtime':1}
    assert act(a,sid,'filters',filters=filters).status_code==200
    assert act(a,sid,'ready').status_code==200
    r=act(b,sid,'ready')
    assert r.status_code==409 and 'Подходящих фильмов нет' in r.json()['detail']
    assert get(a,sid)['phase']=='lobby' and get(a,sid)['matches']==[]
    bad={**filters,'included_genres':['комедия'],'excluded_genres':['комедия']}
    assert act(a,sid,'filters',filters=bad).status_code==422


def test_arbitrary_films_and_stale_final_proposals_are_rejected():
    a,b,sid=pair()
    mid=match(a,b,sid)
    assert act(a,sid,'vote',movie_id='not-in-catalog',vote='yes').status_code==409
    assert act(a,sid,'propose',movie_id='not-in-catalog').status_code==409
    assert act(a,sid,'propose',movie_id=mid).status_code==200
    old=get(b,sid)
    assert act(a,sid,'cancel').status_code==200
    assert b.post(f'/api/sessions/{sid}/match',json={'op':'confirm','version':old['version'],'movie_id':mid}).status_code==409
    assert get(b,sid)['final'] is None


def test_expired_invalid_links_and_participant_leave():
    a,room=create()
    assert browser(B).post('/api/movie-match/join',json={'room':'invalid-invitation-000000'}).status_code==404
    with db_session() as db:
        data=mm.read(db,room['id']);data['expires_at']=(mm.now()-timedelta(hours=1)).isoformat()
        db.execute('UPDATE sessions SET match_data=? WHERE id=?',(dumps(data),room['id']))
    assert browser(B).post('/api/movie-match/join',json={'room':room['room']}).status_code==410
    assert get(a,room['id'])['phase']=='expired'
    a,b,sid=pair()
    assert act(b,sid,'leave').json()['phase']=='left'
    assert get(a,sid)['phase']=='left'
    assert act(a,sid,'ready').status_code==410


def test_match_does_not_replace_normal_tonight_active_session_and_guest_cannot_borrow_profile():
    from backend.recommendation.exclusions import active_evening
    normal=active_session()
    a,room=create('lera')
    assert active_session()['id']==normal['id']
    with db_session() as db:
        assert active_evening(db)['id']==normal['id']
    remote=browser(C).post('/api/sessions/new?movie_match=true&profile=nikita').json()
    with db_session() as db:
        assert mm.read(db,remote['id'])['profile'] is None
        assert mm.read(db,room['id'])['profile']=='lera'


def test_ws_uses_existing_manager_and_never_sends_votes_or_profile_and_reconnects():
    a,b,sid=pair()
    for _ in range(2):
        with a.websocket_connect(f'/ws/session/{sid}/lera') as ws:
            event=ws.receive_json()
            assert event['type']=='match_changed' and event['presence']['lera']
            assert 'session' not in event and 'votes' not in event
            ws.send_text('ping')
            assert ws.receive_json()=={'type':'pong'}
    with pytest.raises(WebSocketDisconnect):
        with browser(C,False).websocket_connect(f'/ws/session/{sid}/lera'):
            pass
    with pytest.raises(WebSocketDisconnect):
        with a.websocket_connect(f'/ws/session/{sid}/nikita'):
            pass


def test_qr_is_scoped_to_invitation_and_no_credentials_returned_or_logged_in_url():
    a,room=create()
    sid=room['id']
    assert a.get(f'/api/sessions/{sid}/match/qr',params={'room':room['room']}).headers['content-type'].startswith('image/svg+xml')
    assert a.get(f'/api/sessions/{sid}/match/qr?room=wrong').status_code==404
    r=a.get(f'/api/sessions/{sid}/match')
    assert 'HttpOnly' in r.headers['set-cookie'] and 'SameSite=strict' in r.headers['set-cookie']
    assert 'no-store' in r.headers['cache-control']
    assert A not in r.text


def test_duplicate_vote_cannot_overwrite_someone_else_and_unknown_fields_are_rejected():
    a,b,sid=pair();mid=get(a,sid)['card']['id']
    r=a.post(f'/api/sessions/{sid}/match',json={'op':'vote','version':1,'movie_id':mid,'vote':'yes','user_id':'nikita'})
    assert r.status_code==422
    assert get(b,sid)['people'][1]['progress']==0


def test_private_exclusions_are_reused_but_frozen_without_exposing_them_to_guest():
    from backend.recommendation.exclusions import change_rule
    change_rule('lera','permanent',kind='movie',value='arrival')
    a,room=create('lera');sid=room['id'];b=browser(B)
    assert b.post('/api/movie-match/join',json={'room':room['room']}).status_code==200
    assert act(a,sid,'ready').status_code==200
    assert act(b,sid,'ready').status_code==200
    with db_session() as db:
        data=mm.read(db,sid)
        assert 'arrival' not in data['deck']
        original={m['id'] for m in mm.candidates(db,sid,data)}
    # Editing another screen must never silently change agreed room conditions.
    change_rule('lera','permanent',kind='genre',value='комедия')
    with db_session() as db:
        assert {m['id'] for m in mm.candidates(db,sid,mm.read(db,sid))}==original
    body=get(b,sid)
    assert 'policy' not in body and 'profile' not in body


def test_old_closed_room_credentials_are_cleaned_and_normal_sessions_preserved():
    a,room=create();sid=room['id']
    with db_session() as db:
        data=mm.read(db,sid);data['expires_at']=(mm.now()-timedelta(days=8)).isoformat()
        db.execute('UPDATE sessions SET match_data=? WHERE id=?',(dumps(data),sid))
    normal=active_session()
    create()
    with db_session() as db:
        assert db.execute('SELECT match_data FROM sessions WHERE id=?',(sid,)).fetchone()[0]=='{}'
        assert db.execute('SELECT id FROM sessions WHERE id=?',(normal['id'],)).fetchone()
