import datetime
from zoneinfo import ZoneInfo
from croniter import croniter


class TimeUtils:
    @staticmethod
    def get_datetime_strftime_in_tz(dt: datetime.datetime, tz: ZoneInfo | str) -> str:
        return dt.astimezone(tz if isinstance(tz, ZoneInfo) else ZoneInfo(tz)).strftime("%Y-%m-%d %H:%M:%S")

def check_valid_cron_expression(expr: str):
    try:
        cron = croniter(expr, datetime.datetime.now())
        cron.get_next(datetime.datetime)
        return True
    except (ValueError, KeyError):
        return False
