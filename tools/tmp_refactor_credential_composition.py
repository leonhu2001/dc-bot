from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    target = Path(path)
    text = target.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"expected exactly one match in {path}, found {count}")
    target.write_text(text.replace(old, new, 1), encoding="utf-8")


# Add a thin credential composition boundary whose service-owned dependencies are
# imported directly, leaving only true bot-owned state at the composition root.
Path("services/order_credential_composition.py").write_text(
    '''from __future__ import annotations

from core.database import remember_order_data, save_bot_data
from core.time_utils import get_taipei_now_iso
from services.order_credential_runtime import configure_order_credentials
from services.orders import _to_int
from services.rewards import fetch_member_safely


def configure_order_credential_composition(
    credential_owner_user_id,
    guild_id,
    order_selections,
    bot_instance,
) -> None:
    """Wire credential runtime using bot-owned state only."""
    configure_order_credentials(
        credential_owner_user_id=credential_owner_user_id,
        guild_id=guild_id,
        self_service_order_selections=order_selections,
        to_int=_to_int,
        bot_instance=bot_instance,
        fetch_member=fetch_member_safely,
        taipei_now_iso=get_taipei_now_iso,
        remember_data=remember_order_data,
        save_data=save_bot_data,
    )
''',
    encoding="utf-8",
)

replace_once(
    "services/order_child_composition.py",
    "from services.order_dispatch_composition import configure_order_dispatch_composition\n",
    "from services.order_credential_composition import configure_order_credential_composition\n"
    "from services.order_dispatch_composition import configure_order_dispatch_composition\n",
)
replace_once(
    "services/order_child_composition.py",
    '''def configure_order_children(
    booster_receiver_role_id,
    dispatch_channel_id,
    order_claims,
    order_selections,
    customer_rewards,
) -> None:
''',
    '''def configure_order_children(
    booster_receiver_role_id,
    dispatch_channel_id,
    order_claims,
    order_selections,
    customer_rewards,
    credential_owner_user_id,
    guild_id,
    bot_instance,
) -> None:
''',
)
replace_once(
    "services/order_child_composition.py",
    '''    configure_order_point_redemption(
        customer_rewards=customer_rewards,
        to_int=_to_int,
        current_reward_points=get_current_reward_points,
        customer_reward_data=get_customer_reward_data,
        order_point_item=get_order_point_item,
        taipei_now_iso=get_taipei_now_iso,
        remember_data=remember_order_data,
        save_data=save_bot_data,
        order_log_sender=send_order_log,
    )
''',
    '''    configure_order_point_redemption(
        customer_rewards=customer_rewards,
        to_int=_to_int,
        current_reward_points=get_current_reward_points,
        customer_reward_data=get_customer_reward_data,
        order_point_item=get_order_point_item,
        taipei_now_iso=get_taipei_now_iso,
        remember_data=remember_order_data,
        save_data=save_bot_data,
        order_log_sender=send_order_log,
    )
    configure_order_credential_composition(
        credential_owner_user_id,
        guild_id,
        order_selections,
        bot_instance,
    )
''',
)

replace_once(
    "services/order_runtime.py",
    "    configure_order_credentials,\n",
    "",
)
replace_once(
    "services/order_runtime.py",
    '''    credential_keys = {
        "CREDENTIAL_OWNER_USER_ID",
        "GUILD_ID",
        "SELF_SERVICE_ORDER_SELECTIONS",
        "_to_int",
        "bot",
        "fetch_member_safely",
        "get_taipei_now_iso",
        "remember_order_data",
        "save_bot_data",
    }
    if credential_keys.issubset(namespace):
        configure_order_credentials(
            credential_owner_user_id=namespace["CREDENTIAL_OWNER_USER_ID"],
            guild_id=namespace["GUILD_ID"],
            self_service_order_selections=namespace["SELF_SERVICE_ORDER_SELECTIONS"],
            to_int=namespace["_to_int"],
            bot_instance=namespace["bot"],
            fetch_member=namespace["fetch_member_safely"],
            taipei_now_iso=namespace["get_taipei_now_iso"],
            remember_data=namespace["remember_order_data"],
            save_data=namespace["save_bot_data"],
        )

''',
    "",
)

replace_once(
    "bot.py",
    '''configure_order_children(
    BOOSTER_RECEIVER_ROLE_ID, DISPATCH_CHANNEL_ID, ORDER_CLAIMS, SELF_SERVICE_ORDER_SELECTIONS,
    CUSTOMER_REWARDS,
)
''',
    '''configure_order_children(BOOSTER_RECEIVER_ROLE_ID, DISPATCH_CHANNEL_ID, ORDER_CLAIMS, SELF_SERVICE_ORDER_SELECTIONS, CUSTOMER_REWARDS, CREDENTIAL_OWNER_USER_ID, GUILD_ID, bot)
''',
)

Path("tests/test_order_child_composition.py").write_text(
    '''from pathlib import Path

from services import order_child_composition as composition


ROOT = Path(__file__).resolve().parents[1]
ORDER_RUNTIME_SOURCE = (ROOT / "services" / "order_runtime.py").read_text(encoding="utf-8")
BOT_SOURCE = (ROOT / "bot.py").read_text(encoding="utf-8")


def test_order_child_composition_wires_extracted_children(monkeypatch):
    dispatch_calls = []
    credential_calls = []
    point_kwargs = {}
    sentinels = {
        "to_int": object(),
        "current_reward_points": object(),
        "customer_reward_data": object(),
        "order_point_item": object(),
        "taipei_now_iso": object(),
        "remember_data": object(),
        "save_data": object(),
        "order_log_sender": object(),
    }
    monkeypatch.setattr(
        composition,
        "configure_order_dispatch_composition",
        lambda *args: dispatch_calls.append(args),
    )
    monkeypatch.setattr(
        composition,
        "configure_order_point_redemption",
        lambda **kwargs: point_kwargs.update(kwargs),
    )
    monkeypatch.setattr(
        composition,
        "configure_order_credential_composition",
        lambda *args: credential_calls.append(args),
    )
    monkeypatch.setattr(composition, "_to_int", sentinels["to_int"])
    monkeypatch.setattr(composition, "get_current_reward_points", sentinels["current_reward_points"])
    monkeypatch.setattr(composition, "get_customer_reward_data", sentinels["customer_reward_data"])
    monkeypatch.setattr(composition, "get_order_point_item", sentinels["order_point_item"])
    monkeypatch.setattr(composition, "get_taipei_now_iso", sentinels["taipei_now_iso"])
    monkeypatch.setattr(composition, "remember_order_data", sentinels["remember_data"])
    monkeypatch.setattr(composition, "save_bot_data", sentinels["save_data"])
    monkeypatch.setattr(composition, "send_order_log", sentinels["order_log_sender"])

    claims = {}
    selections = {}
    rewards = {}
    bot_instance = object()
    composition.configure_order_children(
        11, 22, claims, selections, rewards, 33, 44, bot_instance
    )

    assert dispatch_calls == [(11, 22, claims, selections)]
    assert point_kwargs == {"customer_rewards": rewards, **sentinels}
    assert credential_calls == [(33, 44, selections, bot_instance)]


def test_extracted_child_composition_is_outside_legacy_order_runtime():
    assert "configure_order_point_redemption" not in ORDER_RUNTIME_SOURCE
    assert "redemption_keys" not in ORDER_RUNTIME_SOURCE
    assert "configure_order_credentials(" not in ORDER_RUNTIME_SOURCE
    assert "credential_keys =" not in ORDER_RUNTIME_SOURCE
    assert "configure_order_children" in BOT_SOURCE
    assert "CUSTOMER_REWARDS" in BOT_SOURCE
    assert "CREDENTIAL_OWNER_USER_ID" in BOT_SOURCE
''',
    encoding="utf-8",
)

Path("tests/test_order_credential_composition.py").write_text(
    '''from services import order_credential_composition as composition


def test_order_credential_composition_maps_dependencies(monkeypatch):
    captured = {}
    sentinels = {
        "to_int": object(),
        "fetch_member": object(),
        "taipei_now_iso": object(),
        "remember_data": object(),
        "save_data": object(),
    }
    monkeypatch.setattr(
        composition,
        "configure_order_credentials",
        lambda **kwargs: captured.update(kwargs),
    )
    monkeypatch.setattr(composition, "_to_int", sentinels["to_int"])
    monkeypatch.setattr(composition, "fetch_member_safely", sentinels["fetch_member"])
    monkeypatch.setattr(composition, "get_taipei_now_iso", sentinels["taipei_now_iso"])
    monkeypatch.setattr(composition, "remember_order_data", sentinels["remember_data"])
    monkeypatch.setattr(composition, "save_bot_data", sentinels["save_data"])

    selections = {}
    bot_instance = object()
    composition.configure_order_credential_composition(11, 22, selections, bot_instance)

    assert captured == {
        "credential_owner_user_id": 11,
        "guild_id": 22,
        "self_service_order_selections": selections,
        "to_int": sentinels["to_int"],
        "bot_instance": bot_instance,
        "fetch_member": sentinels["fetch_member"],
        "taipei_now_iso": sentinels["taipei_now_iso"],
        "remember_data": sentinels["remember_data"],
        "save_data": sentinels["save_data"],
    }
''',
    encoding="utf-8",
)

replace_once(
    "tests/test_runtime_extraction_boundaries.py",
    "    order_credential_runtime,\n",
    "    order_credential_composition,\n    order_credential_runtime,\n",
)
replace_once(
    "tests/test_runtime_extraction_boundaries.py",
    "    assert callable(order_credential_runtime.configure_order_credentials)\n",
    "    assert callable(order_credential_composition.configure_order_credential_composition)\n"
    "    assert callable(order_credential_runtime.configure_order_credentials)\n",
)
replace_once(
    "tests/test_runtime_extraction_boundaries.py",
    '''    assert "class OrderCredentialModal" not in order_source
    assert "async def redeem_order_point_benefit_on_payment" not in order_source
''',
    '''    assert "class OrderCredentialModal" not in order_source
    assert "credential_keys =" not in order_source
    assert "configure_order_credentials(" not in order_source
    assert "async def redeem_order_point_benefit_on_payment" not in order_source
''',
)

# Guard the architecture ceiling locally before CI.
bot_size = Path("bot.py").stat().st_size
if bot_size > 235000:
    raise RuntimeError(f"bot.py growth budget exceeded: {bot_size} > 235000")

print(f"credential composition patch applied; bot.py={bot_size} bytes")
