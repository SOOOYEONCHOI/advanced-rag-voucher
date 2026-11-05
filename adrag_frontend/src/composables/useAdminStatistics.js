import { computed, onMounted, ref, watch } from 'vue';
import { storeToRefs } from 'pinia';
import { useRouter } from 'vue-router';
import { statisticsApi } from '../api/statisticsApi';
import { useAuthStore } from '../stores/authStore';

export const useAdminStatistics = () => {
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
  const departmentStats = ref(null);
  const departmentWeeklyTrend = ref(null);
  const topUsers = ref(null);
  const documentHealth = ref(null);

  const periods = [
    { label: '지난 7일', shortLabel: '7일', value: '7' },
    { label: '최근 30일', shortLabel: '30일', value: '30' },
    { label: '이번 달', shortLabel: '월간', value: 'month' },
  ];

  const periodLabel = computed(() => periods.find((period) => period.value === selectedPeriod.value)?.label || selectedPeriod.value);
  const canShowChartStats = computed(() => Boolean(usageTrend.value));

  const activeChart = computed(() => {
    const items = usageTrend.value?.items || [];
    return {
      labels: items.map((item) => item.date),
      queries: items.map((item) => Number(item.query_count || 0)),
      costs: items.map((item) => Number(item.cost_usd || 0)),
    };
  });

  const hasChartData = computed(() => activeChart.value.queries.some((count) => count > 0));

  const summaryCards = computed(() => {
    const data = summary.value || {};
    const queryCount = data.query_count || {};
    const satisfaction = data.satisfaction || {};
    const cost = data.cost || {};
    const flagged = data.flagged_queries || {};

    return [
      {
        label: '총 질의 수',
        value: formatNumber(queryCount.value),
        trend: changeText(queryCount.change_count, queryCount.change_pct, '건'),
        trendType: trendType(queryCount.change_count),
        color: 'blue',
        icon: 'fa-solid fa-message',
      },
      {
        label: '답변 만족도',
        value: percentageText(satisfaction.value_pct),
        trend: satisfaction.change_point == null ? '피드백 데이터 없음' : `${signedNumber(satisfaction.change_point)}%p`,
        trendType: trendType(satisfaction.change_point),
        color: 'purple',
        icon: 'fa-solid fa-thumbs-up',
      },
      {
        label: '예상 API 비용',
        value: cost.total_usd == null ? '-' : `$${Number(cost.total_usd || 0).toFixed(2)}`,
        trend: cost.daily_average_usd == null ? '비용 데이터 없음' : `하루 평균 $${Number(cost.daily_average_usd || 0).toFixed(2)} 소진`,
        trendType: trendType(cost.change_usd),
        color: 'orange',
        icon: 'fa-solid fa-coins',
      },
      {
        label: '주의 질의',
        value: formatNumber(flagged.value),
        trend: changeText(flagged.change_count, flagged.change_pct, '건'),
        trendType: Number(flagged.value || 0) > 0 ? 'down' : 'neutral',
        color: 'red',
        icon: 'fa-solid fa-triangle-exclamation',
      },
    ];
  });

  const keywords = computed(() =>
    (topKeywords.value?.items || []).map((item) => ({
      name: item.keyword,
      count: Number(item.count || 0),
      percent: clampPercent(item.ratio_pct),
    })),
  );

  const referencedDocs = computed(() =>
    (topDocuments.value?.items || []).map((item) => ({
      document_id: item.document_id,
      document_name: item.document_name || '-',
      collection_id: item.collection_id,
      collection_name: item.collection_name,
      citation_count: Number(item.citation_count || 0),
      last_cited_at: item.last_cited_at,
    })),
  );

  const queryIssues = computed(() =>
    (flaggedQueries.value?.items || []).map((item) => ({
      log_id: item.log_id,
      user_id: item.user_id,
      user_name: item.user_name,
      department: item.department,
      query: item.query_text,
      type: item.issue_label || issueTypeLabel(item.issue_types?.[0] || item.outcome_code),
      time: formatDateTime(item.created_at),
      created_at: item.created_at,
    })),
  );

  const departments = computed(() => {
    const items = departmentStats.value?.items || [];
    return items.map((item, index) => ({
      name: item.department || '미지정',
      queryCount: Number(item.query_count || 0),
      satisfaction: item.satisfaction_pct,
      feedbackCount: Number(item.feedback_count || 0),
      percent: clampPercent(item.query_ratio_pct),
      color: departmentColors[index % departmentColors.length],
    }));
  });

  const userRankings = computed(() =>
    (topUsers.value?.items || []).map((item) => ({
      rank: item.rank,
      userId: item.user_id,
      name: item.user_name || item.user_id || '-',
      department: item.department || '-',
      queryCount: Number(item.query_count || 0),
      satisfaction: item.satisfaction_pct,
      feedbackCount: Number(item.feedback_count || 0),
    })),
  );

  const weeklyDepartmentTrend = computed(() => ({
    weeks: departmentWeeklyTrend.value?.weeks || [],
    series: departmentWeeklyTrend.value?.series || [],
  }));

  const documentHealthSummary = computed(() => {
    const healthSummary = documentHealth.value?.summary || {};
    const thresholds = documentHealth.value?.thresholds || {};
    return [
      {
        label: `${formatNumber(thresholds.uncited_days || 60)}일 이상 미참조`,
        value: `${formatNumber(healthSummary.uncited_count)}건`,
        type: 'warn',
        icon: 'fa-solid fa-eye-slash',
      },
      {
        label: '검토 필요',
        value: `${formatNumber(healthSummary.review_overdue_count)}건`,
        type: 'error',
        icon: 'fa-solid fa-triangle-exclamation',
      },
      {
        label: '전체 대상 문서',
        value: `${formatNumber(healthSummary.total_document_count)}건`,
        type: 'info',
        icon: 'fa-solid fa-file-lines',
      },
    ];
  });

  const documentHealthItems = computed(() =>
    (documentHealth.value?.items || []).map((item) => ({
      document_id: item.document_id,
      document_name: item.document_name || '-',
      collection_name: item.collection_name,
      health_status: item.health_status,
      last_cited_at: item.last_cited_at,
      days_since_last_citation: Number(item.days_since_last_citation || 0),
      content_updated_at: item.content_updated_at,
    })),
  );

  const loadPeriodStatistics = async () => {
    isLoading.value = true;
    loadError.value = '';

    try {
      const [summaryRes, keywordRes, documentRes, flaggedRes, departmentRes, userRes] = await Promise.all([
        statisticsApi.adminSummary(selectedPeriod.value),
        statisticsApi.adminTopKeywords(selectedPeriod.value, 5),
        statisticsApi.adminTopDocuments(selectedPeriod.value, 5),
        statisticsApi.adminFlaggedQueries(selectedPeriod.value, 1, 20),
        statisticsApi.adminDepartments(selectedPeriod.value),
        statisticsApi.adminTopUsers(selectedPeriod.value, 10),
      ]);
      summary.value = summaryRes.data;
      topKeywords.value = keywordRes.data;
      topDocuments.value = documentRes.data;
      flaggedQueries.value = flaggedRes.data;
      departmentStats.value = departmentRes.data;
      topUsers.value = userRes.data;
    } catch (err) {
      summary.value = null;
      topKeywords.value = null;
      topDocuments.value = null;
      flaggedQueries.value = null;
      departmentStats.value = null;
      topUsers.value = null;
      loadError.value = err.response?.data?.detail || err.message || '통계 데이터를 불러오지 못했습니다.';
    } finally {
      isLoading.value = false;
    }
  };

  const loadChartStatistics = async () => {
    try {
      const res = await statisticsApi.adminUsageTrend(selectedChartPeriod.value);
      usageTrend.value = res.data;
    } catch {
      usageTrend.value = null;
    }
  };

  const loadStaticStatistics = async () => {
    const [weeklyRes, healthRes] = await Promise.all([
      statisticsApi.adminDepartmentWeeklyTrend(4),
      statisticsApi.adminDocumentHealth(1, 20),
    ]);
    departmentWeeklyTrend.value = weeklyRes.data;
    documentHealth.value = healthRes.data;
  };

  const loadAllStatistics = async () => {
    isLoading.value = true;
    loadError.value = '';

    try {
      const [summaryRes, trendRes, keywordRes, documentRes, flaggedRes, departmentRes, weeklyRes, userRes, healthRes] = await Promise.all([
        statisticsApi.adminSummary(selectedPeriod.value),
        statisticsApi.adminUsageTrend(selectedChartPeriod.value),
        statisticsApi.adminTopKeywords(selectedPeriod.value, 5),
        statisticsApi.adminTopDocuments(selectedPeriod.value, 5),
        statisticsApi.adminFlaggedQueries(selectedPeriod.value, 1, 20),
        statisticsApi.adminDepartments(selectedPeriod.value),
        statisticsApi.adminDepartmentWeeklyTrend(4),
        statisticsApi.adminTopUsers(selectedPeriod.value, 10),
        statisticsApi.adminDocumentHealth(1, 20),
      ]);
      summary.value = summaryRes.data;
      usageTrend.value = trendRes.data;
      topKeywords.value = keywordRes.data;
      topDocuments.value = documentRes.data;
      flaggedQueries.value = flaggedRes.data;
      departmentStats.value = departmentRes.data;
      departmentWeeklyTrend.value = weeklyRes.data;
      topUsers.value = userRes.data;
      documentHealth.value = healthRes.data;
    } catch (err) {
      summary.value = null;
      usageTrend.value = null;
      topKeywords.value = null;
      topDocuments.value = null;
      flaggedQueries.value = null;
      departmentStats.value = null;
      departmentWeeklyTrend.value = null;
      topUsers.value = null;
      documentHealth.value = null;
      loadError.value = err.response?.data?.detail || err.message || '통계 데이터를 불러오지 못했습니다.';
    } finally {
      isLoading.value = false;
    }
  };

  const logout = async () => {
    await authStore.logoutAny();
    router.push('/login');
  };

  const trendIcon = (trend) => {
    if (trend === 'up') return 'fa-solid fa-arrow-trend-up';
    if (trend === 'down') return 'fa-solid fa-arrow-trend-down';
    return 'fa-solid fa-minus';
  };

  const collectionLabel = (collectionName) => collectionName || '-';

  const docIcon = (filename) => {
    const lower = String(filename || '').toLowerCase();
    if (lower.endsWith('.pdf')) return 'fa-regular fa-file-pdf';
    if (lower.endsWith('.doc') || lower.endsWith('.docx')) return 'fa-regular fa-file-word';
    // 2026.08.27(sooyeon.choi) 수정 - 지원하는 OOXML Excel 확장자 4종으로 통일
    if (/\.(xlsx|xlsm|xltx|xltm)$/.test(lower)) return 'fa-regular fa-file-excel';
    if (lower.endsWith('.ppt') || lower.endsWith('.pptx')) return 'fa-regular fa-file-powerpoint';
    return 'fa-regular fa-file-lines';
  };

  const daysClass = (days) => {
    if (days >= 90) return 'days-90';
    if (days >= 60) return 'days-60';
    return 'days-30';
  };

  onMounted(loadAllStatistics);
  watch(selectedPeriod, loadPeriodStatistics);
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
    periodLabel,
    canShowChartStats,
    activeChart,
    hasChartData,
    summaryCards,
    keywords,
    departments,
    weeklyDepartmentTrend,
    userRankings,
    referencedDocs,
    queryIssues,
    documentHealthSummary,
    documentHealthItems,
    loadAllStatistics,
    loadPeriodStatistics,
    loadChartStatistics,
    loadStaticStatistics,
    logout,
    trendIcon,
    collectionLabel,
    docIcon,
    daysClass,
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

const departmentColors = ['#3b82f6', '#10b981', '#8b5cf6', '#f59e0b', '#ef4444', '#14b8a6'];
