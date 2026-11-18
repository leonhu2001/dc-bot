"""Guard regression for safe VIP-only history compensation from live audit shape."""
import json
import sqlite3
import subprocess
import sys
from pathlib import Path

from core.database import _deserialize_customer_data
from scripts import repair_internal_staff_vip_20261119 as repair


ROOT = Path(__file__).resolve().parents[1]


def order(channel, user, key, vip=0, wallet=0):
    data = {
        "category": "staff_internal", "order_rule_key": key,
        "customer_id": user, "reward_counted": True,
        "reward_excluded": vip == 0, "reward_amount": vip,
        "wallet_points_counted": bool(wallet),
        "wallet_point_amount": wallet, "amount": max(vip, wallet),
        "order_no": f"MO-TEST-{channel}",
    }
    return {
        "channel_id": channel, "category": "staff_internal",
        "customer_id": user, "data_json": json.dumps(data, ensure_ascii=False),
        "amount": max(vip, wallet),
    }


def customer(user, total=0, points=0, wallet=0):
    data = {
        "total_spent": total, "points": points,
        "point_adjustment": points - total // 100,
        "wallet_point_spend_total": wallet, "vip_level_index": 1 if total else 0,
    }
    return {
        "customer_id": user, "total_spent": total, "points": points,
        "level": "銀級魔丸" if total else "普通魔丸",
        "data_json": json.dumps(data, ensure_ascii=False),
    }


def seed_db(dbfile, orders, customers):
    with sqlite3.connect(dbfile) as db:
        db.execute(
            "CREATE TABLE orders (channel_id INTEGER PRIMARY KEY, category TEXT,"
            " customer_id INTEGER, data_json TEXT, amount INTEGER)"
        )
        db.execute(
            "CREATE TABLE customers (customer_id INTEGER PRIMARY KEY, total_spent INTEGER,"
            " points INTEGER, level TEXT, data_json TEXT)"
        )
        for item in orders:
            db.execute(
                "INSERT INTO orders VALUES (?, ?, ?, ?, ?)",
                tuple(item[name] for name in ("channel_id", "category", "customer_id", "data_json", "amount"))
            )
        for item in customers:
            db.execute(
                "INSERT INTO customers VALUES (?, ?, ?, ?, ?)",
                tuple(item[name] for name in ("customer_id", "total_spent", "points", "level", "data_json"))
            )


def simulated_live_audit():
    # 2 proven non-wallet VIP credits; 7 wallet-order records (4 other users),
    # reflecting the read-only production report without using any real user IDs.
    vip_user = 101
    orders = [
        order(11, 202, "staff_internal_aw_collision", wallet=400),
        order(12, 202, "staff_internal_ammo_dump_500m", wallet=2650),
        order(13, vip_user, "staff_internal_car_500m", vip=2480),
        order(14, 303, "staff_internal_ammo_dump_500m", wallet=2650),
        order(15, 404, "staff_internal_ammo_dump_500m", wallet=2650),
        order(16, 303, "staff_internal_aw_collision", wallet=400),
        order(17, 505, "staff_internal_ammo_dump_500m", wallet=2650),
        order(18, 505, "staff_internal_ammo_dump_500m", wallet=2650),
        order(19, vip_user, "staff_internal_car_500m", vip=2480),
    ]
    customers = [
        customer(vip_user, total=4960, points=58),
        customer(202, total=37390, points=373),
        customer(303, total=29700, points=297),
        customer(404, total=3760, points=37),
        customer(505, total=1420, points=14),
    ]
    return orders, customers


def test_vip_only_preflight_blocks_no_wallet_customer_for_proven_4960():
    orders, customers = simulated_live_audit()
    full = repair.build_plan(orders, customers)
    assert full["blockers"], "legacy full repair must remain blocked on wallet mismatch"
    plan = repair.build_plan(orders, customers, vip_only=True)
    assert plan["blockers"] == []
    assert plan["scanned"] == 9
    assert plan["wallet_only_skipped"] == 7
    assert len(plan["candidates"]) == 2
    assert len(plan["changes"]) == 1
    change = plan["changes"][0]
    assert (change["before"], change["after"]) == (4960, 0)
    assert (change["before_points"], change["after_points"]) == (58, 9)
    assert (change["level_before"], change["level_after"]) == ("銀級魔丸", "普通魔丸")
    assert change["new_data"]["wallet_point_spend_total"] == 0


def test_vip_only_backup_reversal_no_wallet_edits_repeat_idempotent(tmp_path, monkeypatch):
    dbfile = tmp_path / "bot.db"
    orders, customers = simulated_live_audit()
    seed_db(dbfile, orders, customers)
    monkeypatch.setattr(repair, "_services_stopped", lambda: True)

    preflight = repair.repair(dbfile, vip_only=True, check_apply=True)
    assert len(preflight["changes"]) == 1
    with sqlite3.connect(dbfile) as db:
        assert db.execute("SELECT total_spent FROM customers WHERE customer_id=101").fetchone()[0] == 4960

    repair.repair(dbfile, vip_only=True, apply=True)
    with sqlite3.connect(dbfile) as db:
        total, points, level, raw = db.execute(
            "SELECT total_spent, points, level, data_json FROM customers WHERE customer_id=101"
        ).fetchone()
        assert (total, points, level) == (0, 9, "普通魔丸")
        assert json.loads(raw)["wallet_point_spend_total"] == 0
        for ch in (13, 19):
            item = db.execute("SELECT data_json, amount FROM orders WHERE channel_id=?", (ch,)).fetchone()
            obj = json.loads(item[0])
            assert item[1] == 2480
            assert obj["reward_amount"] == 0
            assert obj["vip_internal_exclusion_reversed_amount"] == 2480
            assert obj["reward_excluded"]
            assert obj["internal_non_vip_vip_only_repaired_at"]
        for ch in (11, 12, 14, 15, 16, 17, 18):
            original = next(x for x in orders if x["channel_id"] == ch)
            item = db.execute("SELECT data_json, amount FROM orders WHERE channel_id=?", (ch,)).fetchone()
            assert item == (original["data_json"], original["amount"])
        for user in (202, 303, 404, 505):
            row = db.execute("SELECT total_spent FROM customers WHERE customer_id=?", (user,)).fetchone()
            assert row[0] == next(x["total_spent"] for x in customers if x["customer_id"] == user)

    backups = list((tmp_path / "_archive").glob("staff_internal_vip_*/bot.db"))
    assert len(backups) == 1
    assert not repair.repair(dbfile, vip_only=True, apply=True)["candidates"]
    assert len(list((tmp_path / "_archive").glob("staff_internal_vip_*/bot.db"))) == 1
    assert repair.repair(dbfile)["blockers"], "wallet history remains explicitly unresolved"


def test_strict_preflight_never_stops_services_on_invalid_data(tmp_path):
    dbfile = tmp_path / "bot.db"
    seed_db(
        dbfile, [order(11, 101, "staff_internal_car_500m", vip=2480)],
        [customer(101, total=1000, points=10)],
    )
    import pytest
    with pytest.raises(RuntimeError, match="無法驗證"):
        repair.repair(dbfile, vip_only=True, check_apply=True)
    assert not (tmp_path / "_archive").exists()


def test_wallet_bucket_survives_database_decode():
    data = {
        "total_spent": 4000, "points": 45, "point_adjustment": 5,
        "wallet_point_spend_total": 3050,
    }
    decoded = _deserialize_customer_data(data)
    assert decoded["wallet_point_spend_total"] == 3050
    assert decoded["point_adjustment"] == 5
    assert _deserialize_customer_data({"total_spent": 0})["wallet_point_spend_total"] == 0


def test_vip_only_cli_flag_recognized_even_without_site_packages(tmp_path):
    script = ROOT / "scripts" / "repair_internal_staff_vip_20261119.py"
    cmd = [
        sys.executable, "-S", str(script), "--db", str(tmp_path / "notfound.db"),
        "--vip-only", "--check-apply",
    ]
    r = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, check=False, timeout=15)
    assert r.returncode == 1
    assert "找不到 bot.db" in r.stderr
    assert "unrecognized arguments" not in r.stderr


def test_windows_runner_avoids_piped_windows_crlf_arguments():
    ps = (ROOT / "scripts" / "repair_internal_staff_vip.ps1").read_text(encoding="utf-8")
    shell = (ROOT / "scripts" / "repair_internal_staff_vip_remote.sh").read_text(encoding="utf-8")
    assert "| & ssh" not in ps
    assert "bash scripts/repair_internal_staff_vip_remote.sh" in ps
    assert "--vip-only" in ps
    assert "trap restore EXIT" in shell
    assert shell.index("--check-apply") < shell.index("systemctl stop")
    assert "--vip-only --apply" in shell
    assert "dc-bot-market.service" in shell
    r = subprocess.run(
        ["bash", "-n", str(ROOT / "scripts" / "repair_internal_staff_vip_remote.sh")],
        capture_output=True, text=True, check=False,
    )
    assert r.returncode == 0, r.stderr
