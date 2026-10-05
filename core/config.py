from __future__ import annotations

import json
from pathlib import Path
from typing import Any


CONFIG_FILE = Path(__file__).resolve().parent.parent / "config.json"

# 仍由 bot.py 呼叫 config_* 載入設定，但這類已搬動過的營運頻道 ID
# 在這裡提供單一 canonical default，避免舊 bot.py fallback 重新生效。
#
# DISPATCH_ONLINE_CHANNEL_ID 是歷史相容鍵；目前代表「女陪在線」頻道。
# 男陪在線頻道由 views.dispatch_presence 讀取 DISPATCH_MALE_ONLINE_CHANNEL_ID。
CANONICAL_INT_DEFAULTS = {
    "DISPATCH_ONLINE_CHANNEL_ID": 1538270157057691660,
    "DISPATCH_MALE_ONLINE_CHANNEL_ID": 1538270089785245856,
}

# 已部署過的舊值在讀取 config.json 時做一次真正的設定遷移並寫回檔案，
# 而不是每次 runtime 再蓋掉舊值。
INT_VALUE_MIGRATIONS = {
    "DISPATCH_ONLINE_CHANNEL_ID": {
        1556366139830042634: 1538270157057691660,
        1556381428235902996: 1538270157057691660,
    },
}


def _migrate_external_config_values(
    data: dict[str, Any],
    *,
    config_file: Path,
) -> dict[str, Any]:
    changed = False
    migrated = dict(data)

    for key, migrations in INT_VALUE_MIGRATIONS.items():
        raw_value = migrated.get(key)
        try:
            parsed_value = int(raw_value)
        except (TypeError, ValueError):
            continue

        replacement = migrations.get(parsed_value)
        if replacement is None:
            continue

        migrated[key] = replacement
        changed = True
        print(
            f"config.json 已遷移 {key}: {parsed_value} -> {replacement}"
        )

    if changed:
        try:
            config_file.write_text(
                json.dumps(
                    migrated,
                    ensure_ascii=False,
                    indent=2,
                ) + "\n",
                encoding="utf-8",
            )
        except OSError as e:
            print(
                "config.json 設定已在本次執行套用，但寫回遷移結果失敗："
                f"{e}"
            )

    return migrated


def load_external_config(config_file: Path = CONFIG_FILE) -> dict[str, Any]:
    """讀取專案根目錄的 config.json。

    沒有 config.json 或格式錯誤時會回傳空 dict，讓 config_* 使用
    canonical default / bot.py 既有預設值繼續啟動。
    """
    if not config_file.exists():
        return {}

    try:
        with config_file.open("r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        print(f"讀取 config.json 失敗，已使用程式內建預設值：{e}")
        return {}

    if not isinstance(data, dict):
        print("config.json 格式錯誤，最外層必須是 JSON object，已使用程式內建預設值。")
        return {}

    return _migrate_external_config_values(
        data,
        config_file=config_file,
    )


BOT_CONFIG = load_external_config()


def config_value(key: str, default: Any) -> Any:
    return BOT_CONFIG.get(key, default)


def config_int(key: str, default: int) -> int:
    effective_default = int(CANONICAL_INT_DEFAULTS.get(key, default))
    value = config_value(key, effective_default)
    try:
        return int(value)
    except (TypeError, ValueError):
        print(
            f"config.json 的 {key} 不是有效整數，"
            f"已使用預設值：{effective_default}"
        )
        return effective_default


def config_int_list(key: str, default: list[int]) -> list[int]:
    value = config_value(key, default)

    if not isinstance(value, list):
        print(f"config.json 的 {key} 必須是陣列，已使用預設值。")
        return list(default)

    result: list[int] = []
    for item in value:
        try:
            result.append(int(item))
        except (TypeError, ValueError):
            print(f"config.json 的 {key} 內含無效 ID：{item}，已略過。")

    return result if result else list(default)


def config_str(key: str, default: str) -> str:
    value = config_value(key, default)
    if value is None:
        return default
    return str(value)


def config_str_list(key: str, default: list[str]) -> list[str]:
    value = config_value(key, default)
    if not isinstance(value, list):
        print(f"config.json 的 {key} 必須是字串陣列，已使用預設值。")
        return list(default)
    return [str(item) for item in value]


# bot.py 目前仍使用舊的私有函式名稱；先保留相容別名，避免大改動。
_config_value = config_value
_config_int = config_int
_config_int_list = config_int_list
_config_str = config_str
_config_str_list = config_str_list
_load_external_config = load_external_config
