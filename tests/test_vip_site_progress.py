from web.app.services.site_data import _resolve_vip_name, _vip_progress


def test_site_normal_progress_auto_upgrades_to_gold():
    data = {
        "total_spent": 6000,
        "level": "銀級魔丸",
        "vip_level_index": 1,
        "vip_progress_base_total_spent": None,
    }

    assert _resolve_vip_name(data) == "金級魔丸"

    progress = _vip_progress(data)

    assert progress["next_name"] == "白金魔丸"
    assert progress["remaining"] == 6000
    assert progress["percent"] == 0


def test_site_stale_upgrade_baseline_does_not_block_gold():
    data = {
        "total_spent": 8880,
        "level": "銀級魔丸",
        "vip_level_index": 1,
        "vip_progress_base_total_spent": 5180,
        "vip_downgrade_logs": [],
    }

    assert _resolve_vip_name(data) == "金級魔丸"

    progress = _vip_progress(data)

    assert progress["next_name"] == "白金魔丸"
    assert progress["remaining"] == 3120
    assert progress["percent"] == 48


def test_site_downgraded_normal_member_starts_next_level_from_zero():
    data = {
        "total_spent": 10965,
        "level": "普通魔丸",
        "vip_level_index": 0,
        "vip_progress_base_total_spent": 10965,
    }

    assert _resolve_vip_name(data) == "普通魔丸"

    progress = _vip_progress(data)

    assert progress["next_name"] == "銀級魔丸"
    assert progress["remaining"] == 2000
    assert progress["percent"] == 0


def test_site_reupgraded_gold_starts_platinum_progress_from_zero():
    data = {
        "total_spent": 9180,
        "level": "金級魔丸",
        "vip_level_index": 2,
        "vip_progress_base_total_spent": 9180,
        "vip_progress_reset_active": True,
        "vip_downgrade_logs": [
            {
                "old_level": "金級魔丸",
                "new_level": "銀級魔丸",
                "progress_reset_total_spent": 5180,
            }
        ],
    }

    assert _resolve_vip_name(data) == "金級魔丸"

    progress = _vip_progress(data)

    assert progress["next_name"] == "白金魔丸"
    assert progress["remaining"] == 6000
    assert progress["percent"] == 0
