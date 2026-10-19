from __future__ import annotations

from pathlib import Path


BOT_PATH = Path("bot.py")


def replace_between(source: str, start: str, end: str, replacement: str) -> str:
    start_index = source.find(start)
    if start_index < 0:
        raise RuntimeError(f"start marker not found: {start!r}")
    end_index = source.find(end, start_index)
    if end_index < 0:
        raise RuntimeError(f"end marker not found: {end!r}")
    return source[:start_index] + replacement + source[end_index:]


def main() -> None:
    source = BOT_PATH.read_text(encoding="utf-8")

    wallet_import = "    get_wallet_transactions as _wallet_get_transactions,\n"
    if source.count(wallet_import) != 1:
        raise RuntimeError("unexpected wallet transaction import count")
    source = source.replace(wallet_import, "", 1)

    source = replace_between(
        source,
        "def build_customer_info_with_wallet_embed(\n",
        "class StaffOrderOperationSelect(discord.ui.Select):\n",
        "# 錢包資訊 / 流水 Embed 已搬到 cogs/wallet_commands.py\n\n\n",
    )

    source = replace_between(
        source,
        "@bot.tree.command(\n    name=\"wallet_add\",\n",
        "# 營運統計 / VIP 降階查詢 slash 指令已搬到 cogs/stats_commands.py\n",
        (
            "# 錢包 slash 指令已搬到 cogs/wallet_commands.py\n\n\n"
            "# 營運統計 / VIP 降階查詢 slash 指令已搬到 cogs/stats_commands.py\n"
        ),
    )

    extension_anchor = '                "cogs.customer_commands",\n'
    wallet_extension = '                "cogs.wallet_commands",\n'
    if source.count(extension_anchor) != 1:
        raise RuntimeError("unexpected customer extension anchor count")
    if wallet_extension not in source:
        source = source.replace(
            extension_anchor,
            extension_anchor + wallet_extension,
            1,
        )

    forbidden = [
        'name="wallet_add"',
        'name="wallet_adjust"',
        'name="wallet_refund"',
        'name="wallet_history"',
        'name="my_wallet_history"',
        'name="wallet_refund_order"',
        'name="my_info"',
        "def build_customer_info_with_wallet_embed(",
        "def build_wallet_history_embed(",
        "def wallet_transaction_type_label(",
        "get_wallet_transactions as _wallet_get_transactions",
    ]
    leftovers = [item for item in forbidden if item in source]
    if leftovers:
        raise RuntimeError(f"bot.py wallet leftovers: {leftovers}")

    if wallet_extension not in source:
        raise RuntimeError("wallet command extension was not registered")

    BOT_PATH.write_text(source, encoding="utf-8")


if __name__ == "__main__":
    main()
