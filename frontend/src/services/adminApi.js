import api from './api';

function safeUserId(userId) {
    return encodeURIComponent(String(userId || ''));
}

const adminApi = {
    // ── Dashboard ───────────────────────────────────────────────────
    getDashboardStats() {
        return api.get('/admin/dashboard/stats');
    },

    getFeedbackSummary() {
        return api.get('/feedback/admin/summary');
    },

    getAutoApprovalSetting() {
        return api.get('/admin/settings/auto-approval');
    },

    setAutoApprovalSetting(enabled) {
        return api.post('/admin/settings/auto-approval', { enabled: Boolean(enabled) });
    },

    getDataFeedConfig() {
        return api.get('/admin/settings/data-feed');
    },

    updateDataFeedConfig(payload) {
        return api.post('/admin/settings/data-feed', payload);
    },

    getZebuCredentials() {
        return api.get('/admin/simulation/zebu-credentials');
    },

    saveZebuCredentials(payload) {
        return api.post('/admin/simulation/zebu-credentials', payload);
    },

    importZebuHistory(days = 90) {
        return api.post('/admin/simulation/zebu-import', { days });
    },

    getSimulationStatus() {
        return api.get('/admin/simulation/status');
    },

    seedSimulation({ days = 45, useMock = false, tryRealFirst = true } = {}) {
        return api.post('/admin/simulation/seed', {
            days,
            use_mock: useMock,
            try_real_first: tryRealFirst,
        });
    },

    // ── User Management ─────────────────────────────────────────────
    listUsers(params = {}) {
        return api.get('/admin/users', { params });
    },

    getUserDetail(userId) {
        return api.get(`/admin/users/${safeUserId(userId)}`);
    },

    updateUserFinancials(userId, payload) {
        return api.post(`/admin/users/${safeUserId(userId)}/financials`, payload);
    },

    approveUser(userId, durationDays) {
        return api.post(`/admin/users/${safeUserId(userId)}/approve`, { duration_days: durationDays });
    },

    deactivateUser(userId, reason) {
        return api.post(`/admin/users/${safeUserId(userId)}/deactivate`, { reason });
    },

    reactivateUser(userId, durationDays) {
        return api.post(`/admin/users/${safeUserId(userId)}/reactivate`, { duration_days: durationDays });
    },

    setDuration(userId, durationDays) {
        return api.post(`/admin/users/${safeUserId(userId)}/set-duration`, { duration_days: durationDays });
    },

    setUserGroup(userId, groupId) {
        return api.post(`/admin/users/${safeUserId(userId)}/group`, { group_id: groupId || null });
    },

    forceLogoutUser(userId) {
        return api.post(`/admin/users/${safeUserId(userId)}/force-logout`, {});
    },

    deleteUserAccount(userId) {
        return api.delete(`/admin/users/${safeUserId(userId)}/delete`);
    },

    // ── Group Management (root/max) ────────────────────────────────
    listGroups() {
        return api.get('/admin/groups');
    },

    createGroup(name) {
        return api.post('/admin/groups', { name });
    },

    renameGroup(groupId, name) {
        return api.patch(`/admin/groups/${safeUserId(groupId)}`, { name });
    },

    deleteGroup(groupId) {
        return api.delete(`/admin/groups/${safeUserId(groupId)}`);
    },

    generateGroupLink(groupId) {
        return api.post(`/admin/groups/${safeUserId(groupId)}/generate-link`, {});
    },

    setGroupAutoApproval(groupId, enabled) {
        return api.post(`/admin/groups/${safeUserId(groupId)}/auto-approval`, { enabled: Boolean(enabled) });
    },

    downloadOverallUsersExcel() {
        return api.get('/admin/exports/users/overall', { responseType: 'blob' });
    },

    downloadAppliedUsersExcel(params = {}) {
        return api.get('/admin/exports/users/applied', { params, responseType: 'blob' });
    },

    // ── Admin Management (root only) ────────────────────────────────
    listAdmins() {
        return api.get('/admin/admins');
    },

    promoteToAdmin(email, adminLevel = 'manage') {
        return api.post('/admin/admins/promote', { email, admin_level: adminLevel });
    },

    updateAdminLevel(adminId, adminLevel) {
        return api.patch(`/admin/admins/${safeUserId(adminId)}/level`, { admin_level: adminLevel });
    },

    revokeAdmin(adminId) {
        return api.delete(`/admin/admins/${safeUserId(adminId)}`);
    },

    // ── Audit Log ───────────────────────────────────────────────────
    getAuditLog(params = {}) {
        return api.get('/admin/audit-log', { params });
    },

    // ── Bug Reports ─────────────────────────────────────────────────
    getBugReportStats() {
        return api.get('/bug-reports/admin/dashboard-stats');
    },

    listBugReports(params = {}) {
        return api.get('/bug-reports/admin/all', { params });
    },

    updateBugReportStatus(reportId, payload) {
        return api.post(`/bug-reports/${safeUserId(reportId)}/update-status`, payload);
    },
};

export default adminApi;
