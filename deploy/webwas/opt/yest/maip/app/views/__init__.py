import json, importlib, logging, time
from zoneinfo import ZoneInfo
from datetime import datetime
from decimal import Decimal
from domain.services.common import CommonUtil


from django.http import Http404, HttpRequest, HttpResponse, JsonResponse

from django.core.exceptions import PermissionDenied
from django.views import View
from django.shortcuts import render,redirect

from django.contrib.auth import login, logout



from configurations import settings
from django.conf import settings as django_settings
from domain.gui import GUIConfiguration
from domain.models.system import MenuUseLog, SystemOption
from domain.models.user import User
from domain.services.logging import LogWriter
from domain.services.account import AccountService


logger = logging.getLogger(__name__)


def _required_auth_code(method):
    """조회는 R, 변경은 W를 요구한다. 데이터 API 는 PUT·PATCH·DELETE 로도 바꾼다."""
    return 'W' if method in ('POST', 'PUT', 'PATCH', 'DELETE') else 'R'


def authorize_menu_codes(request, menu_codes, target):
    """메뉴 권한을 확인한다. 통과하면 None, 거부하면 사유 문자열을 돌려준다.

    `menu_codes` 가 None이면 매핑 미등록, 빈 목록이면 로그인만 요구한다는 뜻이다.
    여러 코드가 오면 **하나라도 권한이 있으면 통과**한다(한 API를 여러 화면이 공유한다).

    `settings.API_AUTHZ_MODE`
      off     — 검사하지 않는다
      warn    — 매핑 미등록은 경고만 남기고 통과시킨다 (이관 중 기본값)
      enforce — 매핑 미등록도 거부한다
    """
    # django.conf.settings 로 읽는다. `from configurations import settings` 는 모듈을
    # 직접 참조해 DJANGO_SETTINGS_MODULE 지정·override_settings 가 반영되지 않는다.
    mode = getattr(django_settings, 'API_AUTHZ_MODE', 'warn')
    if mode == 'off':
        return None

    if menu_codes is None:
        logger.warning('권한 매핑이 없는 경로: %s (user=%s, mode=%s)',
                       target, request.user.username, mode)
        if mode == 'enforce':
            return '권한 설정이 없는 기능입니다.'
        return None

    if not menu_codes:
        return None

    required = _required_auth_code(request.method)
    for code in menu_codes:
        if required in (AccountService.check_user_auth(request.user, code) or ''):
            return None

    logger.info('권한 거부: %s (user=%s, 필요=%s, 대상메뉴=%s)',
                target, request.user.username, required, menu_codes)
    return '이 기능을 사용할 권한이 없습니다.'


class MESBaseView(View):

    def make_parameter(self, qeury_dic):
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

    def dispatch(self, request, *args, **kwargs):

        remote_addr = request.META.get('REMOTE_ADDR')
        method = request.method
        if request.user.is_anonymous:
            return self.response401(request, '로그인이 만료되었습니다. 다시 로그인해 주세요.')

        # 세션은 살아 있어도 계정이 그 사이 비활성화됐을 수 있다. 매 요청 확인한다.
        if not request.user.is_active:
            logout(request)
            return self.response401(request, '사용할 수 없는 계정입니다.')

        if request.method in ['PUT','DELETE']:
            try:
                self.parms = parser.parse(request.body)
            except:
                self.parms = {}
        else:
            self.gparam = self.make_parameter(request.GET)
            self.posparam = self.make_parameter(request.POST)

        with CommonUtil.decimal_context():
            return super().dispatch(request, *args, **kwargs)

    def make_response(self, content_resp):
        res = HttpResponse(content_resp)
        return res

    def make_json_response(self, data):
        res_json = JsonResponse(data, safe=False, json_dumps_params={'ensure_ascii':False})
        return res_json

    def response500(self, request, reason, ex):
        # 예외 원문에는 SQL 조각·컬럼명·접속정보가 섞여 들어온다. 운영에서는
        # 호출자가 정한 문구만 내보내고 원문은 DB 로그에만 남긴다.
        dic_content = {'message': reason}
        if ex and django_settings.DEBUG:
            dic_content['ex'] = str(ex)
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            content = json.dumps(dic_content, ensure_ascii=False)
            return HttpResponse(status=500, content=content)

        return render(request, 'error.html', dic_content, status=500)

    def response401(self, request, reason):
        dic_content = {'message': reason}
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            content = json.dumps(dic_content, ensure_ascii=False)
            return HttpResponse(status=401, content=content)

        return render(request, '401.html', dic_content, status=401)

    def response403(self, request, reason):
        dic_content = {'message': reason}
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            content = json.dumps(dic_content, ensure_ascii=False)
            return HttpResponse(status=403, content=content)

        return render(request, '403.html', dic_content, status=403)


    def response404(self, request, reason):
        dic_content = {'message': reason}
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            content = json.dumps(dic_content, ensure_ascii=False)
            return HttpResponse(status=404, content=content)
        
        return render(request, '404.html', dic_content, status=404)


# 요청 전체를 테넌트 컨텍스트로 감싸는 task. `ApiModuleView._execute_tenant_task` 참조.
TENANT_TASKS = {'item'}


class ApiModuleView(MESBaseView):
    '''
    권한 처리여부 결정할 것
    현재의 경로로 GET/POST Method 이용시 
    '''
    http_method_names = ['get', 'post']

    def dispatch(self, request, *args, **kwargs):
        """동적 dispatch라 데코레이터로 권한을 걸 수 없어, 원본 MES에는 인가가
        아예 없었다(로그인만 하면 모든 업무 API 호출 가능). `apiPermissionMap` 은
        정의만 되고 호출되지 않는 죽은 코드였다. 여기서 그 맵을 실제로 쓴다.
        """
        # 인가는 로그인 확인 뒤에 와야 한다. 익명 사용자에게는 403이 아니라 401을 준다.
        if request.user.is_anonymous:
            return self.response401(request, '로그인이 만료되었습니다. 다시 로그인해 주세요.')

        task_name = kwargs.get('task_name')
        view_name = kwargs.get('view_name')
        denied = authorize_menu_codes(
            request,
            GUIConfiguration.get_menu_code_by_taskview(task_name, view_name),
            '{}/{}'.format(task_name, view_name),
        )
        if denied:
            return self.response403(request, denied)

        return super().dispatch(request, *args, **kwargs)



    def api_execute(self, request, *args, **kwargs):
        
        task_name = kwargs.get('task_name',None)
        view_name = kwargs.get('view_name',None)
        data = None
        try:
            module_path = 'app.views.{}.{}'.format(task_name, view_name)            
            module = importlib.import_module(module_path)
            func = getattr(module, view_name, None)

            if func and task_name in TENANT_TASKS:
                return self._execute_tenant_task(request, module, func)
            if func:
               data = func(self)
            else:
                message = "ApiModuleView view_name is not exist : {}".format(view_name)
                LogWriter.add_dblog('error', view_name, message)
                return self.response404(request, '요청한 기능을 찾을 수 없습니다.')

        except PermissionDenied:
            # 메뉴 매핑은 경로 단위라 action 단위 거부는 뷰가 던진다.
            return self.response403(request, '이 기능을 사용할 권한이 없습니다.')
        except Exception as ex:
            message = "ApiModuleView error : {}".format(view_name)
            LogWriter.add_dblog('error', message, ex)
            return self.response500(request, '처리 중 오류가 발생했습니다. 잠시 후 다시 시도해 주세요.', ex)

        return self.make_json_response(data)

    def _execute_tenant_task(self, request, module, func):
        """데이터 관리 화면 API(`app/views/item/`). 규약은 그 패키지 docstring 에 있다.

        - 모듈의 `READ_ACTIONS` 에 없는 action 은 POST 로만 받는다. MES 는 메서드로 R/W 를
          판정하므로 변경 action 을 GET 으로 부르면 읽기 권한만으로 통과하기 때문이다.
          선언을 빠뜨리면 열리는 쪽이 아니라 막히는 쪽이 된다.
        - 요청 전체를 `tenant_atomic()` 으로 감싼다. RLS 라 밖에서 읽으면 예외 없이 0건이다.
        - `ItemApiError` 는 400 문구로, `Http404` 는 404, `PermissionDenied` 는 그 사유 그대로 403 으로
          바꾼다. 모두 롤백된 뒤다. 그 밖의 예외는 `api_execute` 가 500 으로 바꾼다.
        """
        from app.views.item import ItemApiError
        from domain.tenancy import current_tenant, tenant_atomic

        action = self.gparam.get('action', '')
        if action not in getattr(module, 'READ_ACTIONS', frozenset()) and request.method != 'POST':
            return JsonResponse({'success': False, 'message': 'POST 로 요청해야 하는 기능입니다.'},
                                status=405, json_dumps_params={'ensure_ascii': False})
        request.tenant = current_tenant()
        try:
            with tenant_atomic(request.tenant):
                data = func(self)
        except ItemApiError as exc:
            return JsonResponse({'success': False, 'message': str(exc)}, status=400,
                                json_dumps_params={'ensure_ascii': False})
        except Http404 as exc:
            return self.response404(request, str(exc) or '대상을 찾을 수 없습니다.')
        except PermissionDenied as exc:
            # 서비스가 던지는 거부 사유는 사용자 문구다(예: 검수 완료 이미지는 관리자만 삭제).
            return self.response403(request, str(exc) or '이 기능을 사용할 권한이 없습니다.')
        return self.make_json_response(data)

    def get(self, request, *args, **kwargs):
        
        # 스마트공장 1번가 로그 수집
        return self.api_execute(request, *args, **kwargs)

    def post(self, request, *args, **kwargs):

        # 스마트공장 1번가 로그 수집
        return self.api_execute(request, *args, **kwargs)


class GUITemplatesView(MESBaseView):
    http_method_names = ['get']

    def get(self, request, *args, **kwargs):

        userinfo = WebUserInfo(request)
        gui_code = kwargs.get('gui_code', None)
        template_key = kwargs.get('template_key', 'default')
        content_resp = None
        
        if gui_code:
            gui_info = GUIConfiguration.get_gui_info(gui_code)

            if gui_info is None:
                return self.response404(request, 'The requested page could not be found')

            gparam = self.gparam 
            # params => gparam
            gui_params = gui_info.get('params')
            if gui_params:
                for key, value in gui_params.items():
                    gparam[key] = value

            gui = GUIPageInfo(gui_code, gui_info, gparam)
            gui.template_key = template_key
            # 현재 로긴한 사용자와 gui_code로 권한체크 시작
            authcode = AccountService.check_user_auth(request.user, gui_code)
            if(authcode is None):
                return self.response403(request, '이 화면을 볼 권한이 없습니다.')
            else:
                userinfo.set_authcode(authcode)

            templates = gui_info.get('templates')
            template_path = templates.get(template_key, None)
            if template_path:
                try:
                    content_resp = render(request, template_path, {'gparam':gparam, 'posparam':self.posparam, 'userinfo':userinfo, 'gui':gui, 'html':template_path})
                    # menu_log insert
                    try:
                        if template_key == 'default':
                            log = MenuUseLog()
                            log.MenuCode = gui_code 
                            log.User_id = request.user.id 
                            log.save()
                    except Exception as ex:
                        LogWriter.add_dblog('error', 'MenuUseLog save', ex)

                except Exception as ex:
                    source = 'GUITemplatesView - template_path : {}'.format(template_path)
                    LogWriter.add_dblog('error', source, ex)
                    # 개발의 디버깅을 위해 raise한다, TemplateDoesNotExist포함
                    #raise ex
                    return self.response500(request, '화면을 여는 중 오류가 발생했습니다. 관리자에게 문의해 주세요.', ex)

            else:
                return self.response404(request, 'No registered templates')
        else:
            return self.response404(request, 'You have taken the wrong path')

        httpres = HttpResponse(content_resp)

        return httpres


class TemplatePathView(MESBaseView):
    http_method_names = ['get']

    def dispatch(self, request, *args, **kwargs):
        if request.user.is_anonymous:
            return self.response401(request, '로그인이 만료되었습니다. 다시 로그인해 주세요.')

        folder = kwargs.get('folder')
        template_name = kwargs.get('template_name')
        denied = authorize_menu_codes(
            request,
            GUIConfiguration.get_page_menu_code(folder, template_name),
            'page/{}/{}'.format(folder, template_name),
        )
        if denied:
            return self.response403(request, denied)

        return super().dispatch(request, *args, **kwargs)



    def get(self, request, *args, **kwargs):

        userinfo = WebUserInfo(request)
        #if request.user.is_anonymous:
        #    return HttpResponseRedirect(reverse('login', kwargs=kwargs))
        folder = kwargs.get('folder', None)
        template_name= kwargs.get('template_name', None)
        template_path = 'page/{}/{}.html'.format(folder, template_name)
        httpres = None
        try:
            content_resp = render(request, template_path, {'gparam':self.gparam, 'posparam':self.posparam, 'userinfo':userinfo})
            httpres = HttpResponse(content_resp)
        except Exception as ex:
            # 예외 원문을 상태줄에 싣지 않는다 — 한글이면 응답이 깨지고, 내부 정보가 샌다.
            logger.exception('page 렌더 실패: %s', template_path)
            httpres = HttpResponse(status=500)

        return httpres


class SystemDefaultRenderer():

    #@login_required(login_url='/login')
    @staticmethod
    def home(request):
        """Renders the home page."""
        assert isinstance(request, HttpRequest)
        userinfo = WebUserInfo(request)

        if request.user.is_authenticated==False:
            return redirect('login')

        q = SystemOption.objects.filter(Code='LOGO_TITLE').values('Value')
        option = q.first()
        if option:
            system_title = option.get('Value')
        else:
            system_title = '제조AI플랫폼'

        q = SystemOption.objects.filter(Code='main_menu').values('Value')
        option = q.first()
        if option:
            default_menu_code = option.get('Value')
        else:
            # 첫 화면(고정 첫 탭)은 메뉴 맨 위의 대시보드다(사용자 결정 2026-10-21). 권한이 없으면 메뉴 트리의 첫 화면이 열린다.
            default_menu_code = 'wm_dashboard'

        # 상단 바 We.RAG 로고. href 에 javascript: 같은 값이 들어가지 않게 http(s) 만 넘긴다
        werag_url = django_settings.WERAG_URL
        if not werag_url.lower().startswith(('http://', 'https://')):
            werag_url = ''

        return render(
            request,
            'app/index.html',
            {
                'userinfo' : userinfo,
                'system_title': system_title,
                'profiles':'',
                'default_menu_code': default_menu_code,
                'werag_url': werag_url,
            }
        )

    # 403·404 는 MESBaseView.response403 / response404 가 같은 템플릿으로 응답한다.
    # 여기 있던 notfound403 / notfound404 는 URLConf 에 연결되지 않은 중복이었다.
    # mobile / setup 도 제거했다 — 모바일·MQTT 기능과 함께 템플릿과 설정이 사라졌다.

    @staticmethod
    def error500(request):
        return render(
            request,
            'error.html',
            {
                'title':'setup',
                'message':'Your application description page.',
                'year':datetime.now().year,
            }
        )

    def alive(request):

        now = datetime.now()
        tz = ZoneInfo(settings.TIME_ZONE)
        o = now.astimezone(tz)
        r = o.isoformat()
        if o.microsecond:
            r = r[:23] + r[26:]
        if r.endswith('+00:00'):
            r = r[:-6] + 'Z'

        return JsonResponse({'success': True, 'datetime': r})


class WebUserInfo():
    username = ''
    login_id = ''
    group_code =''
    auth_code = ''
    can_read = False
    can_write = False
    ip_address = ''
    def __init__(self, request):
        self.ip_address = request.META.get('REMOTE_ADDR')
        if request.user.is_authenticated:
            self.username = request.user.userprofile.Name
            self.login_id = request.user.username

            if request.user.userprofile.UserGroup:
                self.group_code = request.user.userprofile.UserGroup.Code
        else:
            self.username = 'anonymous'
            self.login_id = 'anonymous'

    def set_authcode(self, authcode):
        self.auth_code = authcode

        if authcode is None:
            return

        if "R" in authcode:
            self.can_read = True

        if "W" in authcode:
            self.can_write = True
        return

    def dump(self):
        dic = {'username': self.username, 'login_id':self.login_id,'group_code':self.group_code, 'auth_code':self.auth_code, 'can_read':self.can_read, 'can_write': self.can_write}
        return json.dumps(dic, ensure_ascii=False)


class GUIPageInfo():
    gui_code = ''
    gui_name = ''
    template_key = ''
    site_name = ''
    action = ''
    def __init__(self, code, gui, gparam):
        self.site_name = settings.SITE_NAME
        self.action = gparam.get('action')
        self.gui_code = code
        self.gui_name = gui.get('name','')

        for k,v in gparam.items():
            setattr(self, k, v)

