// 2026.11.13(woojin.jung) 추가 - 일반 사용자 비밀번호 규칙
//   서버 규칙(adrag_backend/app/utils/password_policy.py)과 같게 유지한다.
export const PASSWORD_MIN_LENGTH = 8;
// bcrypt 처리 한도(서버 MAX_PASSWORD_BYTES). 한글은 1자에 3바이트
export const PASSWORD_MAX_BYTES = 72;
export const PASSWORD_TOO_LONG_TEXT = '비밀번호가 너무 깁니다.';
export const isPasswordTooLong = (pw) => new TextEncoder().encode(pw).length > PASSWORD_MAX_BYTES;

export const PASSWORD_RULE_TEXT = `영문과 숫자를 포함해 ${PASSWORD_MIN_LENGTH}자 이상`;

// 비밀번호 변경 화면 체크리스트: test(새 비밀번호, { userId, currentPassword })
export const PASSWORD_RULES = [
  { label: `${PASSWORD_MIN_LENGTH}자 이상`, test: (pw) => pw.length >= PASSWORD_MIN_LENGTH },
  { label: '영문과 숫자를 모두 포함', test: (pw) => /[A-Za-z]/.test(pw) && /\d/.test(pw) },
  { label: '현재 비밀번호·아이디와 다름', test: (pw, { userId = '', currentPassword = '' } = {}) => pw !== userId && pw !== currentPassword },
];

// 사용자 추가처럼 체크리스트 없이 한 줄 오류만 보여줄 때 사용(현재 비밀번호 비교 없음)
export const isPasswordPolicyMet = (pw) => PASSWORD_RULES[0].test(pw) && PASSWORD_RULES[1].test(pw);
