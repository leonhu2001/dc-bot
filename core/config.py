from __future__ import annotations

import json
from pathlib import Path
from typing import Any


CONFIG_FILE = Path(__file__).resolve().parent.parent / "config.json"


def load_external_config(config_file: Path = CONFIG_FILE) -> dict[str, Any]:
    """讀取專案根目錄的 config.json。

    沒有 config.json 或格式錯誤時會回傳空 dict，讓 bot.py 使用內建預設值繼續啟動。
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

    return data


BOT_CONFIG = load_external_config()


def config_value(key: str, default: Any) -> Any:
    return BOT_CONFIG.get(key, default)


def config_int(key: str, default: int) -> int:
    value = config_value(key, default)
    try:
        return int(value)
    except (TypeError, ValueError):
        print(f"config.json 的 {key} 不是有效整數，已使用預設值：{default}")
        return int(default)


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
