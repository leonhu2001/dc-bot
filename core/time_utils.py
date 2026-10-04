from datetime import datetime, timezone, timedelta


def get_taipei_now() -> datetime:
    taipei_tz = timezone(timedelta(hours=8))
    return datetime.now(taipei_tz)


def get_taipei_now_iso() -> str:
    return get_taipei_now().isoformat(timespec="seconds")


def get_taipei_now_text() -> str:
    return get_taipei_now().strftime("%Y/%m/%d %H:%M")


def parse_datetime_safe(value: str | None) -> datetime | None:
    if not value:
        return None

    try:
        dt = datetime.fromisoformat(str(value))
    except ValueError:
        return None

    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone(timedelta(hours=8)))

    return dt


# 舊名稱相容：bot.py 裡原本有些地方可能還在叫 _parse_datetime_safe
_parse_datetime_safe = parse_datetime_safe



def parse_utc_datetime_safe(value: str | None) -> datetime | None:
    """Parse database timestamps whose naive form is stored in UTC."""
    if not value:
        return None

    raw = str(value).strip()

    if not raw:
        return None

    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"

    try:
        dt = datetime.fromisoformat(raw)
    except ValueError:
        return None

    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)

    return dt


def get_taipei_date_from_utc(value: str | None) -> str | None:
    """Return YYYY-MM-DD in Taipei for a UTC-backed database timestamp."""
    dt = parse_utc_datetime_safe(value)

    if dt is None:
        return None

    taipei_tz = timezone(timedelta(hours=8))
    return dt.astimezone(taipei_tz).date().isoformat()


def format_taipei_datetime_from_utc(value: str | None) -> str | None:
    """Return a Taipei wall-clock display for a UTC-backed timestamp."""
    dt = parse_utc_datetime_safe(value)

    if dt is None:
        return None

    taipei_tz = timezone(timedelta(hours=8))
    return dt.astimezone(taipei_tz).strftime("%Y-%m-%d %H:%M")
