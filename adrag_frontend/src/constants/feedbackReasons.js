// 2026.11.05(woojin.jung) 추가 - 답변 피드백 사유 (코드 목록은 adrag_backend/app/routes/query.py FEEDBACK_REASONS와 같아야 함)
export const FEEDBACK_REASONS = {
  like: [
    { value: 'accurate', label: '정확한 수치·절차' },
    { value: 'source_clear', label: '출처 확인이 쉬움' },
    { value: 'image_helpful', label: '관련 이미지가 유용함' },
    { value: 'actionable', label: '현장에 바로 적용 가능' },
    { value: 'other', label: '기타' },
  ],
  dislike: [
    { value: 'incorrect', label: '수치·내용이 틀림' },
    { value: 'wrong_source', label: '출처·위치가 맞지 않음' },
    { value: 'wrong_image', label: '이미지가 맞지 않음' },
    { value: 'irrelevant', label: '질문과 관련 없음' },
    { value: 'insufficient', label: '내용이 부족함' },
    { value: 'other', label: '기타' },
  ],
};

export const feedbackReasonLabel = (feedback, value) =>
  FEEDBACK_REASONS[feedback]?.find((reason) => reason.value === value)?.label || value;
