/* 이미지 상세 보기 — 휠: 커서 자리를 기준으로 확대·축소, 끌기: 확대한 이미지 이동, 더블클릭: 원래 크기.
 * 대상(target)에 transform 을 건다. 겹침(BBOX·Polygon)은 대상 안에 % 좌표로 있어 함께 커진다.
 * 라벨링은 이것을 쓰지 않는다(px 배율 + 스크롤, data/labeling.html). */
(function (window) {
  "use strict";

  var MAX_SCALE = 8;
  var WHEEL_RATE = 0.002; // deltaY 1 당 지수 배율. 마우스 휠 한 칸(100) ≈ 1.22배

  function attach(viewport, target) {
    if (viewport.imageZoom) { return viewport.imageZoom; }
    var state = { scale: 1, x: 0, y: 0 };
    var drag = null;
    viewport.classList.add("image-zoom-viewport");
    viewport.title = "휠로 확대·축소하고, 끌어서 옮기고, 더블클릭하면 원래 크기로 돌아갑니다.";
    target.style.transformOrigin = "0 0";

    // 확대한 그림이 원래 칸을 늘 덮게 이동 범위를 막는다(빈 곳으로 밀려나지 않는다).
    function apply() {
      var w = target.offsetWidth, h = target.offsetHeight;
      state.x = Math.min(0, Math.max(w * (1 - state.scale), state.x));
      state.y = Math.min(0, Math.max(h * (1 - state.scale), state.y));
      target.style.transform = state.scale === 1 ? "" : "translate(" + state.x + "px, " + state.y + "px) scale(" + state.scale + ")";
      viewport.classList.toggle("is-zoomed", state.scale > 1);
    }

    function reset() {
      state = { scale: 1, x: 0, y: 0 };
      drag = null;
      viewport.classList.remove("is-dragging");
      apply();
    }

    viewport.addEventListener("wheel", function (event) {
      var next = Math.min(MAX_SCALE, Math.max(1, state.scale * Math.exp(-event.deltaY * WHEEL_RATE)));
      if (next === state.scale) {
        if (state.scale > 1) { event.preventDefault(); } // 최대에서 더 키우려는 휠은 삼킨다
        return; // 원래 크기에서 줄이는 휠은 화면 스크롤에 맡긴다
      }
      event.preventDefault();
      // 커서 아래 점(대상 기준 좌표 u)이 확대 뒤에도 커서 아래 남도록 x' = 커서 - 원위치 - u·s'
      var rect = target.getBoundingClientRect();
      var ux = (event.clientX - rect.left) / state.scale, uy = (event.clientY - rect.top) / state.scale;
      var originX = rect.left - state.x, originY = rect.top - state.y;
      state.x = event.clientX - originX - ux * next;
      state.y = event.clientY - originY - uy * next;
      state.scale = next;
      apply();
    }, { passive: false });

    viewport.addEventListener("pointerdown", function (event) {
      if (state.scale === 1 || event.button !== 0) { return; }
      event.preventDefault();
      drag = { id: event.pointerId, x: event.clientX - state.x, y: event.clientY - state.y };
      viewport.setPointerCapture(event.pointerId);
      viewport.classList.add("is-dragging");
    });
    viewport.addEventListener("pointermove", function (event) {
      if (!drag || event.pointerId !== drag.id) { return; }
      state.x = event.clientX - drag.x;
      state.y = event.clientY - drag.y;
      apply();
    });
    function endDrag(event) {
      if (!drag || event.pointerId !== drag.id) { return; }
      drag = null;
      viewport.classList.remove("is-dragging");
    }
    viewport.addEventListener("pointerup", endDrag);
    viewport.addEventListener("pointercancel", endDrag);
    viewport.addEventListener("dblclick", reset);
    viewport.addEventListener("dragstart", function (event) { event.preventDefault(); });
    if (target.tagName === "IMG") { target.addEventListener("load", reset); }

    viewport.imageZoom = { reset: reset, scale: function () { return state.scale; } };
    return viewport.imageZoom;
  }

  window.ImageZoom = { attach: attach };
}(window));
