// 2026.11.09(woojin.jung) 추가 - 관리 화면 대화상자 공통 키보드 처리(이력·복원 창과 같은 동작)
//   Esc → onEscape, Tab → 창(event.currentTarget) 안에서만 포커스 순환
export const handleDialogKeydown = (event, onEscape) => {
  if (event.key === 'Escape') {
    event.stopPropagation();
    onEscape();
    return;
  }
  if (event.key !== 'Tab') return;
  const items = [...event.currentTarget.querySelectorAll('button:not(:disabled), input:not(:disabled)')];
  if (!items.length) return;
  const first = items[0];
  const last = items[items.length - 1];
  const active = document.activeElement;
  if (event.shiftKey && (active === first || !items.includes(active))) {
    event.preventDefault();
    last.focus();
  } else if (!event.shiftKey && (active === last || !items.includes(active))) {
    event.preventDefault();
    first.focus();
  }
};

// 창을 닫은 뒤 창을 연 버튼으로 포커스를 돌린다(버튼이 사라졌거나 비활성이면 건너뜀)
export const restoreFocus = (el) => {
  if (el?.isConnected && !el.disabled) el.focus();
};
