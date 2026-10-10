from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def patch(path, old, new, count=1):
    target = ROOT / path
    text = target.read_text(encoding="utf-8")
    found = text.count(old)
    if found != count:
        raise RuntimeError(f"{path}: expected {count}, found {found}: {old[:120]!r}")
    target.write_text(text.replace(old, new, count), encoding="utf-8")


# Old 5+1 regression must now assert no same-order free service.
patch(
    "tests/test_game_service_rules.py",
    '''def test_buy_8_get_1_and_prices():
    rule = ORDER_RULES["valorant_radiant_ranked"]
    result = calculate_price(rule, quantity=8, player_count=2)
    assert rule.price == 400
    assert result.base_amount == 6400
    assert result.service_quantity == 9
    assert set(get_allowed_role_ids(rule)) == {"1545357782906314782"}

    lol = ORDER_RULES["lol_entertain_aram"]
    assert lol.price == 300
    assert lol.unit_label == "H"
    assert calculate_price(lol, quantity=8, player_count=1).service_quantity == 9
''',
    '''def test_same_order_buy_get_is_removed_and_prices_unchanged():
    rule = ORDER_RULES["valorant_radiant_ranked"]
    result = calculate_price(rule, quantity=8, player_count=2)
    assert rule.price == 400
    assert result.base_amount == 6400
    assert result.service_quantity == 8
    assert set(get_allowed_role_ids(rule)) == {"1545357782906314782"}

    lol = ORDER_RULES["lol_entertain_aram"]
    assert lol.price == 300
    assert lol.unit_label == "H"
    assert calculate_price(lol, quantity=8, player_count=1).service_quantity == 8
''',
)

# Initialize loyalty schema explicitly on the web process startup.
patch(
    "web/app/main.py",
    "from services.wallet_service import ensure_wallet_tables\n",
    "from services.wallet_service import ensure_wallet_tables\nfrom services.loyalty_benefits import ensure_loyalty_tables\n",
)
patch(
    "web/app/main.py",
    "    ensure_wallet_tables()\n    ensure_ticket_archive_tables()\n",
    "    ensure_wallet_tables()\n    ensure_loyalty_tables()\n    ensure_ticket_archive_tables()\n",
)

# The monolithic bot does not load extension cogs dynamically. Register the
# persistent member portal directly before bot.run, without replacing on_ready.
patch(
    "bot.py",
    '''configure_acceptance_runtime(globals())
configure_web_sync_runtime(globals())
configure_order_runtime(globals())
configure_self_service_runtime(globals())

bot.run(TOKEN)
''',
    '''configure_acceptance_runtime(globals())
configure_web_sync_runtime(globals())
configure_order_runtime(globals())
configure_self_service_runtime(globals())

# Customer-facing member portal in channel 1558395213406412801.
# Register as a persistent view and use an on_ready listener so reconnects
# refresh the existing panel instead of posting duplicates.
from cogs.member_portal import MemberPortalView, ensure_member_portal_panel
from services.loyalty_benefits import ensure_loyalty_tables

ensure_loyalty_tables()
bot.add_view(MemberPortalView())

@bot.listen("on_ready")
async def _refresh_member_portal_panel_on_ready():
    await ensure_member_portal_panel(bot)

bot.run(TOKEN)
''',
)

# Keep the cog module as a passive helper; bot.py owns actual registration.
portal = ROOT / "cogs/member_portal.py"
text = portal.read_text(encoding="utf-8")
text = text.replace(
    '''class MemberPortalCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.bot.add_view(MemberPortalView())
        self.bot.loop.create_task(ensure_member_portal_panel(bot))


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(MemberPortalCog(bot))
''',
    '''# Registration is intentionally owned by bot.py because this project does not
# dynamically load extension cogs. Keeping the panel helpers here avoids adding
# another second startup path.
''',
)
portal.write_text(text, encoding="utf-8")

print("final loyalty corrections applied")
