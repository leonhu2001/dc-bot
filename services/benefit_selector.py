from __future__ import annotations


# Keep the public checkout selector numeric so the existing website and order
# payload format do not need a parallel field for each benefit system.
# Legacy loyalty coupon ids stay unchanged. New benefit systems live in ranges
# far above the SQLite autoincrement values used by the legacy table.
ISSUED_BENEFIT_ID_BASE = 1_000_000_000
VIP_MONTHLY_ID_BASE = 2_000_000_000

SOURCE_LOYALTY = "loyalty"
SOURCE_ISSUED = "issued"
SOURCE_VIP_MONTHLY = "vip_monthly"


def encode_issued_benefit_id(benefit_id: int) -> int:
    return ISSUED_BENEFIT_ID_BASE + max(1, int(benefit_id))


def encode_vip_monthly_benefit_id(benefit_id: int) -> int:
    return VIP_MONTHLY_ID_BASE + max(1, int(benefit_id))


def decode_benefit_selector_id(value: int | str | None) -> tuple[str, int | None]:
    if value in (None, ""):
        return SOURCE_LOYALTY, None
    try:
        raw = int(str(value).strip())
    except (TypeError, ValueError):
        raise ValueError("福利券編號格式錯誤。")

    if raw >= VIP_MONTHLY_ID_BASE:
        return SOURCE_VIP_MONTHLY, raw - VIP_MONTHLY_ID_BASE
    if raw >= ISSUED_BENEFIT_ID_BASE:
        return SOURCE_ISSUED, raw - ISSUED_BENEFIT_ID_BASE
    if raw <= 0:
        raise ValueError("福利券編號格式錯誤。")
    return SOURCE_LOYALTY, raw
