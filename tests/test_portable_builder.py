from scripts.build_portable import update_payload_files


def test_portable_readme_describes_the_built_version_without_old_download_links():
    from scripts.build_portable import portable_readme
    for version in ('1.6.6','2.0.0'):
        text = portable_readme(version)
        assert 'Tonight '+version in text
        assert 'Tonight-update-'+version+'.zip' in text
        assert 'https://github.com/vewi001/tonight/releases' in text
        assert 'Обновить каталог' in text and 'Обновить приложение' in text
        assert 'TMDB-токен' in text and '1.6.5.zip' not in text
        assert '.env' in text and 'data/' in text


def test_portable_staging_is_new_and_never_removes_existing_work(tmp_path):
    from scripts.build_portable import new_staging_directory
    existing = tmp_path / 'work' / 'portable-stage'
    existing.mkdir(parents=True)
    marker = existing / 'keep.txt'
    marker.write_text('unrelated previous build', encoding='utf-8')
    first = new_staging_directory(tmp_path)
    second = new_staging_directory(tmp_path)
    assert first != second
    assert first.is_dir() and second.is_dir()
    assert first.parent == (tmp_path / 'work').resolve()
    assert marker.read_text(encoding='utf-8') == 'unrelated previous build'


def test_update_payload_includes_future_updater_but_never_user_data(tmp_path):
    for name in ("Tonight.exe", "Обновить Tonight.exe", ".env", ".env.example", "README.txt", "PRIVACY.txt"):
        (tmp_path / name).write_bytes(b"fixture")
    (tmp_path / "catalog").mkdir()
    (tmp_path / "catalog" / "starter.db").write_bytes(b"catalog")
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "tonight.db").write_bytes(b"personal")
    payload = update_payload_files(tmp_path)
    assert "Обновить Tonight.exe" in payload
    assert "catalog/starter.db" in payload
    assert ".env" not in payload
    assert "data/tonight.db" not in payload


def test_portable_builder_explicitly_includes_raster_codecs(tmp_path,monkeypatch):
    import sys
    from types import ModuleType
    from scripts.build_portable import _build
    calls = []
    installer = ModuleType('PyInstaller')
    installer.__path__ = []
    entry = ModuleType('PyInstaller.__main__')
    entry.run = lambda args:calls.append(args)
    installer.__main__ = entry
    monkeypatch.setitem(sys.modules,'PyInstaller',installer)
    monkeypatch.setitem(sys.modules,'PyInstaller.__main__',entry)
    _build('desktop.py','Tonight',tmp_path/'stage',tmp_path/'work')
    assert '--hidden-import=PIL.JpegImagePlugin' in calls[0]
    assert '--hidden-import=PIL.PngImagePlugin' in calls[0]
    assert '--hidden-import=PIL.WebPImagePlugin' in calls[0]
