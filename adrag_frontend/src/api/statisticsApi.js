import { adminAuthConfig, authConfig, http } from './http';

export const statisticsApi = {
  dashboard(days = 30) {
    return http.get('/statistics/dashboard', authConfig({ params: { days } }));
  },
  mySummary(period = '7') {
    return http.get('/stats/me/summary', authConfig({ params: { period } }));
  },
  myUsageTrend(period = '7') {
    return http.get('/stats/me/usage-trend', authConfig({ params: { period } }));
  },
  myTopKeywords(period = '7', limit = 5) {
    return http.get('/stats/me/top-keywords', authConfig({ params: { period, limit } }));
  },
  myTopDocuments(period = '7', limit = 5) {
    return http.get('/stats/me/top-documents', authConfig({ params: { period, limit } }));
  },
  myFlaggedQueries(period = '7', limit = 10) {
    return http.get('/stats/me/flagged-queries', authConfig({ params: { period, limit } }));
  },
  adminSummary(period = '7') {
    return http.get('/admin/stats/summary', adminAuthConfig({ params: { period } }));
  },
  adminUsageTrend(period = '7') {
    return http.get('/admin/stats/usage-trend', adminAuthConfig({ params: { period } }));
  },
  adminTopKeywords(period = '7', limit = 5) {
    return http.get('/admin/stats/top-keywords', adminAuthConfig({ params: { period, limit } }));
  },
  adminTopDocuments(period = '7', limit = 5) {
    return http.get('/admin/stats/top-documents', adminAuthConfig({ params: { period, limit } }));
  },
  adminFlaggedQueries(period = '7', page = 1, pageSize = 20) {
    return http.get('/admin/stats/flagged-queries', adminAuthConfig({ params: { period, page, page_size: pageSize } }));
  },
  adminDepartments(period = '7') {
    return http.get('/admin/stats/departments', adminAuthConfig({ params: { period } }));
  },
  adminDepartmentWeeklyTrend(weeks = 4) {
    return http.get('/admin/stats/departments/weekly-trend', adminAuthConfig({ params: { weeks } }));
  },
  adminTopUsers(period = '7', limit = 10) {
    return http.get('/admin/stats/top-users', adminAuthConfig({ params: { period, limit } }));
  },
  adminDocumentHealth(page = 1, pageSize = 20) {
    return http.get('/admin/stats/document-health', adminAuthConfig({ params: { page, page_size: pageSize } }));
  },
};
