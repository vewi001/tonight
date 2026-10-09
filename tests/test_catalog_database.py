import json
import sqlite3
from contextlib import closing

import pytest

from backend.catalog_database import merge_catalog_movies
from backend.catalog_package import CatalogPackageError
from backend.database.db import connect, initialize


def movie(identifier='new', **extra):
    return {'id':identifier, 'title':'Film', 'year':2020, 'genres':['драма'], **extra}


@pytest.fixture
def database(tmp_path):
    path = tmp_path / 'test.db'
    initialize(path)
    with closing(connect(path)) as db:
        yield db


def snapshot(db):
    tables = [row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")
              if row[0] not in {'movies','catalog_field_baselines','sqlite_sequence'}]
    return {table:[tuple(row) for row in db.execute(f'SELECT * FROM "{table}"')] for table in tables}


def test_new_movie_has_baseline_and_outer_rollback_removes_all_changes(database):
    database.execute('BEGIN IMMEDIATE')
    result = merge_catalog_movies(database,[movie(tmdb_id=12,overview='First')])
    assert result == {'new':'new'}
    assert database.in_transaction
    assert database.execute('SELECT genres FROM movies').fetchone()[0] == '["драма"]'
    baseline = json.loads(database.execute('SELECT fields FROM catalog_field_baselines').fetchone()[0])
    assert baseline['overview']=='First' and 'id' not in baseline and 'tmdb_id' not in baseline
    database.rollback()
    assert database.execute('SELECT COUNT(*) FROM movies').fetchone()[0] == 0
    assert not database.execute("SELECT name FROM sqlite_master WHERE name='catalog_field_baselines'").fetchone()


def test_managed_corrections_and_user_overrides_across_updates(database):
    database.execute('BEGIN IMMEDIATE')
    merge_catalog_movies(database,[movie(tmdb_id=12,overview='First',keywords=['old'])])
    database.commit()
    database.execute("UPDATE movies SET overview='My own', genres='[]'")
    database.commit()
    database.execute('BEGIN IMMEDIATE')
    merge_catalog_movies(database,[movie('remote',tmdb_id=12,title='Corrected',overview='Provider',keywords=['new'])])
    database.commit()
    row = database.execute('SELECT * FROM movies').fetchone()
    assert row['id']=='new' and row['title']=='Corrected' and row['overview']=='My own'
    assert row['genres']=='[]' and json.loads(row['keywords'])==['new']
    assert json.loads(database.execute('SELECT fields FROM catalog_field_baselines').fetchone()[0])['overview']=='Provider'


def test_legacy_identity_and_every_personal_table_are_preserved(database):
    database.execute("INSERT INTO movies(id,title,year,genres) VALUES('starter','Film',2020,'[\"драма\"]')")
    database.execute("INSERT INTO sessions(id,session_date,title,selected_movie_id,created_at,updated_at) VALUES(1,'2026-10-09','Evening','starter','now','now')")
    database.execute("INSERT INTO watch_history(id,session_id,movie_id,watched_at) VALUES(1,1,'starter','now')")
    database.execute("INSERT INTO feedback VALUES(1,'lera',5,'now')")
    database.execute("INSERT INTO evening_feedback VALUES(1,'lera',1,'now')")
    database.execute("INSERT INTO participants(session_id,user_id,joined_at) VALUES(1,'lera','now')")
    database.execute("INSERT INTO swipes VALUES(1,'lera','starter','like','now')")
    database.execute("INSERT INTO swipe_decks VALUES(1,'lera','starter',1)")
    database.execute("INSERT INTO watchlist(movie_id,saved_at) VALUES('starter','now')")
    database.execute("INSERT INTO weekly_picks VALUES('2026-10-05',1,'starter','reason','now')")
    database.execute("INSERT INTO avoid_similar(user_id,movie_id,created_at) VALUES('lera','starter','now')")
    database.execute("INSERT INTO taste_genre_exclusions VALUES('lera','ужасы','now')")
    database.execute("INSERT INTO taste_profile_resets VALUES('lera',1,1,'now')")
    database.execute("INSERT INTO app_meta VALUES('private','keep')")
    database.commit()
    before = snapshot(database)
    database.execute('BEGIN IMMEDIATE')
    assert merge_catalog_movies(database,[movie('remote',tmdb_id=12,overview='Added')])=={'remote':'starter'}
    database.commit()
    assert snapshot(database)==before
    row = database.execute('SELECT * FROM movies').fetchone()
    assert row['id']=='starter' and row['tmdb_id']==12 and row['overview']=='Added'
    baseline = json.loads(database.execute('SELECT fields FROM catalog_field_baselines').fetchone()[0])
    assert 'title' not in baseline and 'genres' not in baseline
    assert not database.execute('PRAGMA foreign_key_check').fetchall()


def test_mid_batch_sql_failure_rolls_back_movies_baselines_but_not_callers_work(database):
    database.execute("CREATE TRIGGER fail_catalog BEFORE INSERT ON movies WHEN NEW.id='bad' BEGIN SELECT RAISE(ABORT,'test failure'); END")
    database.commit()
    database.execute('BEGIN IMMEDIATE')
    database.execute("INSERT INTO app_meta VALUES('caller','keep')")
    with pytest.raises(sqlite3.IntegrityError):
        merge_catalog_movies(database,[movie('good',tmdb_id=1),movie('bad',tmdb_id=2)])
    assert database.execute('SELECT COUNT(*) FROM movies').fetchone()[0]==0
    assert not database.execute("SELECT name FROM sqlite_master WHERE name='catalog_field_baselines'").fetchone()
    assert database.execute("SELECT value FROM app_meta WHERE key='caller'").fetchone()[0]=='keep'
    assert database.in_transaction


def test_invalid_or_conflicting_batch_has_no_partial_writes(database):
    database.execute('BEGIN IMMEDIATE')
    merge_catalog_movies(database,[movie(tmdb_id=12)])
    before = [tuple(row) for row in database.execute('SELECT * FROM movies')]
    with pytest.raises(CatalogPackageError):
        merge_catalog_movies(database,[movie('good',tmdb_id=13),movie('new',tmdb_id=14)])
    assert [tuple(row) for row in database.execute('SELECT * FROM movies')]==before
    with pytest.raises(CatalogPackageError):
        merge_catalog_movies(database,[movie(private_note='secret')])


def test_requires_transaction_and_foreign_keys(database):
    with pytest.raises(CatalogPackageError):
        merge_catalog_movies(database,[movie()])
    database.execute('PRAGMA foreign_keys=OFF')
    database.execute('BEGIN IMMEDIATE')
    with pytest.raises(CatalogPackageError):
        merge_catalog_movies(database,[movie()])


def test_corrupted_local_json_is_not_silently_replaced(database):
    database.execute("INSERT INTO movies(id,title,year,genres) VALUES('legacy','Film',2020,'broken')")
    database.commit()
    database.execute('BEGIN IMMEDIATE')
    with pytest.raises(CatalogPackageError):
        merge_catalog_movies(database,[movie(tmdb_id=12)])
    assert database.execute('SELECT genres FROM movies').fetchone()[0]=='broken'


def test_repeat_merge_has_no_duplicates_and_provider_null_never_clears(database):
    database.execute('BEGIN IMMEDIATE')
    merge_catalog_movies(database,[movie(tmdb_id=12,overview='First',keywords=['known'])])
    database.commit()
    database.execute('BEGIN IMMEDIATE')
    update = movie('alias',tmdb_id=12,overview=None)
    merge_catalog_movies(database,[update])
    database.commit()
    before = [tuple(row) for row in database.execute('SELECT * FROM movies')]
    baseline = database.execute('SELECT fields FROM catalog_field_baselines').fetchone()[0]
    database.execute('BEGIN IMMEDIATE')
    merge_catalog_movies(database,[update])
    database.commit()
    assert [tuple(row) for row in database.execute('SELECT * FROM movies')]==before
    assert database.execute('SELECT fields FROM catalog_field_baselines').fetchone()[0]==baseline
    assert database.execute('SELECT overview FROM movies').fetchone()[0]=='First'
    assert json.loads(baseline)['keywords']==['known']


def test_mid_batch_failure_restores_existing_metadata_and_baseline(database):
    database.execute('BEGIN IMMEDIATE')
    merge_catalog_movies(database,[movie(tmdb_id=12,title='First')])
    database.commit()
    before = [tuple(row) for row in database.execute('SELECT * FROM movies')]
    baseline = database.execute('SELECT fields FROM catalog_field_baselines').fetchone()[0]
    database.execute("CREATE TRIGGER fail_catalog BEFORE INSERT ON movies WHEN NEW.id='bad' BEGIN SELECT RAISE(ABORT,'test failure'); END")
    database.commit()
    database.execute('BEGIN IMMEDIATE')
    with pytest.raises(sqlite3.IntegrityError):
        merge_catalog_movies(database,[movie(tmdb_id=12,title='Corrected'),movie('bad',tmdb_id=13)])
    assert [tuple(row) for row in database.execute('SELECT * FROM movies')]==before
    assert database.execute('SELECT fields FROM catalog_field_baselines').fetchone()[0]==baseline
