from __future__ import annotations

REPORT_STATUS_MISSING = "missing"
REPORT_STATUS_PENDING = "pending"
REPORT_STATUS_CHANGES_REQUESTED = "changes_requested"
REPORT_STATUS_APPROVED = "approved"

LOCKED_REPORT_LABELS = {
    REPORT_STATUS_MISSING: "未填寫報單",
    REPORT_STATUS_PENDING: "報單待審核",
    REPORT_STATUS_CHANGES_REQUESTED: "報單需修改",
}


def normalize_report_status(value) -> str:
    status = str(value or "").strip().lower()
    if status in {
        REPORT_STATUS_MISSING,
        REPORT_STATUS_PENDING,
        REPORT_STATUS_CHANGES_REQUESTED,
        REPORT_STATUS_APPROVED,
    }:
        return status
    return REPORT_STATUS_MISSING


def payout_financial_state(*, payout_status, report_status=None, report_required: bool = False) -> str:
    """Return paid/unpaid/locked without mutating the stored payout status."""
    if str(payout_status or "").strip().lower() == "paid":
        return "paid"
    if report_required and normalize_report_status(report_status) != REPORT_STATUS_APPROVED:
        return "locked"
    return "unpaid"


def payout_status_label(*, payout_status, report_status=None, report_required: bool = False) -> str:
    state = payout_financial_state(
        payout_status=payout_status,
        report_status=report_status,
        report_required=report_required,
    )
    if state == "paid":
        return "已發放"
    if state == "unpaid":
        return "待發放"
    return LOCKED_REPORT_LABELS.get(normalize_report_status(report_status), "未填寫報單")
