from datetime import date, datetime, time
from zoneinfo import ZoneInfo


def local_to_utc(d: date, t: time, tz: str) -> datetime:
    z = ZoneInfo(tz)
    local = datetime.combine(d, t).replace(tzinfo=z)
    return local.astimezone(ZoneInfo("UTC"))


def test_ny_open_dst_shift():
    tz = "America/New_York"
    open_t = time(9, 30)

    winter = local_to_utc(date(2025, 1, 15), open_t, tz)
    summer = local_to_utc(date(2025, 7, 15), open_t, tz)

    assert winter.hour == 14 and winter.minute == 30
    assert summer.hour == 13 and summer.minute == 30
