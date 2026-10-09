from contextlib import closing

from backend.catalog_status import get_catalog_summary
from backend.database.db import connect, initialize


def setup(tmp_path):
    path = tmp_path / 'test.db'
    initialize(path)
    return connect(path)


def test_empty_legacy_catalog_has_no_invented_version_or_date(tmp_path):
    with closing(setup(tmp_path)) as db:
        assert get_catalog_summary(db,tmp_path/'data') == {
            'movie_count':0,'local_poster_count':0,'trailer_link_count':0,
            'poster_and_trailer_count':0,'catalog_version':None,'last_successful_update':None}


def test_counts_movies_not_files_or_remote_video_availability(tmp_path):
    data = tmp_path/'data'
    posters = data/'posters'
    posters.mkdir(parents=True)
    for name,content in [('one.jpg',b'poster'),('one.png',b'second'),('two.jpg',b''),('unknown.jpg',b'other')]:
        (posters/name).write_bytes(content)
    (posters/'three.webp').mkdir()
    with closing(setup(tmp_path)) as db:
        db.executemany('INSERT INTO movies(id,title,year,genres,trailer_key) VALUES(?,?,2020,?,?)',[
            ('one','One','[]','abcdefghijk'),('two','Two','[]','https://youtube.com/evil'),
            ('three','Three','[]','ABCDEFGHIJK'),('../outside','Unsafe','[]',None)])
        db.execute("INSERT INTO app_meta VALUES('tmdb_token','secret')")
        db.commit()
        summary = get_catalog_summary(db,data)
        assert summary['movie_count']==4 and summary['local_poster_count']==1
        assert summary['trailer_link_count']==2 and summary['poster_and_trailer_count']==1
        assert 'secret' not in str(summary) and str(tmp_path) not in str(summary)
        assert not db.in_transaction


def test_committed_catalog_version_is_independent_of_app_version(tmp_path):
    with closing(setup(tmp_path)) as db:
        db.executemany('INSERT INTO app_meta VALUES(?,?)',[
            ('catalog_version','2.0.1'),('catalog_updated_at','2026-10-09T18:00:00Z'),('app_version','1.6.5')])
        db.commit()
        result = get_catalog_summary(db,tmp_path/'data')
        assert result['catalog_version']=='2.0.1'
        assert result['last_successful_update']=='2026-10-09T18:00:00Z'


def test_invalid_saved_metadata_and_linked_poster_directory_are_not_claimed(tmp_path,monkeypatch):
    import backend.catalog_status as status
    data = tmp_path/'data'
    (data/'posters').mkdir(parents=True)
    (data/'posters'/'one.jpg').write_bytes(b'poster')
    monkeypatch.setattr(status,'_is_link',lambda path:path==data/'posters')
    with closing(setup(tmp_path)) as db:
        db.execute("INSERT INTO movies(id,title,year,genres) VALUES('one','One',2020,'[]')")
        db.executemany('INSERT INTO app_meta VALUES(?,?)',[
            ('catalog_version','private-invalid-value'),('catalog_updated_at','not a date')])
        db.commit()
        result = get_catalog_summary(db,data)
        assert result['local_poster_count']==0
        assert result['catalog_version'] is None and result['last_successful_update'] is None
