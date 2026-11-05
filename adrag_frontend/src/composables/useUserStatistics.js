import { computed, onMounted, ref, watch } from 'vue';
import { storeToRefs } from 'pinia';
import { useRouter } from 'vue-router';
import { adminApi } from '../api/adminApi';
import { statisticsApi } from '../api/statisticsApi';
import { useAuthStore } from '../stores/authStore';

export const useUserStatistics = () => {
  const router = useRouter();
  const authStore = useAuthStore();
  const { isAdmin, displayName } = storeToRefs(authStore);

  const sidebarOpen = ref(false);
  const selectedPeriod = ref('7');
  const selectedChartPeriod = ref('7');
  const isLoading = ref(false);
  const loadError = ref('');
  const summary = ref(null);
  const usageTrend = ref(null);
  const topKeywords = ref(null);
  const topDocuments = ref(null);
  const flaggedQueries = ref(null);
  const openingDocId = ref(null);
  const docOpenError = ref('');

  const periods = [
    { label: '지난 7일', shortLabel: '7일', value: '7' },
    { label: '최근 30일', shortLabel: '30일', value: '30' },
    { label: '이번 달', shortLabel: '월간', value: 'month' },
  ];

  const periodDaysText = computed(() => {
    if (selectedPeriod.value === 'month') return '이번 달';
    return `최근 ${selectedPeriod.value}일`;
  });

  const chartData = computed(() => {
    const items = usageTrend.value?.items || [];
    return {
      labels: items.map((item) => item.date),
      queries: items.map((item) => Number(item.query_count || 0)),
      costs: items.map((item) => Number(item.cost_usd || 0)),
    };
  });

  const hasChartData = computed(() => chartData.value.queries.some((count) => count > 0));

  const summaryCards = computed(() => {
    const data = summary.value || {};
    const queryCount = data.query_count || {};
    const activeDays = data.active_days || {};
    const satisfaction = data.satisfaction || {};
    const successRate = data.success_rate || {};

    return [
      {
        label: '내 총 질의 수',
        value: formatNumber(queryCount.value),
        trend: changeText(queryCount.change_count, queryCount.change_pct, '건'),
        trendType: trendType(queryCount.change_count),
        color: 'blue',
        icon: 'fa-solid fa-message',
      },
      {
        label: '내 활동 일수',
        value: formatNumber(activeDays.value),
        trend: `${periodDaysText.value} 중 ${formatNumber(activeDays.value)}일 사용`,
        trendType: trendType(activeDays.change_count),
        color: 'green',
        icon: 'fa-solid fa-calendar-check',
      },
      {
        label: '내 만족도',
        value: percentageText(satisfaction.value_pct),
        trend: satisfaction.change_point == null ? '피드백 데이터 없음' : `${signedNumber(satisfaction.change_point)}%p`,
        trendType: trendType(satisfaction.change_point),
        color: 'purple',
        icon: 'fa-solid fa-thumbs-up',
      },
      {
        label: '내 답변 성공률',
        value: percentageText(successRate.value_pct),
        trend: `성공 ${formatNumber(successRate.success_count)}건 / 실패 ${formatNumber(successRate.failure_count)}건`,
        trendType: trendType(successRate.change_point),
        color: 'teal',
        icon: 'fa-solid fa-circle-check',
      },
    ];
  });

  const keywords = computed(() =>
    (topKeywords.value?.items || []).map((item) => ({
      keyword: item.keyword,
      count: Number(item.count || 0),
      ratioPct: clampPercent(item.ratio_pct),
    })),
  );

  const referencedDocs = computed(() =>
    (topDocuments.value?.items || []).map((item) => ({
      documentId: item.document_id,
      documentName: item.document_name || '-',
      collectionName: item.collection_name,
      citationCount: Number(item.citation_count || 0),
      lastCitedAt: item.last_cited_at,
    })),
  );

  const queryIssues = computed(() =>
    (flaggedQueries.value?.items || []).map((item) => ({
      logId: item.log_id,
      queryText: item.query_text,
      issueLabel: item.issue_label || issueTypeLabel(item.issue_types?.[0] || item.outcome_code),
      createdAt: item.created_at,
    })),
  );

  const loadUsageTrend = async () => {
    const res = await statisticsApi.myUsageTrend(selectedChartPeriod.value);
    usageTrend.value = res.data;
  };

  const loadChartStatistics = async () => {
    try {
      await loadUsageTrend();
    } catch {
      usageTrend.value = null;
    }
  };

  const loadAllStatistics = async () => {
    isLoading.value = true;
    loadError.value = '';

    try {
      const [summaryRes, trendRes, keywordRes, documentRes, flaggedRes] = await Promise.all([
        statisticsApi.mySummary(selectedPeriod.value),
        statisticsApi.myUsageTrend(selectedChartPeriod.value),
        statisticsApi.myTopKeywords(selectedPeriod.value, 5),
        statisticsApi.myTopDocuments(selectedPeriod.value, 5),
        statisticsApi.myFlaggedQueries(selectedPeriod.value, 10),
      ]);
      summary.value = summaryRes.data;
      usageTrend.value = trendRes.data;
      topKeywords.value = keywordRes.data;
      topDocuments.value = documentRes.data;
      flaggedQueries.value = flaggedRes.data;
    } catch (err) {
      summary.value = null;
      usageTrend.value = null;
      topKeywords.value = null;
      topDocuments.value = null;
      flaggedQueries.value = null;
      loadError.value = err.response?.data?.detail || err.message || '통계 데이터를 불러오지 못했습니다.';
    } finally {
      isLoading.value = false;
    }
  };

  const logout = async () => {
    await authStore.logoutAny();
    router.push('/login');
  };

  const openOriginalDocument = async (doc) => {
    if (!doc?.documentId || openingDocId.value) return;

    openingDocId.value = doc.documentId;
    docOpenError.value = '';

    try {
      const res = await adminApi.documentFile(doc.documentId);
      const contentType = res.headers?.['content-type'] || 'application/octet-stream';
      const blobUrl = window.URL.createObjectURL(new Blob([res.data], { type: contentType }));
      window.open(blobUrl, '_blank', 'noopener,noreferrer');
      window.setTimeout(() => window.URL.revokeObjectURL(blobUrl), 60000);
    } catch (err) {
      docOpenError.value = err.response?.data?.detail || err.message || '원본 문서를 열 수 없습니다.';
    } finally {
      openingDocId.value = null;
    }
  };

  const trendIcon = (value) => {
    if (value === 'up') return 'fa-solid fa-arrow-trend-up';
    if (value === 'down') return 'fa-solid fa-arrow-trend-down';
    return 'fa-solid fa-minus';
  };

  const docIcon = (filename) => {
    const lower = String(filename || '').toLowerCase();
    if (lower.endsWith('.pdf')) return 'fa-regular fa-file-pdf';
    if (lower.endsWith('.doc') || lower.endsWith('.docx')) return 'fa-regular fa-file-word';
    // 2026.08.27(sooyeon.choi) 수정 - 지원하는 OOXML Excel 확장자 4종으로 통일
    if (/\.(xlsx|xlsm|xltx|xltm)$/.test(lower)) return 'fa-regular fa-file-excel';
    if (lower.endsWith('.ppt') || lower.endsWith('.pptx')) return 'fa-regular fa-file-powerpoint';
    return 'fa-regular fa-file-lines';
  };

  onMounted(loadAllStatistics);
  watch(selectedPeriod, async (period) => {
    if (selectedChartPeriod.value !== period) {
      selectedChartPeriod.value = period;
    }
    await loadAllStatistics();
  });
  watch(selectedChartPeriod, loadChartStatistics);

  return {
    isAdmin,
    displayName,
    sidebarOpen,
    selectedPeriod,
    selectedChartPeriod,
    isLoading,
    loadError,
    periods,
    chartData,
    hasChartData,
    summaryCards,
    keywords,
    referencedDocs,
    queryIssues,
    openingDocId,
    docOpenError,
    loadAllStatistics,
    logout,
    openOriginalDocument,
    trendIcon,
    docIcon,
    formatNumber,
    formatDateTime,
  };
};

const formatNumber = (value) => Number(value || 0).toLocaleString('ko-KR');
const percentageText = (value) => (value == null ? '-' : `${Number(value).toFixed(1).replace(/\.0$/, '')}%`);
const signedNumber = (value) => `${Number(value || 0) > 0 ? '+' : ''}${Number(value || 0).toFixed(1).replace(/\.0$/, '')}`;
const changeText = (count, pct, unit) => {
  if (count == null && pct == null) return '이전 기간 데이터 없음';
  const countText = count == null ? '' : `${signedNumber(count)}${unit}`;
  const pctText = pct == null ? '' : `(${signedNumber(pct)}%)`;
  return [countText, pctText].filter(Boolean).join(' ');
};
const trendType = (value) => {
  const numberValue = Number(value);
  if (Number.isNaN(numberValue) || numberValue === 0) return 'neutral';
  return numberValue > 0 ? 'up' : 'down';
};
const clampPercent = (value) => Math.max(0, Math.min(100, Number(value || 0)));
const issueTypeLabel = (type) => {
  const labels = {
    no_context: '검색 실패',
    retrieval_error: '검색 처리 오류',
    llm_error: '답변 생성 오류',
    system_error: '시스템 오류',
    negative_feedback: '부정 피드백',
  };
  return labels[type] || type || '-';
};
const formatDateTime = (value) => {
  if (!value) return '-';
  const date = new Date(String(value).replace(' ', 'T'));
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString('ko-KR', { dateStyle: 'short', timeStyle: 'short' });
};
