#!/usr/bin/env python3
"""Explicit, one-time update of the approved Discord customer-service lobby.

The bot startup intentionally stays read-only. By default this tool ONLY
previews the edit; --apply is required to PATCH the existing bot-owned message.
Never post another panel, modify unrelated messages, or touch order/database
state.
"""
from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timezone
import json
import os
from pathlib import Path

import aiohttp
from dotenv import load_dotenv

# Running "python scripts/..." puts scripts/ first on sys.path.
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from views.panels import MainPanelView, build_main_panel_embed  # noqa: E402


DEFAULT_GUILD_ID = 1129474191226306672
DEFAULT_CHANNEL_ID = 1497622678138519572
DEFAULT_MESSAGE_ID = 1537533276884045856
API = "https://discord.com/api/v10"

EXPECTED_BUTTON_IDS = (
    "mawan_main_panel_support_call_v1",
    "mawan_main_panel_recruit_button",
    "mawan_main_panel_complaint_button",
    "mawan_main_panel_feedback_button",
)


def _settings() -> dict:
    config_path = ROOT / "config.json"
    if not config_path.is_file():
        return {}
    with config_path.open(encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise RuntimeError("config.json must be an object")
    return value


def _configured_id(settings: dict, key: str, default: int) -> int:
    return int(settings.get(key) or default)


def _button_pairs(components: list[dict]) -> list[tuple[str, str]]:
    return [
        (str(button.get("custom_id") or ""), str(button.get("label") or ""))
        for row in components
        for button in row.get("components", [])
        if button.get("type") == 2
    ]



def _components_match(actual: list[dict], expected: list[dict]) -> bool:
    """Compare semantic Discord controls, ignoring API-added component IDs."""
    if len(actual) != len(expected):
        return False
    for actual_row, expected_row in zip(actual, expected):
        if actual_row.get("type") != expected_row.get("type"):
            return False
        existing = actual_row.get("components") or []
        proposed = expected_row.get("components") or []
        if len(existing) != len(proposed):
            return False
        for old, new in zip(existing, proposed):
            for key in ("type", "style", "label", "custom_id", "emoji"):
                if old.get(key) != new.get(key):
                    return False
            if bool(old.get("disabled")) != bool(new.get("disabled")):
                return False
    return True


def _existing_button_styles_match(
    existing: list[dict], expected: list[dict]
) -> bool:
    """Existing buttons may have old emojis, but nothing else may drift."""
    if len(existing) != len(expected):
        return False
    for existing_row, expected_row in zip(existing, expected):
        old_buttons = existing_row.get("components") or []
        new_buttons = expected_row.get("components") or []
        if len(old_buttons) != len(new_buttons):
            return False
        for old, new in zip(old_buttons, new_buttons):
            for key in ("type", "style", "label", "custom_id"):
                if old.get(key) != new.get(key):
                    return False
    return True

def _price_list_id(*, specified: int | None) -> int:
    """Use the exact Discord channel/thread URL supplied by the owner.

    /guilds/{guild_id}/channels omits thread channels and some entry types,
    so absence from that listing is NOT evidence the provided link is invalid.
    Keep this one-time updater locked to the approved destination.
    """
    from views.panels import SERVICE_LOBBY_PRICE_LIST_CHANNEL_ID

    approved = SERVICE_LOBBY_PRICE_LIST_CHANNEL_ID
    if specified is not None and specified != approved:
        raise RuntimeError(
            f"指定的價目表頻道 {specified} 與店主核准的 {approved} 不符；"
            "停止更新以避免改錯連結"
        )
    return approved


async def _api_call(
    client: aiohttp.ClientSession, method: str, path: str, **kwargs
) -> dict | list:
    async with client.request(method, f"{API}{path}", **kwargs) as response:
        try:
            data = await response.json(content_type=None)
        except Exception as exc:
            raise RuntimeError(
                f"Discord API {method} {path}: invalid JSON ({response.status})"
            ) from exc
        if response.status >= 400:
            reason = data.get("message", "") if isinstance(data, dict) else ""
            raise RuntimeError(
                f"Discord API {method} {path} HTTP {response.status}: {reason}"
            )
        return data


def _write_backup(message: dict, message_id: int) -> Path:
    archive = ROOT / "_archive" / "service_panel_manual_updates"
    archive.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f_utc")
    destination = archive / f"service_panel_{message_id}_{now}.json"
    fd = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        json.dump(message, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    return destination


async def _main(args: argparse.Namespace) -> None:
    load_dotenv(ROOT / ".env")
    token = os.getenv("DISCORD_TOKEN")
    if not token:
        raise RuntimeError("Missing DISCORD_TOKEN in the project .env")

    settings = _settings()
    guild_id = _configured_id(settings, "GUILD_ID", DEFAULT_GUILD_ID)
    channel_id = _configured_id(
        settings, "DISPATCH_SUPPORT_ONLINE_CHANNEL_ID", DEFAULT_CHANNEL_ID
    )
    message_id = _configured_id(
        settings, "MAIN_SERVICE_PANEL_MESSAGE_ID", DEFAULT_MESSAGE_ID
    )
    if not all((guild_id, channel_id, message_id)):
        raise RuntimeError("Panel guild/channel/message IDs must be nonzero")
    if guild_id != DEFAULT_GUILD_ID:
        raise RuntimeError(
            f"Configured guild {guild_id} does not match the owner-approved "
            f"Discord link's guild {DEFAULT_GUILD_ID}"
        )

    view = MainPanelView()
    components = view.to_components()
    target_buttons = _button_pairs(components)
    if tuple(button_id for button_id, _ in target_buttons) != EXPECTED_BUTTON_IDS:
        raise RuntimeError("Canonical lobby button IDs changed; manual review required")
    if any(
        button.get("emoji")
        for row in components
        for button in row.get("components", [])
    ):
        raise RuntimeError("Canonical lobby buttons unexpectedly contain emojis")

    timeout = aiohttp.ClientTimeout(total=25)
    async with aiohttp.ClientSession(
        headers={"Authorization": f"Bot {token}"},
        timeout=timeout,
    ) as client:
        me = await _api_call(client, "GET", "/users/@me")
        current = await _api_call(
            client, "GET", f"/channels/{channel_id}/messages/{message_id}"
        )
        if str(current.get("author", {}).get("id")) != str(me["id"]):
            raise RuntimeError("Existing panel is not authored by this bot; abort")
        if str(current.get("channel_id")) != str(channel_id):
            raise RuntimeError("Existing panel has unexpected channel ID; abort")

        embeds = current.get("embeds") or []
        if len(embeds) != 1:
            raise RuntimeError("Existing panel has multiple/no embeds; abort")
        title = str(embeds[0].get("title") or "")
        if title != "魔丸娛樂｜聯絡客服":
            raise RuntimeError(f"Existing panel title differs ({title!r}); abort")

        current_buttons = _button_pairs(current.get("components") or [])
        if current_buttons != target_buttons:
            raise RuntimeError(
                "Existing panel button IDs or labels differ from the protected "
                "four-button layout; leave owner-approved content untouched"
            )
        if not _existing_button_styles_match(current.get("components") or [], components):
            raise RuntimeError("Existing panel button styling/layout differs; abort")

        # Exact approved Discord URL already pins the destination. Do not
        # enumerate guild channels: a valid forum thread is absent there.
        price_id = _price_list_id(specified=args.price_list_channel_id)
        embed = build_main_panel_embed(price_list_channel_id=price_id)
        if len(embed.description or "") > 4096:
            raise RuntimeError("Embed description exceeds Discord size limit")

        desired = {"embeds": [embed.to_dict()], "components": components}
        already_matches = (
            embeds[0].get("description") == embed.description
            and embeds[0].get("title") == embed.title
            and _components_match(current.get("components") or [], components)
        )

        print(f"Target: channel={channel_id} message={message_id}")
        print(f"Price list: <#{price_id}>")
        print("Planned embed:")
        print(embed.title)
        print(embed.description)
        print("Buttons: " + ", ".join(label for _, label in target_buttons))

        if already_matches:
            print("SKIP: panel already matches the approved copy")
            return
        if not args.apply:
            print("DRY RUN ONLY. To edit this one existing message, add --apply.")
            return

        backup = _write_backup(current, message_id)
        print(f"Backup saved: {backup}")
        await _api_call(
            client,
            "PATCH",
            f"/channels/{channel_id}/messages/{message_id}",
            json=desired,
        )
        confirmed = await _api_call(
            client, "GET", f"/channels/{channel_id}/messages/{message_id}"
        )
        actual_embed = (confirmed.get("embeds") or [{}])[0]
        if (
            actual_embed.get("description") != embed.description
            or not _components_match(confirmed.get("components") or [], components)
        ):
            raise RuntimeError(
                f"POST-VERIFY FAILED. Original message backup: {backup}"
            )
        print("PASS: updated the original service panel and verified buttons.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply", action="store_true", help="Actually update existing panel"
    )
    parser.add_argument(
        "--price-list-channel-id", type=int,
        help="Optional exact ID; must match the owner-approved Discord URL",
    )
    asyncio.run(_main(parser.parse_args()))
