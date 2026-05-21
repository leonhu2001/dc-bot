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
