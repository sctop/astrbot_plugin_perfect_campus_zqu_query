import datetime
from zoneinfo import ZoneInfo


class TimeUtils:
    @staticmethod
    def get_datetime_strftime_in_tz(dt: datetime.datetime, tz: ZoneInfo | str) -> str:
        return dt.astimezone(tz if isinstance(tz, ZoneInfo) else ZoneInfo(tz)).strftime("%Y-%m-%d %H:%M:%S")