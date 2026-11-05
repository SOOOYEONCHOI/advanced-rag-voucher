from django.contrib.auth.models import User
from django.contrib.auth import login, authenticate, logout
from django.views import View
from django.shortcuts import render, redirect
from django.urls import reverse
from django.contrib.auth.views import LoginView, LogoutView
from django.http import HttpResponse, JsonResponse, HttpResponseRedirect, HttpRequest
from django.views.decorators.csrf import csrf_exempt

from configurations import settings
from domain.models.system import LoginLog
from domain.services import login_throttle
from domain.models.user import UserProfile
from domain.services.logging import LogWriter
from domain.services.system import SystemService


login_page = 'app/login_mes.html'


def _locked_message(seconds):
    """잠금 안내. 남은 시간은 분으로 올려 말한다(283초 → 5분)."""
    return '로그인 시도가 많아 잠겼습니다. {}분 뒤에 다시 시도해 주세요.'.format(-(-seconds // 60))


class AccountLoginView(View):
    http_method_names = ['get','post']
    next = '/'

    def dispatch(self, request, *args, **kwargs):
        return super().dispatch(request, *args, **kwargs)

    def get(self, request, *arg, **kwargs):
        system_title = SystemService.get_system_title()
        resp = render( request, login_page, {'system_title': system_title})
        return resp

    def post(self, request, *arg, **kwargs):
        username = request.POST.get('username', '')
        password = request.POST.get('password', '')
        address = login_throttle.client_address(request)
        user_agent = request.META.get('HTTP_USER_AGENT', '')[:300]

        locked = login_throttle.seconds_locked(username, address)
        if locked:
            self._log(request, 'fail', None, username, address, user_agent,
                      '잠금 상태 (남은 {}초)'.format(locked))
            return self._fail(request, 'LOCKED', _locked_message(locked))

        loginuser = authenticate(username=username, password=password)

        if loginuser is None:
            # authenticate() 는 비활성 계정에도 None을 준다. 비밀번호까지 맞은
            # 경우에만 '비활성'이라고 알린다 — 틀린 비밀번호에 알려주면
            # 계정 존재 여부를 흘리는 것이 된다.
            disabled = User.objects.filter(username=username, is_active=False).first()
            if disabled is not None and disabled.check_password(password):
                login_throttle.record_failure(username, address)
                self._log(request, 'fail', disabled, username, address, user_agent, '비활성 계정')
                return self._fail(request, 'INACTIVE', '사용할 수 없는 계정입니다.')

            just_locked = login_throttle.record_failure(username, address)
            self._log(request, 'fail', None, username, address, user_agent,
                      '아이디 또는 비밀번호 불일치')
            if just_locked:
                return self._fail(request, 'LOCKED', _locked_message(login_throttle.LOCK_SECONDS))
            return self._fail(request, 'ETC', '아이디 또는 비밀번호가 맞지 않습니다.')

        login_throttle.clear(username, address)
        login(self.request, loginuser)
        self._log(request, 'login', loginuser, username, address, user_agent, None)

        request.session.set_expiry(0)
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({'loginResult': 'OK', 'next': '/'}, safe=False,
                                json_dumps_params={'ensure_ascii': False})
        return HttpResponseRedirect('/')

    @staticmethod
    def _log(request, log_type, user, username, address, user_agent, reason):
        """로그인 기록이 실패해도 로그인 자체는 막지 않는다."""
        try:
            LoginLog.objects.create(Type=log_type, User=user, Username=username[:150],
                                    IPAddress=address, UserAgent=user_agent,
                                    FailReason=reason)
        except Exception as ex:
            LogWriter.add_dblog('error', 'AccountLoginView._log', ex)

    def _fail(self, request, code, message):
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({'loginResult': code, 'loginResultMsg': message},
                                json_dumps_params={'ensure_ascii': False})
        return render(request, login_page, {
            'loginResult': code,
            'loginResultMsg': message,
            'system_title': SystemService.get_system_title(),
        })


class AccountLogoutView(View):
    http_method_names = ['get']
    next = '/login'
    def get(self, request, *arg, **kwargs):
        user = request.user
        system_title = SystemService.get_system_title()

        data = { 
            'system_title': system_title,
        }

        if user.is_anonymous:
            return render(request, login_page,  data)

        try:
            LoginLog.objects.create(
                Type='logout', User=user, Username=user.username,
                IPAddress=login_throttle.client_address(request),
                UserAgent=request.META.get('HTTP_USER_AGENT', '')[:300])
        except Exception as ex:
            LogWriter.add_dblog('error', 'AccountLogoutView get loginlog.save', ex)
        # 기록이 실패해도 로그아웃은 한다
        logout(request)
        return render(request, login_page, data)
