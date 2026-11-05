from zoneinfo import ZoneInfo

from  datetime import datetime, timedelta
from dateutil.parser import parse as date_parse
from dateutil.relativedelta import relativedelta
from configurations import settings

class DateUtil(object):

    #@staticmethod
    #def get_now():
    #    return datetime.datetime.now(ZoneInfo(settings.TIME_ZONE))


    @staticmethod
    def get_timezone():
        return ZoneInfo(settings.TIME_ZONE)


    @staticmethod
    def get_aszone(value):
        return value.astimezone(ZoneInfo(settings.TIME_ZONE))


    @staticmethod
    def parse_datetime(value):
        return value if type(value) is datetime or not value else date_parse(value)


    @staticmethod
    def get_current_datetime(tz=None):
        #strftime("%Y-%m-%d %H:%M:%S")
        #tz = ZoneInfo(settings.TIME_ZONE)
        #tz = ZoneInfo('Asia/Seoul')
        # settings.TIME_ZONE
        #now = timezone.localtime()
        #now = datetime.datetime.now(tz)
        #json.dump(datetime.now().strftime('%Y-%m-%dT%H:%M:%SZ'))
        #datetime.strptime('2011-05-25T20:34:05.787Z', '%Y-%m-%dT%H:%M:%S.%fZ')
        #json.dumps(datetime.datetime.now().isoformat())
        #now = datetime.datetime.now(tz)
        now = None
        if tz is None:
            tz = ZoneInfo(settings.TIME_ZONE)

        now = datetime.now(tz)

        return now


    @staticmethod
    def get_today(tz=None):
        today = DateUtil.get_current_datetime(tz)
        return today.date()


    @staticmethod
    def get_today_string(tz=None):
        today = DateUtil.get_current_datetime(tz)
        return today.strftime("%Y-%m-%d")


    @staticmethod
    def get_current_year():
        now = DateUtil.get_current_datetime()
        return now.year


    @staticmethod
    def get_yesterday():
        now = DateUtil.get_current_datetime()
        yesterday = now - timedelta(days=1)
        return yesterday

    @staticmethod
    def add_days(date, days):
        return date + timedelta(days=days)


    @staticmethod 
    def get_week_monday(date1):
        """해당 주의 월요일을 리턴
        """
        if type(date1) is str:
            date1 = datetime.strptime(date1, '%Y-%m-%d')
        weekday = date1.weekday
        if type(date1) is datetime:
            monday = date1.date() - timedelta(days=weekday())
        else:
            monday = date1 - timedelta(days=weekday())
        return monday


    @staticmethod 
    def get_week_friday(date1):
        """해당 주의 금요일을 리턴
        """
        if type(date1) is str:
            date1 = datetime.strptime(date1, '%Y-%m-%d')
        weekday = date1.weekday
        if type(date1) is datetime:
            monday = date1.date() + timedelta(days=4-weekday())
        else:
            monday = date1 + timedelta(days=4-weekday())
        return monday


    @staticmethod
    def date_to_string(value):
        return value.strftime('%Y-%m-%d %H:%M:%S')


    @staticmethod
    def diff_timespan(endTime,startTime):
        td = endTime - startTime
        days, hours, minutes = td.days, td.seconds // 3600, td.seconds // 60 % 60
        return td,'%s/%s:%s'%(str(days),str(hours),str(minutes))
    

    @staticmethod
    def last_day_of_month(data_date):
        """해당월의 말일 리턴
        """
        if type(data_date) is str:
            data_date = datetime.strptime(data_date, '%Y-%m-%d')
        return (data_date.replace(day=1) + timedelta(days=31)).replace(day=1) - timedelta(days=1)

    @staticmethod
    def add_month(data_date, month):
        return data_date + relativedelta(months=month)

    @staticmethod
    def get_diff_seconds(start_dt, end_dt):
        new_tz = DateUtil.get_timezone()

        start_time = start_dt.replace(tzinfo=new_tz)
        end_time = end_dt.replace(tzinfo=new_tz)

        time_diff = end_time - start_time
        duration = time_diff.total_seconds()

        return duration

    def is_convertible_to_date(date):
        try:
            # 문자열을 datetime 객체로 파싱
            parsed = datetime.strptime(date, "%Y-%m-%d")
            # datetime.date 객체로 변환
            _ = parsed.date()
            return True
        except ValueError:
            return False
        
    def get_one_month_range(year, month):
        start_date = datetime(year, month, 1)
        if month == 12:
            end_date = datetime(year + 1, 1, 1)
        else:
            end_date = datetime(year, month + 1, 1)
        return start_date.strftime('%Y-%m-%d'), end_date.strftime('%Y-%m-%d')

    #@classmethod
    #def timedelta_minutes(cls, start_time, end_time):
    #    try:
    #        st = datetime.strptime(start_time, '%H:%M')
    #        et = datetime.strptime(end_time, '%H:%M')
    #        delta = et - st
    #        minutes = delta.seconds / 60
    #        return minutes
            
    #    except Exception as ex:
    #        return 0
        
