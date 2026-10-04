import json

from core.config import (
    _migrate_external_config_values,
    config_int,
)


def test_dispatch_presence_channel_uses_canonical_default():
    assert config_int(
        "DISPATCH_ONLINE_CHANNEL_ID",
        1556366139830042634,
    ) == 1556381428235902996


def test_dispatch_presence_channel_migrates_old_runtime_config(tmp_path):
    config_file = tmp_path / "config.json"
    config_file.write_text(
        json.dumps(
            {
                "DISPATCH_ONLINE_CHANNEL_ID": 1556366139830042634,
                "GUILD_ID": 123,
            }
        ),
        encoding="utf-8",
    )

    migrated = _migrate_external_config_values(
        {
            "DISPATCH_ONLINE_CHANNEL_ID": 1556366139830042634,
            "GUILD_ID": 123,
        },
        config_file=config_file,
    )

    assert migrated["DISPATCH_ONLINE_CHANNEL_ID"] == 1556381428235902996

    persisted = json.loads(config_file.read_text(encoding="utf-8"))
    assert persisted["DISPATCH_ONLINE_CHANNEL_ID"] == 1556381428235902996
    assert persisted["GUILD_ID"] == 123
