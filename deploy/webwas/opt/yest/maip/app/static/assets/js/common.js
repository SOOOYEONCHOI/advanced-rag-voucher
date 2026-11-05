// 시스템 공통으로 사용되는 function script (default layout 사용)
// 공통콤보, validatin 등

'use strict';


var JQuery = {
    extends: function () {
        $.rest = function (url, data, callback, type, method) {
            if ($.isFunction(data)) {
                type = type || callback,
                    callback = data,
                    data = {}
            }

            return $.ajax({
                url: url,
                type: method,
                success: callback,
                data: data,
                contentType: type,
                beforeSend: function (xmlHttpRequest) {
                    xmlHttpRequest.setRequestHeader('AJAX', 'true'); // ajax 호출을  header에 기록
                }
            });
        }

        $.put = function (url, data, callback, type) {
            return $.rest(url, data, callback, type, 'PUT');
        }
        $.delete = function (url, data, callback, type) {
            return $.rest(url, data, callback, type, 'DELETE');
        }

        $.fn.serializeObject = function () {
            var object = {};
            var array = this.serializeArray();

            $.each(array, function () {
                if (object[this.name] !== undefined) {
                    if (!object[this.name].push) {
                        object[this.name] = [object[this.name]];
                    }
                    object[this.name].push(this.value || '');
                } else {
                    object[this.name] = this.value || '';
                }
            });
            return object;
        };
    }
};

var Ajax = {
    showSplash: function () {
        let dom = document.getElementById("loadingSplash");
        if (dom)
            dom.style.display = "block";
    },
    hideSplash: function () {
        let dom = document.getElementById("loadingSplash");
        if (dom)
            dom.style.display = "none";
    },

    defaults: {
        progressBarText: 'Loading...'
    },
    setProgressBarText: function (text) {
        Ajax.defaults.progressBarText = text;
    },
    enableProgressBar: function () {
        //let mask = new ax5.ui.mask();

        //mask.setConfig({
        //   // target: $('body', document).get(0)
        //    target: document.getElementById("my_loading")

        //});

        $(document).ajaxStart(function () {
            //mask.open({
            //  content: '<h1><img src="/static/img/loading.svg"> ' + Ajax.defaults.progressBarText + '</h1>'
            //});
        });

        $(document).ajaxStop(function () {
            setTimeout(function () {
                //mask.close();
            }, 100);
        });


    },
    enableErrorHandler: function () {
        $(document).ajaxError(function (evnet, xhr, settings, thrownError) {
            //Alert.alert('', JSON.parse(xhr.responseText).message);
            //var response = JSON.parse(xhr.responseText);
            //$.alert(response.message);
        });
    }
};

var Utils = {
    decodingTag: function (str) {
        if (str !== null) {
            str = str.replace(/&lt;/g, "<").replace(/&gt;/g, ">").replace(/&quot;/g, "\"").replace(/&#39;/g, "\'")
                .replace(/&amp;gt;/g, "&gt;").replace(/&amp;nbsp;/g, "&nbsp;").replace(/&amp;amp;/g, "&").replace(/&amp;/g, "&");
        }
        return str;
    },
    decodingHTMLTag: function (str) {
        if (str !== null && typeof str === 'string') {
            str = str.replace(/&lt;/g, "<").replace(/&gt;/g, ">").replace(/&amp;/g, "&");
        }
        return str;
    },
    fnImagePreview: function (_noticeContent) {
        // 내용중 이미지 있을경우 클릭하여 원본크기로 팝업
        $(_noticeContent).attr('title', '클릭시 이미지원본보기');
        $(_noticeContent).on('click', function () {
            var imgCommonPreview = new Image();
            imgCommonPreview.src = $(this).attr('src');
            var scrollsize = 17;
            var swidth = screen.width - 10;
            var sheight = screen.height - 300;
            var wsize = imgCommonPreview.width
            var hsize = imgCommonPreview.height;
            if (wsize < 50) wsize = 50; // 가로 최소 크기 
            if (hsize < 50) hsize = 50; // 세로 최소 크기 
            if (wsize > swidth) wsize = swidth; // 가로 최대 크기 
            if (hsize > sheight) hsize = sheight; // 세로 최대 크기
            // 세로가 최대크기를 초과한경우 세로스크롤바 자리 확보 
            if ((wsize < swidth - scrollsize) && hsize >= sheight) wsize += scrollsize;
            // 가로가 최대크기를 초과한경우 가로스크롤바 자리 확보 
            if ((hsize < sheight - scrollsize) && wsize >= swidth) hsize += scrollsize;
            // 듀얼 모니터에서 팝업 가운데 정렬하기 
            var mtWidth = document.body.clientWidth;
            // 현재 브라우저가 있는 모니터의 화면 폭 사이즈 
            var mtHeight = document.body.clientHeight;
            // 현재 브라우저가 있는 모니터의 화면 높이 사이즈 
            var scX = window.screenLeft;
            // 현재 브라우저의 x 좌표(모니터 두 대를 합한 총 위치 기준) 
            var scY = window.screenTop;
            // 현재 브라우저의 y 좌표(모니터 두 대를 합한 총 위치 기준) 
            var popX = scX + (mtWidth - wsize) / 2 - 50;
            // 팝업 창을 띄울 x 위치 지정(모니터 두 대를 합한 총 위치 기준) 
            var popY = scY + (mtHeight - hsize) / 2 - 50;
            // 팝업 창을 띄울 y 위치 지정(모니터 두 대를 합한 총 위치 기준)
            var imageWin = window.open("", "", "top=" + 10 + ",left=" + popX + ",width=" + wsize + ",height=" + hsize + ",scrollbars=yes,resizable=yes,status=no");
            imageWin.document.write("<html><title>이미지 원본보기</title><body style='margin:0;cursor:pointer;' title='Close' onclick='window.close()'>");
            imageWin.document.write("<img src='" + imgCommonPreview.src + "'>");
            imageWin.document.write("</body></html>");
        });
    },
    findMainTabs: function () {
        // 메인화면의 nthTabs 찾기. 부모에서 찾아야 함. 이게 의미가 있나?
        let $nthTabs = $('#main-tabs').nthTabs();
        return $nthTabs
    },



};

class GuiBookmarkToggle {
    constructor() {
        this.guiCode = '';
        this.$favoriteLinks = $();
    }

    getGuiCode() {
        if (!window.gui || !gui.gui_code) {
            return '';
        }
        return String(gui.gui_code).trim();
    }

    findFavoriteLinks() {
        return $('.header-title a').filter(function () {
            return $(this).find('i.uil-favorite').length > 0;
        });
    }

    applyState(isBookmarked) {
        let $icons = this.$favoriteLinks.find('i.uil-favorite');
        if (!$icons.length) {
            return;
        }

        $icons
            .toggleClass('favorite-on', !!isBookmarked)
            .toggleClass('favorite-off', !isBookmarked);
    }

    loadBookmarkState(onLoaded) {
        if (!window.AjaxUtil || typeof AjaxUtil.getAsyncData !== 'function') {
            onLoaded(false);
            return;
        }

        AjaxUtil.getAsyncData('/api/system/bookmark', {}, (bookmarks) => {
            onLoaded(Array.isArray(bookmarks) && bookmarks.some((item) => {
                return item && String(item.code || '').trim() === this.guiCode;
            }));
        }, () => onLoaded(false));
    }

    bindEvents() {
        let _this = this;
        this.$favoriteLinks.off('click.guiBookmark').on('click.guiBookmark', function (e) {
            e.preventDefault();
            e.stopPropagation();
            if (typeof e.stopImmediatePropagation === 'function') {
                e.stopImmediatePropagation();
            }

            let isCurrentlyOn = $(this).find('i.uil-favorite').hasClass('favorite-on');
            let nextState = !isCurrentlyOn;
            _this.saveBookmark(nextState);
            _this.applyState(nextState);
            return false;
        });
    }

    saveBookmark(isBookmarked) {
        let csrf = $('[name=csrfmiddlewaretoken]').val();
        let paramData = {
            menucode: this.guiCode,
            isbookmark: isBookmarked,
            csrfmiddlewaretoken: csrf
        };

        $.post('/api/system/bookmark?action=save', paramData).fail(function (e) {
            console.log('GuiBookmarkToggle.saveBookmark error', e && e.message ? e.message : e);
        });
    }

    init() {
        try {
            this.guiCode = this.getGuiCode();
            console.log('GuiBookmarkToggle guiCode:', this.guiCode);
            if (!this.guiCode) {
                return;
            }

            this.$favoriteLinks = this.findFavoriteLinks();
            console.log('GuiBookmarkToggle links found:', this.$favoriteLinks.length);
            if (!this.$favoriteLinks.length) {
                return;
            }

            this.$favoriteLinks.attr('href', 'javascript:void(0);');
            this.loadBookmarkState((isOn) => this.applyState(isOn));
            this.bindEvents();
            console.log('GuiBookmarkToggle bound OK');
        } catch (error) {
            console.log('GuiBookmarkToggle.init error', error);
        }
    }
}

window.GuiBookmarkToggle = GuiBookmarkToggle;

class PopupDraggable {
    // close callback function 추가
    constructor(title_str) {
        this.title = title_str || '';
        this.$modal = null;
        this.$contentArea = null;
        this.bsModal = null;
        this.$content = null;
        this._backdropElement = null;
        this._isOpen = false;
        this.closeCallback = null;
        this.modal = {
            close: () => this.close(),
            hide: () => this.close()
        };
    }

    // 팝업 제목을 현재 GUI 문구로 번역한 뒤 HTML entity를 화면 표시 문자로 복원한다.
    _resolveTitle(title) {
        let value = (title === undefined || title === null) ? '' : String(title);
        if (typeof i18n !== 'undefined' && i18n && typeof i18n.getGUIText === 'function') {
            value = i18n.getGUIText(value);
        }
        if (typeof Utils !== 'undefined' && Utils && typeof Utils.decodingHTMLTag === 'function') {
            value = Utils.decodingHTMLTag(value);
        }
        return value;
    }

    static increaseMaskCount() {
        PopupDraggable._openCount = (PopupDraggable._openCount || 0) + 1;
        $('body').addClass('popup-draggable-mask');
    }

    static decreaseMaskCount() {
        PopupDraggable._openCount = Math.max((PopupDraggable._openCount || 0) - 1, 0);
        if (PopupDraggable._openCount === 0) {
            $('body').removeClass('popup-draggable-mask');
        }
    }

    _detachContent() {
        if (this.$content && this.$content.length) {
            this.$content.detach();
        }
    }

    _removeOwnedBackdrop() {
        if (this._backdropElement) {
            this._backdropElement.remove();
            this._backdropElement = null;
        }
    }

    _releaseMask() {
        if (!this._isOpen) {
            return;
        }

        this._isOpen = false;
        PopupDraggable.decreaseMaskCount();
    }

    _showModal() {
        if (this.bsModal) {
            let existingBackdrops = new Set(document.querySelectorAll('.modal-backdrop'));
            this.bsModal.show();
            let addedBackdrops = Array.from(document.querySelectorAll('.modal-backdrop'))
                .filter(function (element) {
                    return !existingBackdrops.has(element);
                });
            this._backdropElement = addedBackdrops.length
                ? addedBackdrops[addedBackdrops.length - 1]
                : null;
            return;
        }

        if (this.$modal) {
            this.$modal.show();
        }
    }

    _bindDrag() {
        if (!this.$modal || !this.$modal.length) {
            return;
        }

        let $dialog = this.$modal.find('.modal-dialog');
        let $header = this.$modal.find('.modal-header');
        if (!$dialog.length || !$header.length) {
            return;
        }

        let dragging = false;
        let startX = 0;
        let startY = 0;
        let originLeft = 0;
        let originTop = 0;

        $header.css('cursor', 'move');

        let stopDrag = function () {
            dragging = false;
            $(document).off('mousemove.popupDraggableDrag mouseup.popupDraggableDrag');
        };

        $header.off('mousedown.popupDraggableDrag').on('mousedown.popupDraggableDrag', function (e) {
            if ($(e.target).closest('.btn-close').length) {
                return;
            }

            let dialogEl = $dialog.get(0);
            if (!dialogEl) {
                return;
            }

            let rect = dialogEl.getBoundingClientRect();
            dragging = true;
            startX = e.clientX;
            startY = e.clientY;
            originLeft = rect.left;
            originTop = rect.top;

            $dialog.removeClass('modal-dialog-centered').css({
                position: 'fixed',
                margin: 0,
                left: originLeft + 'px',
                top: originTop + 'px',
                transform: 'none'
            });

            $(document).off('mousemove.popupDraggableDrag').on('mousemove.popupDraggableDrag', function (evt) {
                if (!dragging) {
                    return;
                }

                let nextLeft = originLeft + (evt.clientX - startX);
                let nextTop = originTop + (evt.clientY - startY);
                let maxLeft = Math.max(0, $(window).width() - $dialog.outerWidth());
                let maxTop = Math.max(0, $(window).height() - $dialog.outerHeight());

                nextLeft = Math.min(Math.max(0, nextLeft), maxLeft);
                nextTop = Math.min(Math.max(0, nextTop), maxTop);

                $dialog.css({
                    left: nextLeft + 'px',
                    top: nextTop + 'px'
                });
            });

            $(document).off('mouseup.popupDraggableDrag').on('mouseup.popupDraggableDrag', function () {
                stopDrag();
            });

            e.preventDefault();
        });

        this.$modal.off('hidden.bs.modal.popupDraggableDrag').on('hidden.bs.modal.popupDraggableDrag', function () {
            stopDrag();
        });
    }

    _buildModal(width, height) {
        if (this.$modal && this.$modal.length) {
            // 전역 popup 인스턴스를 close 없이 다시 열어도 이전 Bootstrap 상태를 남기지 않는다.
            this._detachContent();
            if (this.bsModal) {
                try {
                    this.bsModal.dispose();
                } catch (e) { }
                this.bsModal = null;
            }
            this.$modal.remove();
            this._removeOwnedBackdrop();
            this._releaseMask();
            this.$modal = null;
            this.$contentArea = null;
        }

        PopupDraggable._seq = (PopupDraggable._seq || 0) + 1;
        let modalId = 'popupDraggableModal_' + PopupDraggable._seq;
        let modalTitle = this._resolveTitle(this.title);
        let html = '' +
            '<div class="modal" id="' + modalId + '" tabindex="-1" aria-hidden="true">' +
            '  <div class="modal-dialog modal-dialog-centered" role="document">' +
            '    <div class="modal-content">' +
            '      <div class="modal-header">' +
            '        <h5 class="modal-title">' + modalTitle + '</h5>' +
            '        <button type="button" class="btn-close btn-close-white popup-draggable-close" aria-label="Close"></button>' +
            '      </div>' +
            '      <div class="modal-body p-0 popup-draggable-body"></div>' +
            '    </div>' +
            '  </div>' +
            '</div>';

        $('body').append(html);
        this.$modal = $('#' + modalId);
        this.$contentArea = this.$modal.find('.popup-draggable-body');

        let parsedWidth = parseInt(width, 10);
        if (!Number.isNaN(parsedWidth) && parsedWidth > 0) {
            this.$modal.find('.modal-dialog').css({
                'max-width': parsedWidth + 'px',
                'width': '100%'
            });
        }

        let parsedHeight = parseInt(height, 10);
        if (!Number.isNaN(parsedHeight) && parsedHeight > 0) {
            // SF-Custom.css의 height:auto!important보다 caller의 고정 높이를 우선한다.
            let modalContent = this.$modal.find('.modal-content').get(0);
            if (modalContent) {
                modalContent.style.setProperty('height', parsedHeight + 'px', 'important');
                modalContent.style.setProperty('display', 'flex');
                modalContent.style.setProperty('flex-direction', 'column');
            }
            this.$contentArea.css({
                'flex': '1 1 auto',
                'min-height': 0,
                'overflow-y': 'auto'
            });
        }

        let _this = this;
        this.$modal.find('.popup-draggable-close').off('click.popupDraggable').on('click.popupDraggable', function (e) {
            e.preventDefault();
            _this.close();
        });

        let modalElement = this.$modal.get(0);
        // Esc 는 Bootstrap 이 바로 닫아 화면이 덮어쓴 close()(저장 안 한 내용 확인)를 건너뛴다.
        // close() 가 시작한 닫힘이 아니면 멈추고 close() 를 부른다 — 덮어쓰지 않은 팝업은 그대로 닫힌다
        this.$modal.off('hide.bs.modal.popupDraggable').on('hide.bs.modal.popupDraggable', function (e) {
            if (_this._closing || e.target !== modalElement) {
                return;
            }
            e.preventDefault();
            _this.close();
        });
        this.$modal.off('hidden.bs.modal.popupDraggable').on('hidden.bs.modal.popupDraggable', function () {
            if (!_this.$modal || _this.$modal.get(0) !== modalElement) {
                return;
            }

            _this._detachContent();
            _this._removeOwnedBackdrop();

            if (_this.$modal) {
                _this.$modal.remove();
            }
            _this.$modal = null;
            _this.$contentArea = null;
            _this.bsModal = null;
            _this._releaseMask();

            let callback = _this.closeCallback;
            _this.closeCallback = null;
            if (callback) {
                callback();
            }
        });

        if (typeof bootstrap !== 'undefined' && bootstrap && typeof bootstrap.Modal === 'function') {
            this.bsModal = bootstrap.Modal.getOrCreateInstance(this.$modal.get(0), {
                backdrop: 'static',
                // Esc 로 닫는다. 백드롭 클릭은 막아 둔다 — 입력 중이던 폼이
                // 실수로 사라지는 것과 의도적인 Esc 는 다르다.
                keyboard: true
            });
            this.modal = {
                close: () => this.close(),
                hide: () => this.close()
            };
        } else {
            this.bsModal = null;
            this.modal = {
                close: () => this.close(),
                hide: () => this.close()
            };
        }

        this._bindDrag();
    }

    open({ width, height, $content, iframe, title } = {}, fnCloseCallback = null) {
        let _this = this;
        // 제목은 원래 생성자 인자다. 전역 modal 처럼 빈 제목으로 만들어 둔
        // 인스턴스를 재사용하는 쪽에서 열 때마다 제목을 줄 수 있게 한다.
        // 넘기지 않으면 생성자에서 받은 제목을 그대로 쓴다(기존 호출자 무영향).
        if (title !== undefined) this.title = title;
        this._buildModal(width, height);
        _this.closeCallback = fnCloseCallback;
        this.$content = $content || null;
        PopupDraggable.increaseMaskCount();
        this._isOpen = true;

        // 기존 AX5 iframe payload의 GET/POST·param 계약을 Bootstrap modal에서 유지한다.
        if (iframe && iframe.url) {
            let frameName = this.$modal.attr('id') + '-frame';
            let $frame = $('<iframe>', {
                name: frameName,
                frameborder: '0',
                scrolling: 'auto'
            }).css({
                width: '100%',
                height: '100%',
                border: '0',
                display: 'block'
            });
            $frame.on('load.popupDraggable', function () {
                try {
                    let frameDocument = this.contentDocument;
                    if (!frameDocument) {
                        return;
                    }
                    frameDocument.querySelectorAll(
                        '#modal-close[data-bs-dismiss="modal"], ' +
                        '#modal-close-button[data-bs-dismiss="modal"]'
                    ).forEach(function (button) {
                        button.removeAttribute('data-bs-dismiss');
                    });
                } catch (e) {
                    // Cross-origin iframe은 child document를 변경하지 않고 기존 계약대로 연다.
                }
            });
            this.$contentArea
                .css({ flex: '1 1 auto', 'min-height': 0, overflow: 'hidden', padding: 0 })
                .empty()
                .append($frame);

            let method = (iframe.method || 'get').toLowerCase();
            let param = iframe.param || '';
            if (method === 'post') {
                let $form = $('<form>', {
                    method: 'post',
                    action: iframe.url,
                    target: frameName
                }).css('display', 'none');
                param.split('&').forEach(function (pair) {
                    if (!pair) {
                        return;
                    }
                    let separatorIndex = pair.indexOf('=');
                    let name = separatorIndex >= 0 ? pair.slice(0, separatorIndex) : pair;
                    let value = separatorIndex >= 0 ? pair.slice(separatorIndex + 1) : '';
                    $form.append($('<input>', {
                        type: 'hidden',
                        name: name,
                        value: value
                    }));
                });
                $('body').append($form);
                this._showModal();
                $form.trigger('submit');
                $form.remove();
            } else {
                let separator = iframe.url.indexOf('?') >= 0 ? '&' : '?';
                $frame.attr('src', iframe.url + separator + param);
                this._showModal();
            }

            return this.modal;
        }

        // 기존 inline content mode의 label, permission, close callback 계약을 유지한다.
        this.$contentArea.empty().append($content);

        if ($content) {
            i18n.applyContentLabel($content);
            yullinAuth.removeWriteButton($content);

            $content.find('#modal-close, #modal-close2, #modal-close-x, #modal-close-button')
                .off('click.popupDraggable')
                .on('click.popupDraggable', function (e) {
                    e.preventDefault();
                    _this.close();
                });
        }

        this._showModal();

        return this.modal;
    }

    close() {
        if (this.bsModal) {
            // hide.bs.modal 은 hide() 안에서 바로 불린다 — 그동안만 close() 가 시작한 닫힘이다
            this._closing = true;
            try {
                this.bsModal.hide();
            } finally {
                this._closing = false;
            }
            return;
        }

        if (!this.$modal || !this.$modal.length) {
            return;
        }

        this._detachContent();
        this.$modal.remove();
        this._removeOwnedBackdrop();
        this.$modal = null;
        this.$contentArea = null;
        this._releaseMask();

        let callback = this.closeCallback;
        this.closeCallback = null;
        if (callback) {
            callback();
        }
    }
}

var Alert = {
    _initialized: false,
    _alertModal: null,
    _confirmModal: null,
    _alertOkCallback: null,
    _confirmYesCallback: null,
    _confirmNoCallback: null,
    _resolveText: function (text, defaultText) {
        let value = text;
        if (value === undefined || value === null || value === '') {
            value = defaultText || '';
        }
        if (typeof i18n !== 'undefined' && i18n && typeof i18n.getCommonText === 'function') {
            value = i18n.getCommonText(value);
        }
        if (typeof Utils !== 'undefined' && Utils && typeof Utils.decodingHTMLTag === 'function') {
            value = Utils.decodingHTMLTag(value);
        }
        return value;
    },
    // Alert 메시지는 호출부를 바꾸지 않아도 GUI → common → 안전한 공백 variant 순서로 번역한다.
    _resolveGUIText: function (text, defaultText) {
        let value = text;
        if (value === undefined || value === null || value === '') {
            value = defaultText || '';
        }
        if (typeof i18n !== 'undefined' && i18n && typeof i18n.getGUIText === 'function') {
            value = i18n.getGUIText(value);
        }
        if (typeof Utils !== 'undefined' && Utils && typeof Utils.decodingHTMLTag === 'function') {
            value = Utils.decodingHTMLTag(value);
        }
        return value;
    },
    // 빈 제목은 기존 common 기본값을 유지하고, 명시한 제목만 GUI 문구로 해석한다.
    _resolveTitle: function (text, defaultText) {
        if (text === undefined || text === null || text === '') {
            return this._resolveText(defaultText || '', '');
        }
        return this._resolveGUIText(text, '');
    },
    _formatMessage: function (message) {
        if (message === undefined || message === null) {
            return '';
        }
        // 메시지에는 파일명·라벨 이름 같은 사용자 값이 섞인다. 글자로 바꾼 뒤 줄바꿈만 <br> 로 둔다.
        return $('<div>').text(String(message)).html().replace(/\r\n|\r|\n/g, '<br>');
    },
    _ensureModalElements: function () {
        if ($('#commonAlertModal').length > 0 && $('#commonConfirmModal').length > 0) {
            return;
        }

        let modalHtml = '' +
            '<div class="modal common-alert-modal" id="commonAlertModal" tabindex="-1" role="dialog" aria-hidden="true" style="display:none;">' +
            '  <div class="modal-dialog modal-dialog-centered modal-sm" role="document">' +
            '    <div class="modal-content">' +
            '      <div class="modal-header">' +
            '        <h5 class="modal-title" id="commonAlertModalTitle">정보</h5>' +
            '        <button type="button" class="btn-close btn-close-white" id="commonAlertModalClose" aria-label="Close"></button>' +
            '      </div>' +
            '      <div class="modal-body p-4">' +
            '        <div class="text-center">' +
            '          <i class="ri-information-line h1 text-info"></i>' +
            '          <p class="mt-3 mb-3" id="commonAlertModalBody"></p>' +
            '          <button type="button" class="btn btn-info my-2" id="commonAlertModalOk">확인</button>' +
            '        </div>' +
            '      </div>' +
            '    </div>' +
            '  </div>' +
            '</div>' +
            '<div class="modal common-alert-modal" id="commonConfirmModal" tabindex="-1" role="dialog" aria-hidden="true" style="display:none;">' +
            '  <div class="modal-dialog modal-dialog-centered modal-sm" role="document">' +
            '    <div class="modal-content">' +
            '      <div class="modal-header">' +
            '        <h5 class="modal-title" id="commonConfirmModalTitle">확인</h5>' +
            '        <button type="button" class="btn-close btn-close-white" id="commonConfirmModalClose" aria-label="Close"></button>' +
            '      </div>' +
            '      <div class="modal-body p-4">' +
            '        <div class="text-center">' +
            '          <i class="ri-alert-line h1 text-warning"></i>' +
            '          <p class="mt-3 mb-4" id="commonConfirmModalBody"></p>' +
            '          <div class="d-flex justify-content-center gap-2">' +
            // 푸터는 보조 → 주요 순서다.
            '            <button type="button" class="btn btn-light" id="commonConfirmModalCancel">취소</button>' +
            '            <button type="button" class="btn btn-primary" id="commonConfirmModalOk">확인</button>' +
            '          </div>' +
            '        </div>' +
            '      </div>' +
            '    </div>' +
            '  </div>' +
            '</div>';

        $('body').append(modalHtml);
    },
    _setButtonText: function () {
        $('#commonAlertModalOk').text(this._resolveText('확인', '확인'));
        $('#commonConfirmModalCancel').text(this._resolveText('취소', '취소'));
        $('#commonConfirmModalOk').text(this._resolveText('확인', '확인'));
    },
    init: function () {
        if (this._initialized) {
            this._setButtonText();
            return;
        }

        if (typeof bootstrap === 'undefined' || !bootstrap || typeof bootstrap.Modal !== 'function') {
            this._initialized = true;
            return;
        }

        this._ensureModalElements();
        this._setButtonText();

        let alertElement = document.getElementById('commonAlertModal');
        let confirmElement = document.getElementById('commonConfirmModal');

        // Esc 로 닫는다. 백드롭 클릭은 막아 둔다(backdrop: 'static').
        this._alertModal = bootstrap.Modal.getOrCreateInstance(alertElement, {
            backdrop: 'static',
            keyboard: true
        });
        this._confirmModal = bootstrap.Modal.getOrCreateInstance(confirmElement, {
            backdrop: 'static',
            keyboard: true
        });

        $('#commonAlertModal')
            .off('hidden.bs.modal.commonAlertBackdrop')
            .on('hidden.bs.modal.commonAlertBackdrop', function () {
                $('body').removeClass('common-alert-mask');
            });
        $('#commonConfirmModal')
            .off('hidden.bs.modal.commonAlertBackdrop')
            .on('hidden.bs.modal.commonAlertBackdrop', function () {
                $('body').removeClass('common-alert-mask');
            });

        let _this = this;
        $('#commonAlertModalOk').off('click.commonAlert').on('click.commonAlert', function () {
            let callback = _this._alertOkCallback;
            _this._alertOkCallback = null;
            _this._alertModal.hide();
            if (typeof callback === 'function') {
                callback();
            }
        });
        $('#commonAlertModalClose').off('click.commonAlert').on('click.commonAlert', function () {
            _this._alertOkCallback = null;
            _this._alertModal.hide();
        });

        $('#commonConfirmModalOk').off('click.commonAlert').on('click.commonAlert', function () {
            let callback = _this._confirmYesCallback;
            _this._confirmYesCallback = null;
            _this._confirmNoCallback = null;
            _this._confirmModal.hide();
            if (typeof callback === 'function') {
                callback();
            }
        });
        $('#commonConfirmModalClose').off('click.commonAlert').on('click.commonAlert', function () {
            let callback = _this._confirmNoCallback;
            _this._confirmYesCallback = null;
            _this._confirmNoCallback = null;
            _this._confirmModal.hide();
            if (typeof callback === 'function') {
                callback();
            }
        });

        $('#commonConfirmModalCancel').off('click.commonAlert').on('click.commonAlert', function () {
            let callback = _this._confirmNoCallback;
            _this._confirmYesCallback = null;
            _this._confirmNoCallback = null;
            _this._confirmModal.hide();
            if (typeof callback === 'function') {
                callback();
            }
        });

        this._initialized = true;
    },
    alert: function (_title, _msg, _okCallback) {
        let title = this._resolveTitle(_title, '정보');
        let message = this._resolveGUIText(_msg, '');

        if (typeof bootstrap === 'undefined' || !bootstrap || typeof bootstrap.Modal !== 'function') {
            window.alert(message);
            if (typeof _okCallback === 'function') {
                _okCallback();
            }
            return;
        }

        this.init();
        $('#commonAlertModalTitle').text(title);
        $('#commonAlertModalBody').html(this._formatMessage(message));
        this._alertOkCallback = (typeof _okCallback === 'function') ? _okCallback : null;
        $('body').addClass('common-alert-mask');
        this._alertModal.show();
    },
    confirm: function (_title, _msg, _yesCallback, _noCallback) {
        let title = this._resolveTitle(_title, '확인');
        let message = this._resolveGUIText(_msg, '');

        if (typeof bootstrap === 'undefined' || !bootstrap || typeof bootstrap.Modal !== 'function') {
            let result = window.confirm(message);
            if (result) {
                if (typeof _yesCallback === 'function') {
                    _yesCallback();
                }
            } else if (typeof _noCallback === 'function') {
                _noCallback();
            }
            return;
        }

        this.init();
        $('#commonConfirmModalTitle').text(title);
        $('#commonConfirmModalBody').html(this._formatMessage(message));
        this._confirmYesCallback = (typeof _yesCallback === 'function') ? _yesCallback : null;
        this._confirmNoCallback = (typeof _noCallback === 'function') ? _noCallback : null;
        $('body').addClass('common-alert-mask');
        this._confirmModal.show();
    }
};

var CommonUtil = {
    onkeyupEnter: function (form) {
        if (window.event.keyCode == 13) {
            $(form).submit();
        }
    },
    onchangeCombobox: function (value, callback) {
        if (value != '') {
            $('#searchForm').submit();
            if (typeof callback == 'function') {
                callback();
            }
        }
    },
    getTimeStamp: function () {
        var d = new Date();
        var s =
            d.getFullYear() + '-' +
            d.getMonth() + 1 + '-' +
            d.getDate() + '_' +
            d.getHours() +
            d.getMinutes() +
            d.getSeconds();
        return s;
    },
    addDays: function (date, days) {
        var result = new Date(date);
        result.setDate(result.getDate() + days);
        return result;
    },
    getYYMMDD: function (_diff) {
        _diff = _diff || 0;
        var d = new Date();
        d.setDate(d.getDate() + _diff);
        var m = d.getMonth() + 1;
        var day = d.getDate();
        if (m < 10) {
            m = "0" + m;
        }
        if (day < 10) {
            day = "0" + day;
        }
        var str = d.getFullYear() + '-' + m + '-' + day;

        return str.substr(2, str.length - 2);
    },
    getYYYYMMDD: function (_diff) {
        _diff = _diff || 0;
        var d = new Date();
        d.setDate(d.getDate() + _diff);
        var m = d.getMonth() + 1;
        var day = d.getDate();
        if (m < 10) {
            m = "0" + m;
        }
        if (day < 10) {
            day = "0" + day;
        }
        var str = d.getFullYear() + '-' + m + '-' + day;
        return str;
    },
    formatYYYYMMDD: function (p_date) {
        let m = p_date.getMonth() + 1;
        let day = p_date.getDate();
        if (m < 10) {
            m = "0" + m;
        }
        if (day < 10) {
            day = "0" + day;
        }
        var str = p_date.getFullYear() + '-' + m + '-' + day;
        return str;
    },
    //from to 숫자 입력값 유효성 체크(title 입력 필요)
    checkValidNumberRange: function (from, to) {
        if (DecimalUtil.gt(from.val() || 0, to.val() || 0)) {
            let msg = from.attr("title") + ' 가 ' + to.attr("title") + ' 보다 높습니다'.
                //Alert.alert('', getMessage('valid.msg.validrange',[from.attr("title"),to.attr("title")]));
                Alert.alert('', msg);
            return false;
        }
        return true;
    },
    // 검색조건에 필수 여부 확인(title 입력 필요)
    isRequired: function (objs) {
        if (objs !== null && $.type(objs) === 'array') {
            $.each(objs, function (i) {
                if (objs[i].val() == "") {
                    Alert.alert('', objs[i].attr("title") + "을(를) 입력해 주십시오.");
                    //Alert.alert('', objs[i].attr("title")+getMessage('valid.msg.M000000041'));
                    return false;
                }
            });
        }
        return true;
    },
    CommaNumber: function (value) {
        // 수치값인 경우 3자리 기준으로 콤마를 넣어서 출력한다. 
        // 12345678.2345 -> 12,345,678.2345
        if (value == null)
            return null;
        let value2 = DecimalUtil.parse(value);

        //if ( Number.isNaN(value2) ) return value;

        if (!value2) return value;
        if (value2.isZero()) return 0;

        let reg = /(^[+-]?\d+)(\d{3})/;
        let n = value2.toFixed();

        while (reg.test(n)) n = n.replace(reg, '$1' + ',' + '$2');

        return n;
    },  // CommaNumber
    removeNullFromObject: function (dic) {
        // object의 value가 null 값인 경우 ''로 치환해 준다. 화면에 null로 표시되는 것을 방지하기 위해 사용.
        if (Array.isArray(dic)) {
            for (let obj of dic) {
                CommonUtil.removeNullFromObject(obj);
            }
        }
        for (const [key, value] of Object.entries(dic)) {
            if (Array.isArray(value))
                CommonUtil.removeNullFromObject(value);
            else if (value === null || value === undefined)
                dic[key] = '';
            else if (value.constructor.name === 'Object')
                CommonUtil.removeNullFromObject(value);
        }
        //return dic;
    },  // removeNullFromObject
    getParameters: function (paramName) {
        // 리턴값을 위한 변수 선언
        var returnValue;
        // 현재 URL 가져오기
        var url = location.href;
        // get 파라미터 값을 가져올 수 있는 ? 를 기점으로 slice 한 후 split 으로 나눔
        var parameters = (url.slice(url.indexOf('?') + 1, url.length)).split('&');

        // 나누어진 값의 비교를 통해 paramName 으로 요청된 데이터의 값만 return
        for (var i = 0; i < parameters.length; i++) {
            var varName = parameters[i].split('=')[0];
            if (varName.toUpperCase() == paramName.toUpperCase()) {
                returnValue = parameters[i].split('=')[1];
                return decodeURIComponent(returnValue);
            }
        }
    },
    openWindowPost: function (url, frm, options) {
        if (!options) {
            options = {};
        }

        if (!options.width) {
            options.width = 1024;
        }
        if (!options.height) {
            options.height = 768;
        }
        if (!options.layout) {
            options.layout = 'resizable=no, toolbar=no, menubar=no, location=no, status=no, scrollbars=yes';
        }
        if (!options.winname) {
            options.winname = '__window__' + Math.floor((Math.random() * 1000000) + 1);
        }

        var dualScreenLeft = window.screenLeft != undefined ? window.screenLeft : screen.left;
        var dualScreenTop = window.screenTop != undefined ? window.screenTop : screen.top;
        var screenWidth = window.innerWidth ? window.innerWidth : document.documentElement.clientWidth ? document.documentElement.clientWidth : screen.width;
        var screenHeight = window.innerHeight ? window.innerHeight : document.documentElement.clientHeight ? document.documentElement.clientHeight : screen.height;
        if (!options.left) {
            options.left = (screenWidth / 2) - (options.width / 2) + dualScreenLeft;
        }
        if (!options.top) {
            options.top = (screenHeight / 2) - (options.height / 2);
        }

        if (options.params) {
            var params = '';
            $.each(options.params, function (name, value) {
                if (params != '') {
                    params += '&';
                }
                params += name + '=' + value;

            });
            url += params ? '?' + params : '';
        }
        window.open('', options.winname, 'top=' + options.top + ', left=' + options.left + ', width=' + options.width + ', height=' + options.height + ', ' + options.layout);
        $('#' + frm).attr('action', url);
        $('#' + frm).attr('target', options.winname);
        $('#' + frm).submit();
        return false;
    },
    openWindow: function (url, options) {
        if (!options) {
            options = {};
        }

        if (!options.width) {
            options.width = 1024;
        }
        if (!options.height) {
            options.height = 768;
        }
        if (!options.layout) {
            options.layout = 'resizable=no, toolbar=no, menubar=no, location=no, status=no, scrollbars=yes';
        }
        if (!options.winname) {
            options.winname = '__window__' + Math.floor((Math.random() * 1000000) + 1);
        }

        var dualScreenLeft = window.screenLeft != undefined ? window.screenLeft : screen.left;
        var dualScreenTop = window.screenTop != undefined ? window.screenTop : screen.top;
        var screenWidth = window.innerWidth ? window.innerWidth : document.documentElement.clientWidth ? document.documentElement.clientWidth : screen.width;
        var screenHeight = window.innerHeight ? window.innerHeight : document.documentElement.clientHeight ? document.documentElement.clientHeight : screen.height;
        if (!options.left) {
            options.left = (screenWidth / 2) - (options.width / 2) + dualScreenLeft;
        }
        if (!options.top) {
            options.top = (screenHeight / 2) - (options.height / 2);
        }

        if (options.params) {
            var params = '';
            $.each(options.params, function (name, value) {
                if (params != '') {
                    params += '&';
                }
                params += name + '=' + value;

            });
            url += params ? '?' + params : '';
        }
        return window.open(url, options.winname, 'top=' + options.top + ', left=' + options.left + ', width=' + options.width + ', height=' + options.height + ', ' + options.layout);
    },
    onlyNumber: function (event) {
        // 숫자만 입력
        event = event || window.event;
        var keyID = (event.which) ? event.which : event.keyCode;
        if ((keyID >= 48 && keyID <= 57) || (keyID >= 96 && keyID <= 105) || keyID == 8 || keyID == 46 || keyID == 37 || keyID == 39)
            return;
        else
            return false;
    },
    removeChar: function (event) {
        //문자제거
        event = event || window.event;
        var keyID = (event.which) ? event.which : event.keyCode;
        if (keyID == 8 || keyID == 46 || keyID == 37 || keyID == 39)
            return;
        else
            event.target.value = event.target.value.replace(/[^0-9]/g, "");
    },
    sizeOf: function (obj) {
        if (obj !== null && obj !== undefined) {
            switch (typeof obj) {
                case 'number':
                    bytes += 8;
                    break;
                case 'string':
                    bytes += obj.length * 2;
                    break;
                case 'boolean':
                    bytes += 4;
                    break;
                case 'object':
                    var objClass = Object.prototype.toString.call(obj).slice(8, -1);
                    if (objClass === 'Object' || objClass === 'Array') {
                        for (var key in obj) {
                            if (!obj.hasOwnProperty(key)) continue;
                            CommonUtil.sizeOf(obj[key]);
                        }
                    }
                    else {
                        bytes += obj.toString().length * 2;
                    }
                    break;
            }
        }
        return bytes;
    },
    toggleFullScreen: function (element_id) {
        //let element = document.querySelector("body");
        let element = document.querySelector(element_id);
        if (!document.fullscreenElement) {
            if (element.requestFullscreen) return element.requestFullscreen()
            if (element.webkitRequestFullscreen)
                return element.webkitRequestFullscreen()
            if (element.mozRequestFullScreen) return element.mozRequestFullScreen()
            if (element.msRequestFullscreen) return element.msRequestFullscreen()
        } else {
            if (document.exitFullscreen) return document.exitFullscreen()
            if (document.webkitCancelFullscreen)
                return document.webkitCancelFullscreen()
            if (document.mozCancelFullScreen) return document.mozCancelFullScreen()
            if (document.msExitFullscreen) return document.msExitFullscreen()
        }
    },
    convertApprLineNameHtml: function (apprLine, apprLineState) {
        let ret = [];
        if (apprLine != null && apprLine != '') {
            let arrLine = apprLine.split(' ▶ ');
            let arrLineState = apprLineState.split('||');
            $.each(arrLineState, function (index, item) {
                let html = arrLine[index];
                if (item == 'process') {
                    html = '<span style="color:#5d9cec;">' + arrLine[index] + '</span>';
                }
                ret.push(html);
            });
        }
        return ret.join(' ▶ ');
    },
    convertApprStateCss: function (stateName, state) {
        let cssName = '';
        if (state == 'process') {
            cssName = 'grid-appr-state-blue';
        } else if (state == 'write' || state == null) {
            cssName = 'grid-appr-state-yellow';
        } else if (state == 'reject') {
            cssName = 'grid-appr-state-red';
        }

        return cssName;
    }
};

/******************************************************************/
let FormUtil = {
    extractForm: function ($form, disabledFields = []) {
        let _this = this;
        let values = {};
        if ($form) {
            let form = $form.serializeArray();
            form.map(val => {
                values[val.name] = val.value;
            });
        }
        disabledFields.map(val => {
            values[val] = $form.find('#' + val).val();
        });

        return values;
    },
    // serialize시에 disabled값도 포함하여 serialize 리턴
    disabledSerialize: function (_useForm) {
        var disableds = _useForm.find(':input:disabled').removeAttr('disabled');
        var params = _useForm.serialize();
        disableds.attr('disabled', 'disabled');
        return params;
    },

    // 데이터를 Form내부 Control 에 바인딩 (name으로 매칭)
    BindDataForm: function (_resultSet, $form) {
        //console.log('BindDataForm', _resultSet);
        $.each(_resultSet, function (key, value) {
            // 빈스트링으로 오는 값은 반드시 null 값으로 치환한다. 또는 json 에서 null 로 넘겨준다
            // 치환하지 않고 빈스트링값('') 으로 처리하면 input[value=] 이렇게 되어 오류 발생함.
            if (key === '') value = null;
            if (value === '') value = null;
            //console.log('form ke', key);
            var $frmCtl = $form.find('[name=' + key + ']');

            if ($frmCtl.length == 0)
                return true;
            let object = $frmCtl[0];
            var tagName = object === undefined ? '' : object.tagName.toUpperCase();
            var tagClassName = object === undefined ? '' : object.className.toUpperCase();
            let type_name = object.type;

            //console.log('form control', $frmCtl);
            if (tagName == 'SELECT') {

                //if ($('#' + key).is(':disabled')) { $('#' + key).removeAttr('disabled'); }
                if ($frmCtl.is(':disabled')) { $frmCtl.removeAttr('disabled'); }
                //$('#' + key + ' > option').each(function () {
                //$('#' + key + ' > option').each(function () {
                //    $(this).removeProp('selected');
                //});
                //$('#' + key + ' > option[value=' + value + ']').prop('selected', true);
                //_f$formorm.find('[name=' + key + '] > option[value=' + value + ']').prop('selected', true);
                $frmCtl.val(value);
            } else if (tagName == 'INPUT' || tagName == 'TEXTAREA') {

                if ($frmCtl.is(':disabled')) { $frmCtl.removeAttr('disabled'); }
                if (type_name == 'checkbox') {
                    //console.log('bind checkbox', value);
                    let checkValue = $frmCtl.val();
                    //console.log('checkbox value', checkValue);
                    if (checkValue != undefined)
                        $frmCtl.prop('checked', value == checkValue);
                    else
                        $frmCtl.prop('checked', value);
                    //$frmCtl.attr('checked', value);
                } else if (type_name == 'radio') {
                    $frmCtl.removeAttr('checked');
                    var $radioCtl = $('input:radio[name=' + key + ']:input[value=' + value + ']');
                    $radioCtl.prop('checked', true);
                    $radioCtl.attr('checked', true);
                } else {
                    if ($.isNumeric(value) || value === null) {
                        $frmCtl.val(value);
                    } else {
                        $frmCtl.val(value.replace('&amp;', '&'));
                    }
                }
            } else if (tagName == 'SPAN') {
                if (tagClassName == 'DATE') {
                    var ddspan = new Date(value);
                    $frmCtl.text(ddspan.toLocaleString());
                } else {
                    $frmCtl.text(value);
                }
            }
        });
    }
};

// 상세 영역. 머리에는 [등록]·[수정]·[삭제]만 둔다.
// 행을 고르면 읽기 전용(view), [수정]을 누르면 o.fields 가 풀리고 [저장]·[취소](와 o.editOnly)만 보인다(edit).
// [등록]·[수정]·[삭제]는 늘 켜져 있다 — 고른 행 없이 [수정]·[삭제]를 누르면 안내만 한다.
// o: { form, grid, rowIdField, fields, editOnly, buttons: {create, edit, del, save, cancel}, onCreate(), onDelete(row), onSave(row) }
// 값을 저장한 뒤 화면이 bind(새 행)으로 읽기 전용에 돌려놓는다.
var DetailForm = {
    create: function (o) {
        const $form = $(o.form);
        const b = o.buttons;
        const self = { row: null, editing: false, before: null };
        // 처음부터 막힌 칸(키 값 등)은 늘 막는다. BindDataForm 이 disabled 를 풀기 때문이다.
        const $locked = $form.find(':input:disabled').not(o.fields);
        const snapshot = function () {
            return JSON.stringify([$form.serializeArray(), $form.find(o.fields).filter(':checkbox').map(function () { return this.checked; }).get(),
                $form.find('input[type=file]').map(function () { return this.files.length; }).get()]);
        };
        const setEditing = function (editing) {
            self.editing = editing;
            $form.find(o.fields).prop('disabled', !editing);
            $locked.prop('disabled', true);
            $form.find('.is-invalid').removeClass('is-invalid');
            $([b.create, b.edit, b.del].filter(Boolean).join(',')).toggleClass('d-none', editing);
            $([b.save, b.cancel, o.editOnly].filter(Boolean).join(',')).toggleClass('d-none', !editing);
        };
        // 토글(.form-switch)의 글자 label 에 data-on·data-off 가 있으면 상태를 글로 보인다(활성화/비활성화).
        const syncSwitches = function () {
            $form.find('.form-switch input[type=checkbox]').each(function () {
                const $label = $form.find('label[for="' + this.id + '"][data-on]');
                $label.text(this.checked ? $label.data('on') : $label.data('off'));
            });
        };
        $form.on('change', '.form-switch input[type=checkbox]', syncSwitches);
        const needRow = function () {
            if (self.row) return true;
            Alert.alert('', '목록에서 항목을 선택해 주세요.');
            return false;
        };
        self.bind = function (row) {
            self.row = row;
            $form[0].reset();
            FormUtil.BindDataForm(row, $form);
            // BindDataForm 은 체크박스를 문자열 값으로 맞춘다. 참/거짓 값은 여기서 맞춘다.
            $form.find('input[type=checkbox][name]').each(function () {
                if (typeof row[this.name] === 'boolean') this.checked = row[this.name];
            });
            syncSwitches();
            setEditing(false);
        };
        self.clear = function () {
            self.row = null;
            $form[0].reset();
            syncSwitches();
            setEditing(false);
        };
        // 목록에서 행을 눌렀을 때. 수정 중에 바꾼 값이 있으면 확인하고, 취소하면 그대로 수정을 잇는다.
        self.select = function (row, done) {
            const go = function () { self.bind(row); if (done) done(row); };
            if (!self.editing || snapshot() === self.before) { go(); return; }
            Alert.confirm('', '수정 중인 내용을 버리고 이동할까요?', go, function () {
                if (o.grid && self.row) o.grid.setSelectionByRowId(self.row[o.rowIdField || 'id']);
            });
        };
        $(b.edit).on('click', function () {
            if (!needRow()) return;
            setEditing(true);
            self.before = snapshot();
        });
        $(b.cancel).on('click', function () { self.bind(self.row); });
        if (b.create) $(b.create).on('click', function () { o.onCreate(); });
        if (b.del) $(b.del).on('click', function () { if (needRow()) o.onDelete(self.row); });
        $(b.save).on('click', function () { if (DetailForm.requireFields($form)) o.onSave(self.row); });
        setEditing(false);
        return self;
    },
    // required 가 붙은 빈 칸(켜진 것만)에 is-invalid 를 달고 알린다. 다 찼으면 true.
    requireFields: function ($scope) {
        let first = null;
        $scope.find('[required]:enabled').each(function () {
            const empty = this.type === 'file' ? !this.files.length : !$.trim($(this).val());
            $(this).toggleClass('is-invalid', empty);
            if (empty && !first) first = this;
        });
        if (!first) return true;
        Alert.alert('', '필수 항목을 입력해 주세요.', function () { first.focus(); });
        return false;
    }
};

// AX5 mask를 대신하며 중첩된 비동기 작업이 모두 끝날 때까지 화면을 가린다.
var LoadingMask = {
    _count: 0,
    _el: null,
    _ensure: function () {
        if (this._el && document.body.contains(this._el)) {
            return;
        }
        let element = document.getElementById('commonLoadingMask');
        if (!element) {
            element = document.createElement('div');
            element.id = 'commonLoadingMask';
            element.setAttribute(
                'style',
                'position:fixed;top:0;left:0;right:0;bottom:0;z-index:1100;' +
                'display:none;align-items:center;justify-content:center;' +
                'background:rgba(0,0,0,0.32);'
            );
            element.innerHTML = '<div style="text-align:center;color:#fff;">' +
                '<img src="/static/img/loading.svg" alt="loading" style="width:48px;height:48px;">' +
                '<div style="margin-top:8px;">로딩중...</div></div>';
            document.body.appendChild(element);
        }
        this._el = element;
    },
    open: function () {
        this._ensure();
        this._count++;
        this._el.style.display = 'flex';
    },
    close: function () {
        this._count = Math.max(0, this._count - 1);
        if (this._count === 0 && this._el) {
            this._el.style.display = 'none';
        }
    }
};

let AjaxUtil = {
    failureCallback: function (req, status, error) {
        // JSON 이 아닌 응답(502 의 nginx HTML 등)이나 message 가 없는 응답은 원문 대신 고정 문구를 보인다.
        let message = '';
        try {
            message = JSON.parse(req.responseText).message;
        }
        catch (ex) {
            console.log(status, req.responseText, ex);
        }
        Alert.alert('실패', message || '처리 중 오류가 발생했습니다. 잠시 후 다시 시도해 주세요.');
    },
    fillSelectOptionsRows: function ($combo, rows, null_option, selected_value) {
        $combo.empty();
        $.each(rows, function (index, row) {
            //let option = $('<option>',
            //    {
            //        value: row['value'],
            //        text: row['text'],
            //    });
            let option = $('<option>');
            option.val(row['value']).text(row['text']);
            //console.log('fill option row', row);    
            Object.keys(row).forEach(function (key) {
                //console.log('key', key);
                if (key != 'value' && key != 'text')
                    option.data(key, row[key]);
            });

            $combo.append(option);
        });

        if (selected_value) {
            $combo.val(selected_value).change();
        }

        return rows;
    },

    // getSyncData·postSyncData·postFileSyncData 는 제거했다. 동기 XHR 은 UI 스레드를
    // 멈추고 브라우저가 폐기를 예고한 기능이다. 조회는 getAsyncData, 변경은 postAsyncData 를 쓴다.
    getAsyncData: function (url, param_data, fn_success, fn_failure) {
        let _this = this;
        //if (!_this.mask) {
        //    _this.mask = new ax5.ui.mask();
        //}
        //_this.mask.open({ content: '<h1><img src="/static/img/loading.svg">로딩중...</h1>' });

        //console.log('getAsyncData mask', _this.mask);
        $.ajax({
            async: true,
            dataType: 'json',
            type: 'GET',
            url: url,
            data: param_data,
            success: function (res) {
                //if (_this.mask) {
                //    _this.mask.close();
                //    //_this.mask = null;
                //}
                fn_success(res);
            },
            error: function (req, status, error) {
                console.log('getAsyncData error', error, url);
                //if (_this.mask) {
                //    _this.mask.close();
                //    //_this.mask = null;
                //}
                if (typeof fn_failure !== 'undefined') {
                    fn_failure(req, status, error);
                } else {
                    AjaxUtil.failureCallback(req, status, error);
                }
            }
        });
    },

    postAsyncData: function (url, param_data, fn_success, fn_failure) {
        let result = null;

        if (param_data != null && typeof param_data === 'object') {
            if (param_data.hasOwnProperty('csrfmiddlewaretoken') == false) {
                let csrf = $('[name=csrfmiddlewaretoken]').val();
                param_data['csrfmiddlewaretoken'] = csrf;
            }
        }

        $.ajax({
            async: true,
            dataType: 'json',
            type: 'POST',
            url: url,
            data: param_data,
            success: function (res) {
                //console.log('post success res', res);
                fn_success(res);
            },
            error: function (req, status, error) {
                if (typeof fn_failure !== 'undefined') {
                    fn_failure(req, status, error);
                } else {

                    AjaxUtil.failureCallback(req, status, error);
                }
            }
        });
    },
    postFileAsyncData: function (url, form_data, fn_success, fn_failure) {
        let result = null;

        if (form_data != null && typeof form_data === 'object') {
            let csrf = $('[name=csrfmiddlewaretoken]').val();
            form_data.append("csrfmiddlewaretoken", csrf);
        }

        $.ajax({
            async: true,
            type: 'POST',
            url: url,
            data: form_data,
            processData: false,
            contentType: false,
            success: function (res) {
                //console.log('post success res', res);
                fn_success(res);
            },
            error: function (req, status, error) {
                if (typeof fn_failure !== 'undefined') {
                    fn_failure(req, status, error);
                } else {

                    AjaxUtil.failureCallback(req, status, error);
                }
            }
        });
    },
    // WeZonGrid 서버 모드(props.dataMode:'server')의 remoteDataSource.
    // 서버는 {rows, totalRows} 를 돌려준다(app/views/item/). query.page 는 1 부터다.
    gridRemoteSource: function (url, buildParams) {
        return {
            // buildParams 가 null 을 주면 요청하지 않고 빈 목록이다 — 그리드가 만들어지며 스스로 첫 조회를 하는데,
            // 조회 조건(날짜 등)이 아직 없거나 화면이 [조회]로 따로 부를 때 두 번 받지 않게 한다.
            loadRows: function (query) {
                const extra = buildParams ? buildParams() : {};
                if (extra === null) return Promise.resolve({ rows: [], totalRows: 0 });
                const params = $.extend({}, extra, { page: query.page, page_size: query.pageSize });
                return new Promise(function (resolve, reject) {
                    AjaxUtil.getAsyncData(url, params, resolve, function (req, status, error) {
                        AjaxUtil.failureCallback(req, status, error);
                        reject(error || status);
                    });
                });
            }
        };
    },
    // 서버 모드 그리드를 첫 페이지부터 다시 조회한다(검색 조건이 바뀌었을 때).
    // WeZonGrid 에 그리드 단위 공개 page 설정이 없어 내부 상태를 여기 한 곳에서만 만진다.
    // 그리드가 만들어지며 하는 첫 조회(requestSeq 0)가 아직이면 그 조회가 지금 조건을 쓰므로 다시 부르지 않는다.
    gridResearch: function (grid) {
        if (grid._remoteState && !grid._remoteState.requestSeq) return;
        if (grid._remoteState) grid._remoteState.page = 1;
        grid.refreshRemote('search');
    },
    // 콤보 조회. fn_success(rows) 로 결과를 받는다.
    // 동기 XHR 은 UI 스레드를 멈추고 브라우저가 폐기 예고한 기능이라 쓰지 않는다.
    getSelectData: function (combo_type, cond1, cond2, cond3, fn_success, fn_failure) {
        let data = {
            combo_type: combo_type,
        };
        if (cond1 !== undefined) {
            data.cond1 = cond1;
        }
        if (cond2 !== undefined) {
            data.cond2 = cond2;
        }
        if (cond3 !== undefined) {
            data.cond3 = cond3;
        }
        AjaxUtil.getAsyncData('/api/system/combo', data, function (rows) {
            if (fn_success) fn_success(Array.isArray(rows) ? rows : []);
        }, fn_failure);
    },
    getSelectDataWithNull: function (combo_type, null_option, condition1, condition2, condition3, fn_success, fn_failure) {
        AjaxUtil.getSelectData(combo_type, condition1, condition2, condition3, function (rows) {
            let text = null_option;
            if (null_option == 'choose') {
                text = i18n.getCommonText('선택');
            }
            else if (null_option == 'all') {
                text = i18n.getCommonText('전체');
            }
            else {
                text = null;
            }
            if (text) {
                rows.unshift({ 'value': '', 'text': text });
            }
            if (fn_success) fn_success(rows);
        }, fn_failure);
    },
    // 콤보에 옵션을 채운다. 기존 호출부는 그대로 두고 끝에 fn_done 만 더했다.
    // 콤보가 채워진 뒤에 할 일이 있으면 fn_done 을 넘긴다.
    fillSelectOptions: function ($combo, combo_type, null_option, selected_value, condition1, condition2, condition3, fn_done) {
        AjaxUtil.getSelectDataWithNull(combo_type, null_option, condition1, condition2, condition3, function (rows) {
            $combo.empty();
            $.each(rows, function (index, row) {
                $combo.append($('<option>', { value: row['value'], text: row['text'] }));
            });
            if (selected_value) {
                $combo.val(selected_value).change();
            }
            if (fn_done) fn_done(rows);
        });
    },


    //파일업로드
    uploadFile(files, menu_name, pk, action) {
        //let formData = new FormData();
        //files.forEach(file => {
        //    formData.append('file', file);
        //});
        //formData.append('action', action);
        //formData.append('menu_name', menu_name);
        //formData.append('pk', pk);
        //$.ajax({
        //    type: 'post',
        //    url: yullin.getUrl({ api: 'pop/file_upload' }),
        //    processData: false,
        //    contentType: false,
        //    data: formData,
        //    success: function (resp) {
        //        //console.log(resp.result.items)
        //    },
        //    error: function (err) {
        //        console.log(err);
        //    }
        //});//ajax
    },

    //파일다운로드(GET)
    downloadFile(url, filename) {

        LoadingMask.open();

        fetch(url)
            .then(resp => resp.blob())
            .then(blob => {
                //console.log('download blob', url);
                const url = window.URL.createObjectURL(blob);
                const a = document.createElement('a');
                a.style.display = 'none';
                a.href = url;
                // the filename you want
                a.download = filename;
                document.body.appendChild(a);
                a.click();
                window.URL.revokeObjectURL(url);
                //alert('your file has downloaded!'); 
                LoadingMask.close();
                //Notify.success('다운로드 성공');
            }).catch(() => {
                console.log('download error', url);
                Alert.alert('실패', '파일을 받지 못했습니다. 관리자에게 문의해 주세요.');
                LoadingMask.close();
            });

        //let url = yullin.getUrl({ api: api_url + '?' + param + '=' + val });
        //var link = document.createElement("a");
        //$(link).click(function (e) {
        //    e.preventDefault();
        //    window.location.href = url;
        //});
        //$(link).click();
        //$(link).remove();
    },
};

// 업무별 공통으로 사용되는 function script (default layout 사용)
// 버튼, TAB 권한, 대시보드 function 호출, QA 상세 호출, 녹취청취 호출등

// 버튼별 권한 처리
var authDisableBtn = function (data) {
    // servlet(modelandview에서 리턴된 권한버튼,탭 데이터로 show/hide 처리)
    //console.log(data)
    // 화면별 권한에 따른 버튼 활성화 처리(show, hide)
    var btnRoleList = data.replace('[', '').replace(']', '').replace(/ /g, '').split(',');
    // [중요]권한제어할 button에는 btn-role-group 클래스명이 항상 포함되어야 함.
    $('.btn-role-group').each(function () {
        var _this = this;
        $(_this).addClass('btndisplaynone');
        $.each(btnRoleList, function () {
            var btntxt = this;
            if (_this.id == btntxt) {
                $(_this).removeClass('btndisplaynone');
            } else {
                if (btntxt.substr(btntxt.length - 1, btntxt.length) == '*') {
                    if (btntxt.substr(0, btntxt.length - 1) == _this.id.substr(0, btntxt.length - 1)) {
                        $(_this).show();
                        $(_this).removeClass('btndisplaynone');
                    }
                }
            }
        });
        $('.btndisplaynone').remove();
    });
};

// TAB별 권한처리
var authDisableTab = function (data) {
    // 화면별 권한에 따른 TAB(탭) 활성화 처리
    var tabRoleList = data.replace('[', '').replace(']', '').replace(/ /g, '').split(',');
    // [중요]권한제어할 TAP의 a태그에는 tab-role-group 클래스명이 항상 포함되어야 함.
    // tab li태그 하위의 a태그의 id로 권한 관리가 됨 - <li><a href="#tabs_detcd_tab" id="tabs_detcd" class="tab-role-group">
    // tab 화면을 삭제하기 위해 <div id="tabs_detcd_tab" class="tab-pane">처럼 tab화면 div의 ID를 'tab메뉴 a태그 id' + '_tab' 을 붙여야 함.
    $('.tab-role-group').each(function () {
        var _this = this;
        if (jQuery.inArray(_this.id, tabRoleList) < 0) {
            $('#' + _this.id).closest("li").remove();
            $('.' + _this.id + '_tab').remove();
        }
    });
    $('.tab-role-group').each(function () {
        $('#' + this.id).closest("li").addClass('active role');
        $('#' + this.id).trigger('click');
        $('.' + this.id + '_tab').addClass('active');
        return false;
    });
};

// 다국어 처리
// marker의 labeltarget이 title/aria-label이면 속성만 바꾸고, 지정이 없으면 기존 text/placeholder 계약을 따른다.
function applyI18nLabel($element, labelText) {
    let targets = String($element.data('labeltarget') || '').trim().split(/\s+/).filter(Boolean);
    if (targets.length > 0) {
        targets.forEach(function (target) {
            if (target === 'title' || target === 'aria-label') {
                $element.attr(target, labelText);
            }
        });
        if ($element.attr('placeholder') !== undefined) {
            $element.attr('placeholder', labelText);
        }
        return;
    }
    $element.text(labelText);
    $element.attr('placeholder', labelText);
}

var i18n = {
    modal: null,
    mask: null,
    commonModal: null,
    commonMask: null,
    dicMonth: {
        'ko-KR': ['1월', '2월', '3월', '4월', '5월', '6월', '7월', '8월', '9월', '10월', '11월', '12월'],
        'en-US': ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'],
        'zh-CN': ['1月', '2月', '3月', '4月', '5月', '6月', '7月', '8月', '9月', '10月', '11月', '12月'],
        'vi-VN': ['Th1', 'Th2', 'Th3', 'Th4', 'Th5', 'Th6', 'Th7', 'Th8', 'Th9', 'Th10', 'Th11', 'Th12'],
    },
    dicDays: {
        'ko-KR': ['일', '월', '화', '수', '목', '금', '토'],
        'en-US': ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'],
        'zh-CN': ['日', '一', '二', '三', '四', '五', '六'],
        'vi-VN': ['CN', 'T2', 'T3', 'T4', 'T5', 'T6', 'T7'],
    },
    url: '/api/common/labels',
    storageKeys: ['lang_code', 'kr_common_common', 'en_common_common'],
    COMMON_CACHE_VERSION: 'v3',
    DEFAULT_LOCALE: 'ko-KR',
    commonResource: {},
    commonWhitespaceResource: {},
    menuResource: {},
    guiResource: {},
    _commonReady: false,
    _guiReady: false,
    _readyHeld: false,
    _readyCallbacks: [],
    // common과 GUI 라벨을 모두 읽을 때까지 document ready를 보류해 첫 화면부터 번역된 문구를 사용한다.
    holdReady: function () {
        if (!i18n._readyHeld && typeof $.holdReady === 'function') {
            i18n._readyHeld = true;
            $.holdReady(true);
        }
    },
    whenReady: function (callback) {
        if (typeof callback !== 'function') {
            return;
        }
        if (i18n._commonReady && i18n._guiReady) {
            callback();
            return;
        }
        i18n._readyCallbacks.push(callback);
    },
    // 각 자원의 완료 상태를 기록하고 두 자원이 모두 끝났을 때만 ready 대기를 해제한다.
    _markReady: function (resource) {
        if (resource === 'common') {
            i18n._commonReady = true;
        } else if (resource === 'gui') {
            i18n._guiReady = true;
        }
        i18n._flushReady();
    },
    _flushReady: function () {
        if (!i18n._commonReady || !i18n._guiReady) {
            return;
        }
        let callbacks = i18n._readyCallbacks.splice(0);
        if (i18n._readyHeld) {
            i18n._readyHeld = false;
            $.holdReady(false);
        }
        callbacks.forEach(function (callback) {
            callback();
        });
    },
    resetData: function () {
        let lang_cd = i18n.getLanguageCode();
        sessionStorage.clear();
        sessionStorage.setItem('lang_code', lang_cd);
    },
    // 깨졌거나 이전 형식인 캐시는 버리고 서버에서 다시 받을 수 있도록 cache miss로 처리한다.
    _readCachedArray: function (storageKey) {
        try {
            let cached = sessionStorage.getItem(storageKey);
            if (cached === null || cached === 'null') {
                return null;
            }
            let parsed = JSON.parse(cached);
            if (!Array.isArray(parsed)) {
                throw new Error('i18n cache is not an array');
            }
            return parsed;
        } catch (error) {
            try {
                sessionStorage.removeItem(storageKey);
            } catch (removeError) { }
            return null;
        }
    },
    _writeCachedArray: function (storageKey, result) {
        try {
            sessionStorage.setItem(
                storageKey,
                result.length > 0 ? JSON.stringify(result) : null
            );
        } catch (error) {
            try {
                sessionStorage.removeItem(storageKey);
            } catch (removeError) { }
        }
    },
    initialize: function () {
        let lang_cd = i18n.getLanguageCode();
        i18n.initializeCommonData(lang_cd);
        i18n.initializeGUIData(lang_cd);
    },
    initializeMenuData: function (lang_cd) {
        let storageKey = lang_cd + '_common_menu';
        let menuStorageData = i18n._readCachedArray(storageKey);
        let loadMenuData = function (result) {
            result = Array.isArray(result) ? result : [];
            i18n.menuResource = {};
            i18n._writeCachedArray(storageKey, result);
            if (result.length > 0) {
                $.each(result, function (idx, item) {
                    i18n.menuResource[item.label_code] = { 'text': item.text, 'desc': item.descr };
                });
            }
        };
        if (menuStorageData === null) {
            let data = {
                lang_code: lang_cd,
                gui_code: 'common',
                template_key: 'menu',
                action: 'read'
            };
            AjaxUtil.getAsyncData(i18n.url, data, loadMenuData, function () {
                // 라벨을 못 받아도 화면은 떠야 한다. 기본 문구로 진행한다.
                loadMenuData([]);
            });
        } else {
            loadMenuData(menuStorageData);
        }
    },
    initializeCommonData: function (lang_cd) {
        let storageKey = lang_cd + '_common_common_' + i18n.COMMON_CACHE_VERSION;
        let commonStorageData = i18n._readCachedArray(storageKey);
        let loadCommonData = function (result) {
            result = Array.isArray(result) ? result : [];
            i18n.commonResource = {};
            try {
                i18n._writeCachedArray(storageKey, result);
                $.each(result, function (idx, item) {
                    i18n.commonResource[item.label_code] = { 'text': item.text, 'desc': item.descr };
                });
                i18n._rebuildCommonWhitespaceResource();
                i18n.applyCommonLabel();
                if (i18n._guiReady) {
                    i18n.applyGUILabel();
                }
            } finally {
                i18n._markReady('common');
            }
        };
        if (commonStorageData === null) {
            let data = {
                lang_code: lang_cd,
                gui_code: 'common',
                template_key: 'common',
                action: 'read'
            };
            let fnsuccess = function (result) {
                loadCommonData(result);
            };
            let fnfailure = function (req, status, error) {
                loadCommonData([]);
                AjaxUtil.failureCallback(req, status, error);
            };
            AjaxUtil.getAsyncData(i18n.url, data, fnsuccess, fnfailure);
        }
        else {
            loadCommonData(commonStorageData);
        }
    },
    initializeGUIData: function (lang_cd) {
        if (gui.gui_code == '') {
            i18n._markReady('gui');
            return;
        }
        let storageKey = lang_cd + '_' + gui.gui_code + '_' + gui.template_key;
        let guiStorageData = i18n._readCachedArray(storageKey);
        let loadGUIData = function (result) {
            result = Array.isArray(result) ? result : [];
            i18n.guiResource = {};
            try {
                i18n._writeCachedArray(storageKey, result);
                $.each(result, function (idx, item) {
                    i18n.guiResource[item.label_code] = { 'text': item.text, 'desc': item.descr };
                });
                i18n.applyGUILabel();
            } finally {
                i18n._markReady('gui');
            }
        };
        if (guiStorageData === null) {
            let data = {
                gui_code: gui.gui_code,
                template_key: gui.template_key,
                lang_code: lang_cd,
                action: 'read'
            };
            let fnsuccess = function (result) {
                loadGUIData(result);
            };
            let fnfailure = function (req, status, error) {
                loadGUIData([]);
                AjaxUtil.failureCallback(req, status, error);
            };
            AjaxUtil.getAsyncData(i18n.url, data, fnsuccess, fnfailure);
        }
        else {
            loadGUIData(guiStorageData);
        }
    },
    normalizeLanguageCode: function (lang_cd) {
        let aliases = {
            'ko': 'ko-KR', 'ko-kr': 'ko-KR',
            'en': 'en-US', 'en-us': 'en-US',
            'zh': 'zh-CN', 'zh-cn': 'zh-CN',
            'vi': 'vi-VN', 'vi-vn': 'vi-VN'
        };
        let normalized = String(lang_cd || '').trim().toLowerCase();
        return aliases[normalized] || i18n.DEFAULT_LOCALE;
    },
    getLanguageCode: function () {
        let lang_cd = i18n.normalizeLanguageCode(sessionStorage.getItem('lang_code'));
        sessionStorage.setItem('lang_code', lang_cd);
        return lang_cd;
    },
    getMenuText: function (code, args) {
        let result = code;
        let exist = i18n.menuResource.hasOwnProperty(code);
        if (exist) {
            result = i18n.menuResource[code].text;
            if (args !== null && $.type(args) === 'array') {
                $.each(args, function (_idx, _val) {
                    result = result.replace('{' + _idx + '}', _val);
                });
            }
        }
        return result;
    },
    // 일반 공백(U+0020)만 제거한 한글 signature를 만들어 안전 표시된 common 문구끼리만 비교한다.
    _whitespaceLabelSignature: function (code) {
        let value = String(code || '');
        if (!/[가-힣]/.test(value)) {
            return null;
        }
        return value.replace(/ /g, '');
    },
    // 같은 signature가 둘 이상이면 모호한 fallback을 막기 위해 null 충돌 표식으로 보관한다.
    _rebuildCommonWhitespaceResource: function () {
        i18n.commonWhitespaceResource = {};
        $.each(i18n.commonResource, function (labelCode, resource) {
            let description = String(resource && resource.desc || '');
            if (!/(?:^|[,\s])whitespace-variant(?:[,\s:]|$)/.test(description)) {
                return;
            }
            let signature = i18n._whitespaceLabelSignature(labelCode);
            if (signature === null) {
                return;
            }
            if (Object.prototype.hasOwnProperty.call(i18n.commonWhitespaceResource, signature)) {
                let existing = i18n.commonWhitespaceResource[signature];
                if (existing !== null && existing.labelCode !== labelCode) {
                    i18n.commonWhitespaceResource[signature] = null;
                }
                return;
            }
            i18n.commonWhitespaceResource[signature] = {
                labelCode: labelCode,
                resource: resource
            };
        });
    },
    // GUI exact → common exact → 유일한 안전 공백 variant 순서로 조회하고, 없으면 원문을 반환한다.
    getGUIText: function (code, args) {
        let result = code;
        let resource = null;
        if (i18n.guiResource.hasOwnProperty(code)) {
            resource = i18n.guiResource[code];
        } else if (i18n.commonResource.hasOwnProperty(code)) {
            resource = i18n.commonResource[code];
        } else {
            let signature = i18n._whitespaceLabelSignature(code);
            if (
                signature !== null
                && Object.prototype.hasOwnProperty.call(i18n.commonWhitespaceResource, signature)
                && i18n.commonWhitespaceResource[signature] !== null
            ) {
                resource = i18n.commonWhitespaceResource[signature].resource;
            }
        }
        if (resource !== null) {
            result = resource.text;
            if (args !== null && $.type(args) === 'array') {
                $.each(args, function (_idx, _val) {
                    result = result.replace('{' + _idx + '}', _val);
                });
            }
        } else {
            //console.log('getGUIText 라벨코드없음', i18n.guiResource);
        }

        return result;
    },
    getCommonText: function (code, args) {
        let result = code;
        let exist = i18n.commonResource.hasOwnProperty(code);
        if (exist) {
            result = i18n.commonResource[code].text;
            if (args !== null && $.type(args) === 'array') {
                $.each(args, function (_idx, _val) {
                    result = result.replace('{' + _idx + '}', _val);
                });
            }
        } else {
            //console.log('getCommonText 라벨코드없음', i18n.guiResource);
        }

        return result;
    },
    applyLabel: function () {
        i18n.applyCommonLabel();
        if (gui.gui_code != '') {
            i18n.applyGUILabel();
        }
    },
    applyGUILabel: function () {
        let $labels = $('[data-labelCd]');
        $labels.each(function () {
            var $this = $(this);
            let labelcd = $this.data('labelcd');
            let lbltext = i18n.getGUIText(labelcd);

            applyI18nLabel($this, lbltext);

            //if (getLabelDesc(labelcd) !== undefined) {
            //    // 라벨데이터에 설명데이터가 있을경우 & th태그의 label에만 ? 설명아이콘 활성화
            //    if ($this.prop('tagName') == 'TH') {
            //        $this.addClass('lbldescexist');
            //    } else {
            //        $this.attr('title', lbltext);
            //    }
            //} else {
            //    $this.attr('title', lbltext);
            //}
        });
        // GUI resource가 준비된 이 pass에서 GUI 소유 aria-label만 적용한다.
        $('[data-labelAriaCd]').each(function () {
            let $this = $(this);
            $this.attr('aria-label', i18n.getGUIText($this.data('labelariacd')));
        });

        if (userinfo.group_code == 'admin') {
            $labels.unbind('contextmenu').bind('contextmenu', 'th', function (e) {
                let labelcd = $(this).data('labelcd');
                let lang_code = i18n.getLanguageCode();
                //let paramData = {
                //    lang_code: lang_code,
                //    label_code: labelcd,
                //    gui_code: gui.gui_code,
                //    template_key: gui.template_key
                //};
                i18n.modal = new PopupDraggable('');

                let config = {
                    width: 380,
                    height: 540,
                    iframe: {
                        method: 'get',
                        url: '/page/popup/label',
                        param: 'lang_code=' + lang_code + '&label_code=' + labelcd + '&gui_code=' + gui.gui_code + '&template_key=' + gui.template_key
                    }
                };
                i18n.modal.open(config);
                //Ax5Modal.open({ url: '/page/popup/label', width: 480, height: 500, callbackfn: 'i18n.applyGUILabel', params: paramData });
                return false;
            });
        }
    },
    applyCommonLabel: function () {
        let $labels = $('[data-commonCd]');
        $labels.each(function () {
            var $this = $(this);
            let labelcd = $this.data('commoncd');
            let lbltext = i18n.getCommonText(labelcd);
            applyI18nLabel($this, lbltext);
        });
        // common resource가 준비된 이 pass에서 common 소유 aria-label만 적용한다.
        $('[data-commonAriaCd]').each(function () {
            let $this = $(this);
            $this.attr('aria-label', i18n.getCommonText($this.data('commonariacd')));
        });
        if (userinfo.group_code == 'admin') {
            $labels.unbind('contextmenu').bind('contextmenu', 'th', function (e) {
                let labelcd = $(this).data('commoncd');
                let lang_code = i18n.getLanguageCode();
                let paramData = {
                    lang_code: lang_code,
                    label_code: labelcd,
                    gui_code: 'common',
                    template_key: 'common',
                    //callback: 'i18n.applyCommonLabel'
                };

                i18n.modal = new PopupDraggable('');
                let width = 350;
                if (window.innerWidth < 350) {
                    width = 300;
                }
                let config = {
                    width: width,
                    height: 240,
                    iframe: {
                        method: 'get',
                        url: '/page/popup/label',
                        param: 'lang_code=' + lang_code + '&label_code=' + labelcd + '&gui_code=common&template_key=common'
                    }
                };
                i18n.modal.open(config);


                //Ax5Modal.open({ url: '/page/popup/label', width: 480, height: 500, callbackfn: null, params: paramData });
                return false;
            });
        }
    },
    applyContentLabel: function ($popupContent) {
        let $labels = $popupContent.find('[data-labelCd]');
        $labels.each(function () {
            var $this = $(this);
            let labelcd = $this.data('labelcd');
            let lbltext = i18n.getGUIText(labelcd);

            applyI18nLabel($this, lbltext);
        });
        $popupContent.find('[data-labelAriaCd]').each(function () {
            let $this = $(this);
            $this.attr('aria-label', i18n.getGUIText($this.data('labelariacd')));
        });

        if (userinfo.group_code == 'admin') {
            $labels.unbind('contextmenu').bind('contextmenu', 'th', function (e) {
                let labelcd = $(this).data('labelcd');
                let lang_code = i18n.getLanguageCode();
                //let paramData = {
                //    lang_code: lang_code,
                //    label_code: labelcd,
                //    gui_code: gui.gui_code,
                //    template_key: gui.template_key
                //};
                i18n.modal = new PopupDraggable('');

                let config = {
                    width: 380,
                    height: 540,
                    iframe: {
                        method: 'get',
                        url: '/page/popup/label',
                        param: 'lang_code=' + lang_code + '&label_code=' + labelcd + '&gui_code=' + gui.gui_code + '&template_key=' + gui.template_key
                    }
                };
                i18n.modal.open(config);
                //Ax5Modal.open({ url: '/page/popup/label', width: 480, height: 500, callbackfn: 'i18n.applyGUILabel', params: paramData });
                return false;
            });
        }


        $labels = $('[data-commonCd]');
        $labels.each(function () {
            var $this = $(this);
            let labelcd = $this.data('commoncd');
            let lbltext = i18n.getCommonText(labelcd);
            applyI18nLabel($this, lbltext);
        });
        $popupContent.find('[data-commonAriaCd]').each(function () {
            let $this = $(this);
            $this.attr('aria-label', i18n.getCommonText($this.data('commonariacd')));
        });
        if (userinfo.group_code == 'admin') {
            $labels.unbind('contextmenu').bind('contextmenu', 'th', function (e) {
                let labelcd = $(this).data('commoncd');
                let lang_code = i18n.getLanguageCode();
                let paramData = {
                    lang_code: lang_code,
                    label_code: labelcd,
                    gui_code: 'common',
                    template_key: 'common',
                    //callback: 'i18n.applyCommonLabel'
                };

                i18n.modal = new PopupDraggable('');
                let width = 350;
                if (window.innerWidth < 350) {
                    width = 300;
                }
                let config = {
                    width: width,
                    height: 240,
                    iframe: {
                        method: 'get',
                        url: '/page/popup/label',
                        param: 'lang_code=' + lang_code + '&label_code=' + labelcd + '&gui_code=common&template_key=common'
                    }
                };
                i18n.modal.open(config);
                //Ax5Modal.open({ url: '/page/popup/label', width: 480, height: 500, callbackfn: null, params: paramData });
                return false;
            });
        }


    },
    getMonthArrayText: function () {
        let langcd = i18n.getLanguageCode();
        if (i18n.dicMonth.hasOwnProperty(langcd)) {
            return i18n.dicMonth[langcd];
        } else {
            return i18n.dicMonth[i18n.DEFAULT_LOCALE];
        }
    },
    getDayArrayText: function () {
        let langcd = i18n.getLanguageCode();
        if (i18n.dicDays.hasOwnProperty(langcd)) {
            return i18n.dicDays[langcd];
        } else {
            return i18n.dicDays[i18n.DEFAULT_LOCALE];
        }
    },
};

// 템플릿의 ready handler는 두 라벨 자원이 준비된 뒤 실행한다.
// 캐시 유무와 관계없이 차트·동적 DOM이 첫 생성부터 현재 언어를 사용하게 하는 계약이다.
if (userinfo.login_id != '') {
    i18n.holdReady();
    i18n.initialize();
}

//권한처리
let yullinAuth = {
    //inspection: function () {
    //    let $items = $('[data-authCd]');
    //    $items.each(function () {
    //        let $this = $(this);
    //        let authcd = $this.data('authcd');
    //        if (authcd == 'W') {
    //            if (userinfo.can_write() == false) {
    //                $this.remove();
    //            }
    //        }
    //    });
    //},
    removeWriteButton: function ($content) {
        let $items;
        if ($content)
            $items = $content.find('.y_write_auth');
        else
            $items = $('.y_write_auth');
        $items.each(function () {
            if (!userinfo.can_write())
                $(this).remove();
        });
    },
};

// 시간(hh24:mi)형식 validation
let DataValidation = { timeCheck: null, validateTime: null };

DataValidation.timeCheck = function (hours, minutes) {
    let i = 0;

    if (hours == "" || isNaN(hours) || parseInt(hours) > 23) {
        i++;
    } else if (parseInt(hours) == 0) {
        hours = "00";
    } else if (hours < 10 && hours.length < 2) {
        hours = "0" + hours;
    }

    if (minutes == "" || isNaN(minutes) || parseInt(minutes) > 59) {
        i++;
    } else if (parseInt(minutes) == 0) {
        minutes = "00";
    } else if (minutes < 10 && minutes.length < 2) {
        minutes = "0" + minutes;
    }

    if (i == 0) {
        return hours + ":" + minutes;
    } else {
            /*alert*/("Invalid Time Format.");
        return "";
    }
}

DataValidation.validateTime = function (obj) {
    /*
         _this.$addModal.find('#start_time').blur(function (event) {
                DataValidation.validateTime(event.target);
          });
     */
    let timeValue = obj.value;
    let sHours;
    let sMinutes;

    if (timeValue == "") {
            /*alert*/("Invalid Time format.");
        obj.value = "";
        return false;
    }
    else {
        if (timeValue.indexOf(":") > 0) {
            sHours = timeValue.split(':')[0];
            sMinutes = timeValue.split(':')[1];
            obj.value = DataValidation.timeCheck(sHours, sMinutes);
        }
        else {
            if (timeValue.length >= 4) {
                sHours = timeValue.substring(0, 2);
                sMinutes = timeValue.substring(2, 4);
                obj.value = DataValidation.timeCheck(sHours, sMinutes);
            }
            else if (timeValue.length == 3) {
                sHours = timeValue.substring(0, 2);
                sMinutes = timeValue.substring(2, 3);
                if (parseInt(sHours) > 23) {
                    sHours = timeValue.substring(0, 1);
                    sMinutes = timeValue.substring(1, 3);
                }
                obj.value = DataValidation.timeCheck(sHours, sMinutes);
            }
            else if (timeValue.length <= 2) {
                sHours = timeValue.substring(0, 2);
                sMinutes = '00';
                if (parseInt(sHours) > 23) {
                    sHours = timeValue.substring(0, 1);
                    sMinutes = timeValue.substring(1, 3);
                }
                obj.value = DataValidation.timeCheck(sHours, sMinutes);
            }
        }
        return true;
    }
}

// 현재 테마 선택을 저장하고 top/left stylesheet를 한 쌍으로 교체한다.
var dynamicLinkCss = function (srctop, srcleft) {
    localStorage.setItem('theme-top', srctop);
    localStorage.setItem('theme-left', srcleft);
    $('link[href*="/static/css/theme-top"]').remove();
    $('link[href*="/static/css/theme-left"]').remove();

    var linkTop = document.createElement('link');
    linkTop.href = srctop + '.css';
    linkTop.async = false;
    linkTop.rel = 'stylesheet';
    linkTop.type = 'text/css';
    document.head.appendChild(linkTop);

    var linkLeft = document.createElement('link');
    linkLeft.href = srcleft + '.css';
    linkLeft.async = false;
    linkLeft.rel = 'stylesheet';
    linkLeft.type = 'text/css';
    document.head.appendChild(linkLeft);

    $('label[data-load-top-css="' + srctop + '"][data-load-left-css="' + srcleft + '"]')
        .children('input[type=radio]')
        .prop('checked', true);
};


////////////////////////////////////////////////////////////////////////////////
$(document).ready(function () {

    // 다국어 처리 대상
    let _msg_resource = {
        'valid.msg.required': '필수 항목입니다.',
        'valid.msg.remote': '항목을 수정하세요',
        'valid.msg.email': '유효하지 않은 E-Mail주소입니다',
        'valid.msg.url': '유효하지 않은 URL입니다',
        'valid.msg.date': '올바른 날짜를 입력하세요',
        'valid.msg.dateISO': '올바른 날짜를 입력하세요',
        'valid.msg.number': '유효한 숫자가 아닙니다',
        'valid.msg.digits': '숫자만 입력 가능합니다',
        'valid.msg.creditcard': '신용카드 번호가 바르지 않습니다',
        'valid.msg.equalTo': '같은 값을 다시 입력하세요',
        'valid.msg.extension': '올바른 확장자가 아닙니다',
        'valid.msg.maxlength': '{0}자를 넘을 수 없습니다',
        'valid.msg.minlength': '{0} 이상의 값을 입력하세요',
        'valid.msg.rangelength': '문자 길이가 {0} 에서 {1} 사이의 값을 입력하세요',
        'valid.msg.range': '{0} 에서 {1} 사이의 값을 입력하세요',
        'valid.msg.max': '{0} 이하의 값을 입력하세요',
        'valid.msg.min': '{0} 이상의 값을 입력하세요',
        'valid.msg.validrange': '{0}가 {1}보다 높습니다.',
    };

    $.extend(
        $.validator.messages,
        {
            required: ' ' + _msg_resource['valid.msg.required']
            , remote: ' ' + _msg_resource['valid.msg.remote']
            , email: ' ' + _msg_resource['valid.msg.email']
            , url: ' ' + _msg_resource['valid.msg.url']
            , date: ' ' + _msg_resource['valid.msg.date']
            , dateISO: ' ' + _msg_resource['valid.msg.dateISO']
            , number: ' ' + _msg_resource['valid.msg.number']
            , digits: ' ' + _msg_resource['valid.msg.digits']
            , creditcard: ' ' + _msg_resource['valid.msg.creditcard']
            , equalTo: ' ' + _msg_resource['valid.msg.equalTo']
            , extension: ' ' + _msg_resource['valid.msg.extension']
            , maxlength: ' ' + $.validator.format(_msg_resource['valid.msg.maxlength'])
            , minlength: ' ' + $.validator.format(_msg_resource['valid.msg.minlength'])
            , rangelength: ' ' + $.validator.format(_msg_resource['valid.msg.rangelength'])
            , range: ' ' + $.validator.format(_msg_resource['valid.msg.range'])
            , max: ' ' + $.validator.format(_msg_resource['valid.msg.max'])
            , min: ' ' + $.validator.format(_msg_resource['valid.msg.min'])
            , validrange: ' ' + $.validator.format(_msg_resource['valid.msg.validrange'])
        }
    );

    $.validator.setDefaults({
        onkeyup: false,
        onclick: false,
        onfocusout: false,
        focusInvalid: false,
        showErrors: function (errorMap, errorList) {
            if (this.numberOfInvalids()) {
                Alert.alert('', $.trim(errorList[0].message), function () {
                    errorList[0].element.focus();
                });
            }
        }
    });

    JQuery.extends();
    Ajax.enableErrorHandler();
    Ajax.enableProgressBar();
    Alert.init();


    // ready가 해제된 시점의 DOM에 marker 라벨을 한 번 더 적용한다.
    if (userinfo.login_id != '') {
        i18n.applyLabel();
    }

    // 배포시 console.log 제거
    //console.log = function() {};


});
