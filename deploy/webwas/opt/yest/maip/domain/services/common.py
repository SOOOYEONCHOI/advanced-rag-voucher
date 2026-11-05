import mimetypes 
import json
from decimal import Decimal, ROUND_HALF_UP, localcontext
from urllib.parse import quote
from  datetime import datetime

from .sql import DbUtil

class CommonUtil(object):
    """
    """

    # 전체 유효숫자 정밀도. 저장할 소수 자릿수(기본 3)와 구분한다.
    DECIMAL_PRECISION = 50

    @classmethod
    def decimal_context(cls):
        """요청·계산 구간에만 적용하며 종료 시 기존 Decimal 컨텍스트를 복구한다."""
        return localcontext(prec=cls.DECIMAL_PRECISION, rounding=ROUND_HALF_UP)

    @classmethod
    def to_decimal(cls, value):
        """반올림 없이 유한한 소수로 변환한다. 빈값·NaN·Infinity는 거부한다."""
        if value is None:
            raise TypeError('A decimal value is required')
        if isinstance(value, bool):
            value = int(value)
        result = value if isinstance(value, Decimal) else Decimal(str(value).strip())
        if not result.is_finite():
            raise ValueError('A finite decimal value is required')
        return result

    @classmethod
    def round_decimal(cls, value, places=3):
        """입력·최종 저장 경계에서 지정한 소수 자릿수로 ROUND_HALF_UP 반올림한다."""
        with cls.decimal_context():
            return cls.to_decimal(value).quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP)

    @classmethod
    def unique_id(cls):
        import uuid
        ID = str(uuid.uuid4())
        #nowdate = app_methods.get_now()
        #ID = nowdate.strftime('%Y-%m-%d %H-%M-%S')
        return ID


    @classmethod
    def try_float(cls, number, default=None):
        try:
            return float(number)
        except Exception as e:
            return default


    @classmethod
    def try_decimal(cls, number, default=None):
        try:
            return cls.round_decimal(number)
        except Exception:
            return default


    # 2026-09-08 JHM: 소수 문자열의 정수 변환 실패를 방지하고 기존 정수화·기본값 동작을 유지.
    @classmethod
    def try_int(cls, number, default=None):
        """정수 변환 실패 시 소수 문자열만 Decimal로 재시도한다. 반올림하지 않는다."""
        try:
            return int(number)
        except ValueError:
            if isinstance(number, str):
                try:
                    return int(cls.to_decimal(number))
                except Exception:
                    pass
            return default
        except Exception:
            return default


    @classmethod
    def try_yyyymmdd(cls, date_text):
        try:
            datetime.strptime(date_text, '%Y-%m-%d')
            return date_text
        except Exception as e:
            return None


    @classmethod
    def blank_to_none(cls, text):
        try:
            if text != '':
                return text
            else:
                return None
        except Exception as e:
            return None


    @classmethod
    def get_utf8_filename(cls, filename):
        return quote(filename.encode('utf-8'))

    @classmethod
    def get_content_type(cls, filename):
        content_type=mimetypes.guess_type(filename)[0]
        return content_type

    @classmethod 
    def make_parameter(cls, qeury_dic):
        param = {}

        for k in qeury_dic.keys():
            v = qeury_dic.get(k)
            if (k=='Q' or k.startswith('_dic')) and isinstance(v, str):
                param[k] = {}
                try:
                    param[k] = json.loads(v, parse_float=Decimal)
                    continue
                except Exception as ex:
                    print(ex)
                    continue

            v = qeury_dic.getlist(k)
            param[k] = v
            if isinstance(v, list):
                if len(v)==1:
                    param[k] = v[0]
                else:
                    param[k] = v

            elif isinstance(v, dict):
                pass

        return param

    @classmethod
    def load_json_list(cls, json_str):
        try:
            return json.loads(json_str, parse_float=Decimal)
        except json.JSONDecodeError as e:
            return None
    

    @classmethod
    def to_24h(cls, time_text):
        """
        시간 문자열을 24시간 'HH:MM' 형식으로 정규화한다.

        [2026-05-30 추가 사유]
        이식 과정에서 timepicker 라이브러리가 jonthornton(jquery.timepicker) -> bootstrap-timepicker
        로 교체되면서, 일부 화면이 12시간제 'h:mm AM/PM'(예: '3:00 PM')을 전송하게 되었다.
        서버는 'prod_date + 시간' 을 DateTimeField('YYYY-MM-DD HH:MM')로 파싱하므로 12h 표기가 오면
        거부되어 생산실적 work_finish 등이 500을 냈다.
        클라이언트 위젯 수정(showMeridian:false)과 별개로, PDA/외부연동/향후 위젯 교체 등 어떤 진입점에서
        와도 안전하도록 서버에서 '15:00' / '3:00 PM' / '15:00:00' 등을 모두 'HH:MM'(24h)로 통일한다.
        값이 비었거나(None/'') 알 수 없는 포맷이면 원본을 그대로 반환하여 기존 동작을 보존한다(최소 회귀).
        """
        if not time_text:
            return time_text
        time_text = str(time_text).strip()
        # 24h(분/초) -> 12h(AM/PM, 공백 유무) 순으로 시도, 첫 매칭을 'HH:MM'으로 반환
        for fmt in ('%H:%M', '%H:%M:%S', '%I:%M %p', '%I:%M%p'):
            try:
                return datetime.strptime(time_text, fmt).strftime('%H:%M')
            except ValueError:
                continue
        return time_text


class CommonService():

    def get_seq_number(self, code):
        '''
        Code별 시퀀스 번호 생성 (seq_maker)
        '''
        sql = '''
        exec make_seq_number %(code)s
        '''
        dc = {'code': code}
        seq_data = DbUtil.get_row(sql,dc)
        seq_number = seq_data.get('seq_number')
        return seq_number
