from __future__ import annotations

from pathlib import Path


def replace_once(source: str, old: str, new: str, label: str) -> str:
    count = source.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected one match, got {count}")
    return source.replace(old, new, 1)


def main() -> None:
    router = Path("web/app/routers/admin_payout_summary.py")
    source = router.read_text(encoding="utf-8")
    source = replace_once(
        source,
        'def _collect_bulk_payout_notification_targets(month: str, role: str) -> list[dict]:\n'
        '    targets: list[dict] = []\n'
        '    for person in fetch_rows(month, role, None, status="unpaid"):\n',
        'def _collect_bulk_payout_notification_targets(month: str, role: str) -> list[dict]:\n'
        '    targets: list[dict] = []\n'
        '    rows, _ = fetch_rows(month, role, None, status="unpaid")\n'
        '    for person in rows:\n',
        "bulk fetch_rows tuple handling",
    )
    router.write_text(source, encoding="utf-8")

    test = Path("tests/test_payout_notifications.py")
    source = test.read_text(encoding="utf-8")
    source = replace_once(
        source,
        '        lambda month, role, q, status="unpaid": rows if status == "unpaid" else [],\n',
        '        lambda month, role, q, status="unpaid": (rows, {}) if status == "unpaid" else ([], {}),\n',
        "bulk target regression mock",
    )
    test.write_text(source, encoding="utf-8")


if __name__ == "__main__":
    main()
