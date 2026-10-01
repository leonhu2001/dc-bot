from pathlib import Path

from core import database
from views.voice import build_vip_whitelist_overwrite


def _configure_temp_database(monkeypatch, tmp_path: Path) -> Path:
    db_path = tmp_path / "bot.db"
    monkeypatch.setattr(database, "_DB_FILE", db_path)
    monkeypatch.setattr(database, "_DATA_FILE", tmp_path / "bot_data.json")
    monkeypatch.setattr(database, "_BACKUP_DIR", tmp_path / "backups")
    monkeypatch.setattr(database, "_INIT_DATABASE", database.init_database)
    return db_path


def test_vip_whitelist_persists_and_deduplicates(monkeypatch, tmp_path):
    _configure_temp_database(monkeypatch, tmp_path)

    added = database.add_vip_voice_room_whitelist_user(
        1001,
        2002,
        added_by=1001,
    )
    duplicate = database.add_vip_voice_room_whitelist_user(
        1001,
        2002,
        added_by=1001,
    )

    rows = database.list_vip_voice_room_whitelist(1001)

    assert added is True
    assert duplicate is False
    assert len(rows) == 1
    assert rows[0]["owner_id"] == 1001
    assert rows[0]["user_id"] == 2002
    assert rows[0]["added_by"] == 1001

    assert database.remove_vip_voice_room_whitelist_user(1001, 2002) is True
    assert database.list_vip_voice_room_whitelist(1001) == []


def test_deleting_vip_room_clears_whitelist(monkeypatch, tmp_path):
    _configure_temp_database(monkeypatch, tmp_path)

    database.upsert_vip_voice_room(
        owner_id=1001,
        channel_id=3003,
        panel_message_id=4004,
    )
    database.add_vip_voice_room_whitelist_user(
        1001,
        2002,
        added_by=1001,
    )

    database.delete_vip_voice_room_record(
        owner_id=1001,
        channel_id=3003,
    )

    assert database.get_vip_voice_room_by_owner(1001) is None
    assert database.list_vip_voice_room_whitelist(1001) == []


def test_vip_whitelist_overwrite_is_minimal():
    overwrite = build_vip_whitelist_overwrite()

    assert overwrite.view_channel is True
    assert overwrite.connect is True
    assert overwrite.speak is True
    assert overwrite.use_voice_activation is True
    assert overwrite.send_messages is True
    assert overwrite.read_message_history is True

    assert overwrite.stream is False
    assert overwrite.attach_files is False
    assert overwrite.add_reactions is False
    assert overwrite.use_external_emojis is False
    assert overwrite.use_external_stickers is False
    assert overwrite.move_members is False
    assert overwrite.manage_channels is False
    assert overwrite.manage_messages is False
