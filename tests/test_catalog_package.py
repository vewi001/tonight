import json
import hashlib
import stat
import sqlite3
import zipfile
from pathlib import Path

import pytest
from PIL import Image

from backend.catalog_package import CatalogPackageError, build_catalog_package, read_catalog_package


def source(tmp_path):
    root = tmp_path / 'source'
    root.mkdir()
    with sqlite3.connect(root / 'tonight.db') as db:
        db.execute('CREATE TABLE movies(id TEXT,title TEXT,year INTEGER,genres TEXT,poster_path TEXT,trailer_key TEXT,private_note TEXT)')
        db.execute("INSERT INTO movies VALUES('film','Film',2020,'[\"драма\"]','/private/poster','abcdefghijk','secret note')")
        db.execute('CREATE TABLE users(name TEXT)')
        db.execute("INSERT INTO users VALUES('Private viewer')")
    (root / '.env').write_text('TMDB_READ_TOKEN=secret')
    return root


def build(root, output, **kwargs):
    return build_catalog_package(root, output, version='1.0.0', min_app_version='1.6.6',
                                 created_at='2026-10-09T12:00:00Z', **kwargs)


def test_package_is_public_projection_and_deterministic(tmp_path):
    root = source(tmp_path)
    before = (root / 'tonight.db').read_bytes()
    first, second = tmp_path / 'a.zip', tmp_path / 'b.zip'
    build(root, first)
    build(root, second)
    assert first.read_bytes() == second.read_bytes()
    assert (root / 'tonight.db').read_bytes() == before
    package = read_catalog_package(first)
    assert package.version == '1.0.0' and package.min_app_version == '1.6.6'
    assert package.movies[0]['id'] == 'film'
    with zipfile.ZipFile(first) as bundle:
        assert set(bundle.namelist()) == {'tonight-catalog.json', 'movies.json'}
        content = bundle.read('movies.json')
        assert b'private' not in content and b'secret' not in content
        assert json.loads(content)[0]['genres'] == ['драма']


def test_existing_output_is_never_replaced(tmp_path):
    root = source(tmp_path)
    output = tmp_path / 'out.zip'
    output.write_bytes(b'keep')
    with pytest.raises(CatalogPackageError):
        build(root, output)
    assert output.read_bytes() == b'keep'


def test_media_requires_explicit_rights_review_and_only_matching_movies(tmp_path):
    root = source(tmp_path)
    posters = root / 'posters'
    posters.mkdir()
    with Image.new('RGB',(8,8),'red') as image:
        image.save(posters/'film.jpg')
    (posters / 'private.jpg').write_bytes(b'not a catalog movie')
    (posters / '.env').write_text('secret')
    with pytest.raises(CatalogPackageError):
        build(root, tmp_path / 'rejected.zip', include_media=True)
    assert not (tmp_path / 'rejected.zip').exists()
    output = tmp_path / 'media.zip'
    build(root, output, include_media=True, media_rights_reviewed=True)
    package = read_catalog_package(output)
    assert package.media_files == ('posters/film.jpg',)


def test_media_builder_strips_private_metadata_without_touching_source(tmp_path):
    root = source(tmp_path)
    (root/'posters').mkdir()
    path = root/'posters/film.jpg'
    exif = Image.Exif()
    exif[270] = 'private-location-note'
    with Image.new('RGB',(8,8),'red') as image:
        image.save(path,exif=exif)
    before = path.read_bytes()
    output = tmp_path/'clean.zip'
    build(root,output,include_media=True,media_rights_reviewed=True)
    assert path.read_bytes()==before
    with zipfile.ZipFile(output) as bundle:
        assert b'private-location-note' not in bundle.read('posters/film.jpg')


def test_reader_rejects_fake_image_even_with_correct_digest(tmp_path):
    good = tmp_path/'good.zip'
    build(source(tmp_path),good)
    with zipfile.ZipFile(good) as bundle:
        manifest = json.loads(bundle.read('tonight-catalog.json'))
        movies = bundle.read('movies.json')
    content = b'not an image'
    manifest['files']['posters/film.jpg'] = {'size':len(content),'sha256':hashlib.sha256(content).hexdigest()}
    bad = tmp_path/'bad.zip'
    with zipfile.ZipFile(bad,'w') as bundle:
        bundle.writestr('tonight-catalog.json',json.dumps(manifest))
        bundle.writestr('movies.json',movies)
        bundle.writestr('posters/film.jpg',content)
    with pytest.raises(CatalogPackageError):
        read_catalog_package(bad)


@pytest.mark.parametrize('version', ['v1.0.0','01.0.0','1.0','1.0.0-beta',True])
def test_invalid_version_is_rejected(tmp_path, version):
    with pytest.raises(CatalogPackageError):
        build_catalog_package(source(tmp_path), tmp_path/'bad.zip',version=version,min_app_version='1.6.6')


def test_private_movie_field_and_duplicate_identity_are_rejected(tmp_path):
    root = source(tmp_path)
    with sqlite3.connect(root/'tonight.db') as db:
        db.execute("INSERT INTO movies SELECT * FROM movies")
    with pytest.raises(CatalogPackageError):
        build(root,tmp_path/'bad.zip')


def test_untrusted_extra_file_rejected(tmp_path):
    output = tmp_path / 'out.zip'
    build(source(tmp_path),output)
    with zipfile.ZipFile(output,'a') as bundle:
        bundle.writestr('.env','secret')
    with pytest.raises(CatalogPackageError):
        read_catalog_package(output)


def test_tampering_and_incompatible_manifest_rejected(tmp_path):
    output = tmp_path / 'out.zip'
    build(source(tmp_path),output)
    with zipfile.ZipFile(output) as bundle:
        manifest = json.loads(bundle.read('tonight-catalog.json'))
        content = bundle.read('movies.json')
    for name, changed, data in [('tampered',manifest,content+b' '),
                                ('wrong-kind',{**manifest,'kind':'app'},content)]:
        bad = tmp_path / (name+'.zip')
        with zipfile.ZipFile(bad,'w') as bundle:
            bundle.writestr('tonight-catalog.json',json.dumps(changed))
            bundle.writestr('movies.json',data)
        with pytest.raises(CatalogPackageError):
            read_catalog_package(bad)


def rewrite_movie(path, changes):
    with zipfile.ZipFile(path) as bundle:
        manifest = json.loads(bundle.read('tonight-catalog.json'))
        movies = json.loads(bundle.read('movies.json'))
    movies[0].update(changes)
    content = json.dumps(movies).encode()
    manifest['files']['movies.json'] = {'size':len(content),'sha256':hashlib.sha256(content).hexdigest()}
    with zipfile.ZipFile(path,'w') as bundle:
        bundle.writestr('tonight-catalog.json',json.dumps(manifest))
        bundle.writestr('movies.json',content)


@pytest.mark.parametrize('changes', [
    {'tmdb_id':'abc'}, {'tmdb_id':True}, {'tmdb_id':0}, {'tmdb_id':-1},
    {'year':True}, {'rating':float('nan')}, {'genres':'drama'},
    {'private_note':'secret'}, {'poster_path':'/private'}, {'id':'CON'},
    {'id':'../escape'}, {'trailer_key':'https://example.com/private'},
])
def test_consumer_rejects_bad_types_and_private_fields_even_with_valid_digest(tmp_path, changes):
    path = tmp_path/'out.zip'
    build(source(tmp_path),path)
    rewrite_movie(path,changes)
    with pytest.raises(CatalogPackageError):
        read_catalog_package(path)


def test_zip_symlink_rejected(tmp_path):
    path = tmp_path/'out.zip'
    build(source(tmp_path),path)
    with zipfile.ZipFile(path,'a') as bundle:
        link = zipfile.ZipInfo('posters/film.jpg')
        link.create_system = 3
        link.external_attr = (stat.S_IFLNK | 0o777)<<16
        bundle.writestr(link,'../../.env')
    with pytest.raises(CatalogPackageError):
        read_catalog_package(path)


def test_actual_archive_size_limit(tmp_path,monkeypatch):
    import backend.catalog_package as module
    path = tmp_path/'out.zip'
    build(source(tmp_path),path)
    monkeypatch.setattr(module,'MAX_RELEASE_BYTES',path.stat().st_size-1)
    with pytest.raises(CatalogPackageError):
        read_catalog_package(path)


@pytest.mark.parametrize('target', ['manifest','movie'])
def test_duplicate_json_keys_rejected_even_with_valid_file_digest(tmp_path,target):
    path = tmp_path/'out.zip'
    build(source(tmp_path),path)
    with zipfile.ZipFile(path) as bundle:
        manifest = json.loads(bundle.read('tonight-catalog.json'))
        content = bundle.read('movies.json')
    if target=='movie':
        content = content.replace(b'"id":"film"',b'"id":"different","id":"film"')
        manifest['files']['movies.json'] = {'size':len(content),'sha256':hashlib.sha256(content).hexdigest()}
    encoded = json.dumps(manifest)
    if target=='manifest':
        encoded = encoded.replace('"version": "1.0.0"','"version": "9.9.9", "version": "1.0.0"')
    with zipfile.ZipFile(path,'w') as bundle:
        bundle.writestr('tonight-catalog.json',encoded)
        bundle.writestr('movies.json',content)
    with pytest.raises(CatalogPackageError):
        read_catalog_package(path)


@pytest.mark.parametrize('app_version,compatible', [
    ('1.6.5',False),('1.6.6',True),('1.6.10',True),('1.10.0',True),
    ('10.0.0',True),('1.0',False),('v1.6.6',False),
])
def test_optional_app_compatibility_gate_uses_numeric_versions(tmp_path,app_version,compatible):
    path = tmp_path/'out.zip'
    build(source(tmp_path),path)
    if compatible:
        assert read_catalog_package(path,app_version=app_version).version=='1.0.0'
    else:
        with pytest.raises(CatalogPackageError):
            read_catalog_package(path,app_version=app_version)
