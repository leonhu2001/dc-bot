from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if text.count(old) != 1:
        raise SystemExit(f"{label}: expected exactly one match, got {text.count(old)}")
    return text.replace(old, new, 1)


bot_path = Path("bot.py")
bot = bot_path.read_text(encoding="utf-8")
bot = replace_once(bot, "load_dotenv()\nimport os\nimport json", "load_dotenv()\nimport json", "duplicate os import")
bot = replace_once(bot, "\nimport discord\n\nfrom services.ticket_identity import", "\nfrom services.ticket_identity import", "duplicate discord import")
bot = replace_once(bot, "from discord import app_commands\nfrom dotenv import load_dotenv\n", "from discord import app_commands\n", "duplicate dotenv import")
bot = replace_once(
    bot,
    "from services.review_persistent_runtime import restore_persistent_review_views\n",
    "from services.order_dispatch_composition import configure_order_dispatch_composition\nfrom services.review_persistent_runtime import restore_persistent_review_views\n",
    "dispatch composition import",
)
bot = replace_once(
    bot,
    "configure_web_sync_runtime(globals())\nconfigure_order_runtime(globals())",
    "configure_web_sync_runtime(globals())\nconfigure_order_dispatch_composition(\n    BOOSTER_RECEIVER_ROLE_ID, DISPATCH_CHANNEL_ID, ORDER_CLAIMS, SELF_SERVICE_ORDER_SELECTIONS\n)\nconfigure_order_runtime(globals())",
    "dispatch composition startup",
)
bot_path.write_text(bot, encoding="utf-8")

runtime_path = Path("services/order_runtime.py")
runtime = runtime_path.read_text(encoding="utf-8")
runtime = replace_once(runtime, "    configure_order_dispatch_runtime,\n    configure_order_dispatch_runtime_explicit,\n", "", "legacy dispatch configurator imports")
start = runtime.index("    dispatch_keys = {")
end = runtime.index("    credential_keys = {", start)
runtime = runtime[:start] + runtime[end:]
runtime_path.write_text(runtime, encoding="utf-8")

boundary_path = Path("tests/test_order_runtime_dependency_boundary.py")
boundary = boundary_path.read_text(encoding="utf-8")
start = boundary.index("def _dispatch_namespace()")
end = boundary.index("def test_order_runtime_namespace_binding_is_explicitly_scoped", start)
boundary = boundary[:start] + boundary[end:]
boundary = boundary.replace("            **_dispatch_namespace(),\n", "", 1)
boundary_path.write_text(boundary, encoding="utf-8")

extraction_path = Path("tests/test_runtime_extraction_boundaries.py")
extraction = extraction_path.read_text(encoding="utf-8")
extraction = replace_once(
    extraction,
    "    order_credential_runtime,\n",
    "    order_credential_runtime,\n    order_dispatch_composition,\n",
    "composition test import",
)
extraction = replace_once(
    extraction,
    "    assert callable(order_runtime.configure_order_runtime)\n",
    "    assert callable(order_runtime.configure_order_runtime)\n    assert callable(order_dispatch_composition.configure_order_dispatch_composition)\n",
    "composition callable assertion",
)
extraction = replace_once(
    extraction,
    "    web_bind = bot_source.index(\"configure_web_sync_runtime(globals())\")\n    order_bind = bot_source.index(\"configure_order_runtime(globals())\")",
    "    web_bind = bot_source.index(\"configure_web_sync_runtime(globals())\")\n    dispatch_bind = bot_source.index(\"configure_order_dispatch_composition(\")\n    order_bind = bot_source.index(\"configure_order_runtime(globals())\")",
    "dispatch startup index",
)
extraction = replace_once(
    extraction,
    "    assert web_bind < bot_run\n    assert order_bind < bot_run",
    "    assert web_bind < dispatch_bind < order_bind < bot_run\n    assert order_bind < bot_run",
    "dispatch startup order assertion",
)
start = extraction.index("def _order_dispatch_namespace()")
end = extraction.index("def test_runtime_configure_boundaries_match_current_migration_stage", start)
extraction = extraction[:start] + extraction[end:]
extraction = extraction.replace("            **_order_dispatch_namespace(),\n", "", 1)
extraction = replace_once(
    extraction,
    "    assert \"def configure_order_dispatch_runtime\" in dispatch_source\n",
    "    assert \"def configure_order_dispatch_runtime\" in dispatch_source\n    assert \"dispatch_keys =\" not in order_source\n    assert \"configure_order_dispatch_runtime_explicit(\" not in order_source\n",
    "legacy dispatch composition absence assertions",
)
extraction_path.write_text(extraction, encoding="utf-8")

print("bot.py bytes:", bot_path.stat().st_size)
print("order_runtime.py bytes:", runtime_path.stat().st_size)
# retrigger validation after dependency fix
