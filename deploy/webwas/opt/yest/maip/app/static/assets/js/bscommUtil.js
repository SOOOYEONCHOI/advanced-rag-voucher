// 공통 UI 유틸 (BS5 layout 사용) — Notify(Toast)/modal·subModal
// ※ Alert·PopupDraggable 은 common.js 가 보유(중복 제거). 이 파일은 반드시 common.js '뒤에' 로드돼야 한다
//   (하단 modal=new PopupDraggable 가 로드시점에 common.js 정의를 참조).

'use strict';

// dialog/confirmDialog(ax5.ui.dialog)→Bootstrap Alert, toast(ax5.ui.toast)→Bootstrap Toast,
// mask/subMask(ax5.ui.mask)→제거(Alert 백드롭은 Bootstrap 자체 처리, 로딩은 common.js LoadingMask).
// modal/subModal은 Bootstrap PopupDraggable(하단 할당, 클래스 호이스팅 불가).
var modal;
var subModal;

// Ax5GridUtil(페이징 파라미터 헬퍼)·Ax5Grid(ax5.ui.grid.formatter)·Ax5Calendar(ax5.info)
// ·Ax5MediaViewer(ax5.ui.mediaViewer) 래퍼 제거 — 참조 0건(템플릿·JS)으로 사장됨.
// BS5 트랙은 WeZonGrid 사용.

// Date picker: ax5.ui.picker/ax5DatePicker 래퍼 제거 → 각 화면에서 daterangepicker 직접 호출.
//   $('#id').daterangepicker({ singleDatePicker: true, showDropdowns: true, drops: 'up', locale: { format: 'YYYY-MM-DD' } });
// (layout_page.html이 moment/daterangepicker(.js/.css)를 전역 로드)

// Bootstrap Alert/Confirm (ax5.ui.dialog 제거 → SF_MES 이식, 무아이콘).
// 공개 API 동결: alert(_title,_msg,_okCallback) / confirm(_title,_msg,_yesCallback,_noCallback).
// 백드롭/z-index 적층은 SF-Custom.css(.common-alert-modal/.common-alert-mask/popup-draggable-mask)가 처리.
var Notify = {
    _container: null,
    // 알림 호출부의 원문을 GUI 우선 다국어 문구로 바꿔 기존 Notify API를 그대로 유지한다.
    _resolveText: function (msg) {
        let message = (msg === undefined || msg === null) ? '' : String(msg);
        if (typeof i18n !== 'undefined' && i18n && typeof i18n.getGUIText === 'function') {
            message = i18n.getGUIText(message);
        }
        return message;
    },
    _hasBootstrapToast: function () {
        return typeof bootstrap !== 'undefined' && bootstrap && typeof bootstrap.Toast === 'function';
    },
    _ensureContainer: function () {
        if (this._container && document.body.contains(this._container)) {
            return this._container;
        }
        let el = document.getElementById('commonToastContainer');
        if (!el) {
            el = document.createElement('div');
            el.id = 'commonToastContainer';
            el.className = 'toast-container position-fixed bottom-0 end-0 p-3';
            el.style.zIndex = '1200';
            document.body.appendChild(el);
        }
        this._container = el;
        return el;
    },
    _removeEmptyContainer: function (container) {
        if (!container || container.querySelector('.toast')) {
            return;
        }
        container.remove();
        if (this._container === container) {
            this._container = null;
        }
    },
    init: function () {
        if (this._hasBootstrapToast()) {
            this._ensureContainer();
        }
    },
    _push: function (theme, msg, _func) {
        let message = this._resolveText(msg);
        let callbackCalled = false;
        let runCallbackOnce = function () {
            if (callbackCalled) {
                return;
            }
            callbackCalled = true;
            if (typeof _func === 'function') {
                _func();
            }
        };
        if (!this._hasBootstrapToast()) {
            try {
                window.alert(message);
            } finally {
                runCallbackOnce();
            }
            return;
        }
        let container = this._ensureContainer();
        let el = document.createElement('div');
        el.className = 'toast align-items-center text-bg-' + theme + ' border-0';
        el.setAttribute('role', 'alert');
        el.setAttribute('aria-live', 'assertive');
        el.setAttribute('aria-atomic', 'true');
        let body = document.createElement('div');
        body.className = 'toast-body';
        body.textContent = message;   // 서버·사용자 값이 섞인다 — HTML 로 해석하지 않는다
        let closeBtn = document.createElement('button');
        closeBtn.type = 'button';
        closeBtn.className = 'btn-close btn-close-white me-2 m-auto';
        closeBtn.setAttribute('data-bs-dismiss', 'toast');
        closeBtn.setAttribute('aria-label', 'Close');
        let flex = document.createElement('div');
        flex.className = 'd-flex';
        flex.appendChild(body);
        flex.appendChild(closeBtn);
        el.appendChild(flex);
        container.appendChild(el);
        let toast = bootstrap.Toast.getOrCreateInstance(el, { delay: 3000, autohide: true });
        let cleanup = () => {
            let instance = bootstrap.Toast.getInstance(el);
            if (instance) {
                instance.dispose();
            }
            el.remove();
            this._removeEmptyContainer(container);
            runCallbackOnce();
        };
        el.addEventListener('hidden.bs.toast', cleanup, { once: true });
        try {
            toast.show();
        } catch (error) {
            cleanup();
            throw error;
        }
    },
    success: function (msg) {
        this._push('success', msg);
    },
    successfnc: function (msg, _func) {
        this._push('success', msg, _func);
    },
    info: function (msg) {
        this._push('info', msg);
    },
    warn: function (msg) {
        this._push('warning', msg);
    },
    error: function (msg) {
        this._push('danger', msg);
    }
};

// ax5.ui.modal → Bootstrap 모달 기반으로 교체(SF_MES common.js 이식). ax5.ui.modal/mask 의존 제거.
// SF-Custom.css의 .modal[id^="popupDraggableModal_"] .popup-draggable-body{overflow-y:auto} +
// .modal-content{height:auto;max-height:calc(100vh-40px)} 규칙이 이 구조에 매칭되어 콘텐츠 초과 시 스크롤.

// 전역 modal/subModal: ax5.ui.modal 제거 → Bootstrap PopupDraggable 인스턴스.
// (parent.modal.close() / page 팝업 / i18n 라벨 팝업 등 기존 계약 유지)
modal = new PopupDraggable('');
subModal = new PopupDraggable('');

$(document).ready(function () {
    Alert.init();
    Notify.init();
});
