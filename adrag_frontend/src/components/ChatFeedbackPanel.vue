<template>
  <!-- 2026.11.05(woojin.jung) 추가 - 답변 피드백 의견 패널 (docs/chat_UI-02-08_20261104.html ANS-07) -->
  <section class="feedback-panel" :class="feedback" aria-label="답변 피드백 의견">
    <div v-if="done" class="feedback-done" role="status">
      <i class="fa-solid fa-circle-check"></i> 의견을 보내 주셔서 감사합니다. 답변 품질 개선에 활용하겠습니다.
    </div>
    <template v-else>
      <div class="feedback-head">
        <i :class="`fa-solid fa-thumbs-${feedback === 'like' ? 'up' : 'down'}`"></i>
        <strong>{{ feedback === 'like' ? '어떤 점이 도움이 되었나요?' : '어떤 점이 아쉬웠나요?' }} <small>(선택)</small></strong>
        <button type="button" class="feedback-close" aria-label="의견 닫기" @click="$emit('close')">
          <i class="fa-solid fa-xmark"></i>
        </button>
      </div>
      <div class="feedback-chips" role="group" aria-label="의견 유형">
        <button
          v-for="reason in FEEDBACK_REASONS[feedback]"
          :key="reason.value"
          type="button"
          class="feedback-chip"
          :aria-pressed="selected.includes(reason.value)"
          @click="toggleReason(reason.value)"
        >
          {{ reason.label }}
        </button>
      </div>
      <textarea
        v-model="comment"
        class="feedback-text"
        rows="2"
        maxlength="1000"
        :placeholder="
          feedback === 'like'
            ? '도움이 된 점을 자유롭게 남겨 주세요.'
            : '틀린 부분이나 올바른 값을 알려 주시면 검토 후 문서·답변 개선에 반영합니다.'
        "
      ></textarea>
      <div class="feedback-foot">
        <span class="feedback-scope">
          <i class="fa-solid fa-circle-info"></i>
          질문·답변<template v-if="sourceLabel">과 참고 문서(<b>{{ sourceLabel }}</b>)</template> 정보가 함께 저장됩니다.
        </span>
        <button type="button" class="feedback-submit" :disabled="!canSubmit || pending" @click="submit">
          {{ pending ? '보내는 중...' : '의견 보내기' }}
        </button>
      </div>
    </template>
  </section>
</template>

<script setup>
import { computed, ref } from 'vue';
import { FEEDBACK_REASONS } from '../constants/feedbackReasons';

defineProps({
  feedback: { type: String, required: true },
  done: { type: Boolean, default: false },
  pending: { type: Boolean, default: false },
  sourceLabel: { type: String, default: '' },
});
const emit = defineEmits(['submit', 'close']);

const selected = ref([]);
const comment = ref('');
const canSubmit = computed(() => selected.value.length > 0 || comment.value.trim().length > 0);

const toggleReason = (value) => {
  selected.value = selected.value.includes(value) ? selected.value.filter((v) => v !== value) : [...selected.value, value];
};
const submit = () => emit('submit', { reasons: selected.value, comment: comment.value.trim() || null });
</script>

<style scoped>
.feedback-panel {
  margin-top: 0.75rem;
  padding: 0.85rem 0.95rem;
  border: 1px solid #e2e8f0;
  border-radius: 10px;
  background: #fff;
  animation: feedback-in 0.18s ease-out;
}
.feedback-panel.like {
  border-color: #bfdbfe;
}
.feedback-panel.dislike {
  border-color: #fecaca;
}
@keyframes feedback-in {
  from {
    opacity: 0;
    transform: translateY(-4px);
  }
  to {
    opacity: 1;
    transform: none;
  }
}
.feedback-head {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 0.6rem;
}
.feedback-head > i {
  font-size: 0.9rem;
}
.feedback-panel.like .feedback-head > i {
  color: #2563eb;
}
.feedback-panel.dislike .feedback-head > i {
  color: #dc2626;
}
.feedback-head strong {
  flex: 1;
  font-size: 0.86rem;
  color: #1e293b;
}
.feedback-head strong small {
  font-weight: 400;
  color: #94a3b8;
}
.feedback-close {
  width: 26px;
  height: 26px;
  border: none;
  border-radius: 6px;
  background: transparent;
  color: #94a3b8;
  cursor: pointer;
}
.feedback-close:hover {
  background: #f1f5f9;
  color: #475569;
}
.feedback-chips {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}
.feedback-chip {
  padding: 5px 11px;
  border: 1px solid #e2e8f0;
  border-radius: 999px;
  background: #f8fafc;
  color: #475569;
  font: inherit;
  font-size: 0.8rem;
  cursor: pointer;
  transition:
    background 0.15s,
    border-color 0.15s,
    color 0.15s;
}
.feedback-chip:hover {
  border-color: #cbd5e1;
  background: #f1f5f9;
}
.feedback-chip[aria-pressed='true'] {
  border-color: #2563eb;
  background: #eff6ff;
  color: #1d4ed8;
}
.feedback-panel.dislike .feedback-chip[aria-pressed='true'] {
  border-color: #dc2626;
  background: #fef2f2;
  color: #b91c1c;
}
.feedback-chip[aria-pressed='true']::before {
  content: '\f00c';
  font-family: 'Font Awesome 6 Free';
  font-weight: 900;
  font-size: 0.7rem;
  margin-right: 5px;
}
.feedback-text {
  width: 100%;
  min-height: 64px;
  margin-top: 0.6rem;
  padding: 0.5rem 0.65rem;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  background: #f8fafc;
  color: #1e293b;
  font: inherit;
  font-size: 0.85rem;
  line-height: 1.5;
  resize: vertical;
  outline: none;
}
.feedback-text:focus {
  border-color: #2563eb;
  background: #fff;
}
.feedback-foot {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-top: 0.6rem;
}
.feedback-scope {
  flex: 1;
  min-width: 0;
  font-size: 0.74rem;
  color: #64748b;
}
.feedback-scope b {
  font-weight: 600;
  color: #475569;
}
.feedback-submit {
  padding: 6px 16px;
  border: none;
  border-radius: 8px;
  background: #2563eb;
  color: #fff;
  font: inherit;
  font-size: 0.82rem;
  font-weight: 600;
  cursor: pointer;
  white-space: nowrap;
}
.feedback-submit:hover:not(:disabled) {
  background: #1d4ed8;
}
.feedback-submit:disabled {
  background: #cbd5e1;
  cursor: not-allowed;
}
.feedback-done {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 0.84rem;
  color: #334155;
}
.feedback-done i {
  color: #16a34a;
}
@media (max-width: 768px) {
  .feedback-foot {
    flex-direction: column;
    align-items: stretch;
  }
  .feedback-submit {
    padding: 8px 16px;
  }
}
</style>
