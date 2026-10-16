from pathlib import Path

from services.acceptance import runtime, ticket_access


def test_acceptance_ticket_access_is_physically_extracted_and_reexported():
    runtime_source = Path("services/acceptance/runtime.py").read_text(encoding="utf-8")
    ticket_source = Path("services/acceptance/ticket_access.py").read_text(
        encoding="utf-8"
    )

    function_names = (
        "_ticket_overwrite_has_values",
        "grant_order_ticket_access",
        "revoke_order_ticket_access",
        "sync_acceptance_ticket_access_from_state",
    )

    for name in function_names:
        definition = (
            f"def {name}" if name == "_ticket_overwrite_has_values" else f"async def {name}"
        )
        assert definition not in runtime_source
        assert definition in ticket_source
        assert getattr(runtime, name) is getattr(ticket_access, name)


def test_ticket_access_grant_and_revoke_keep_the_same_permission_scope():
    source = Path("services/acceptance/ticket_access.py").read_text(encoding="utf-8")

    for permission_name in (
        "view_channel",
        "send_messages",
        "read_message_history",
        "attach_files",
        "embed_links",
    ):
        assert f"overwrite.{permission_name} = True" in source
        assert f"overwrite.{permission_name} = None" in source

    assert 'reason="Grant accepted staff ticket access"' in source
    assert 'reason="Revoke unclaimed staff ticket access"' in source


def test_ticket_access_has_stable_direct_dependencies_only():
    source = Path("services/acceptance/ticket_access.py").read_text(encoding="utf-8")

    assert "from services.orders import _to_int" in source
    assert "import bot" not in source
    assert "from bot import" not in source
    assert "globals()" not in source
