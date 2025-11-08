from __future__ import annotations

from datetime import date, datetime, time as dt_time, timedelta
from functools import lru_cache
from zoneinfo import ZoneInfo


@lru_cache(maxsize=8)
def get_timezone(name: str) -> ZoneInfo:
    return ZoneInfo(name)


def now(tz_name: str) -> datetime:
    return datetime.now(get_timezone(tz_name))


def ensure_timezone(dt: datetime, tz_name: str) -> datetime:
    tz = get_timezone(tz_name)
    if dt.tzinfo is None:
        return dt.replace(tzinfo=tz)
    return dt.astimezone(tz)


def isoformat(dt: datetime, tz_name: str) -> str:
    return ensure_timezone(dt, tz_name).isoformat(timespec="seconds")


def parse_ymd(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        return None


def collection_window(
    *,
    current: datetime | None,
    start_hour: int,
    end_hour: int,
    tz_name: str,
) -> tuple[bool, datetime, datetime]:
    tz_now = ensure_timezone(current or datetime.utcnow(), tz_name)
    start_t = dt_time(start_hour % 24, 0)
    end_t = dt_time(end_hour % 24, 0)

    start_dt = tz_now.replace(hour=start_t.hour, minute=0, second=0, microsecond=0)
    end_dt = tz_now.replace(hour=end_t.hour, minute=0, second=0, microsecond=0)

    if end_t <= start_t:
        if tz_now.time() < end_t:
            start_dt -= timedelta(days=1)
        else:
            end_dt += timedelta(days=1)

    is_in = start_dt <= tz_now <= end_dt
    return is_in, start_dt, end_dt