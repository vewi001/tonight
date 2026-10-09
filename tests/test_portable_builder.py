from scripts.build_portable import update_payload_files


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
