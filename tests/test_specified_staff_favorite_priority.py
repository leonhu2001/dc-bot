from services import self_service_selection_runtime as selection_runtime


def _entries():
    return [
        {"id": "100", "label": "Alpha", "description": "Role A", "role_order": 0},
        {"id": "200", "label": "Beta", "description": "Role B", "role_order": 1},
        {"id": "300", "label": "Gamma", "description": "Role A", "role_order": 0},
    ]


def test_customer_favorites_are_moved_to_front_and_marked(monkeypatch):
    seen = {}

    def fake_get_staff_favorites(customer_id, staff_ids):
        seen["customer_id"] = customer_id
        seen["staff_ids"] = list(staff_ids)
        return {"200"}

    monkeypatch.setattr(selection_runtime, "get_staff_favorites", fake_get_staff_favorites)

    result = selection_runtime._prioritize_specified_staff_entries_for_customer(
        _entries(),
        999,
    )

    assert seen == {
        "customer_id": 999,
        "staff_ids": ["100", "200", "300"],
    }
    assert [item["id"] for item in result] == ["200", "100", "300"]
    assert result[0]["is_favorite"] is True
    assert result[0]["description"].startswith("❤️ 收藏｜")
    assert all(item["is_favorite"] is False for item in result[1:])


def test_favorite_lookup_failure_keeps_normal_role_and_name_order(monkeypatch):
    def broken_get_staff_favorites(_customer_id, _staff_ids):
        raise RuntimeError("db unavailable")

    monkeypatch.setattr(selection_runtime, "get_staff_favorites", broken_get_staff_favorites)

    result = selection_runtime._prioritize_specified_staff_entries_for_customer(
        [
            {"id": "200", "label": "Beta", "description": "Role B", "role_order": 1},
            {"id": "300", "label": "Gamma", "description": "Role A", "role_order": 0},
            {"id": "100", "label": "Alpha", "description": "Role A", "role_order": 0},
        ],
        999,
    )

    assert [item["id"] for item in result] == ["100", "300", "200"]
    assert all(item["is_favorite"] is False for item in result)
