import api from './api';

const ADMIN_SESSION_STORAGE_KEY = 'alphasync_admin_session';

export function getAdminSessionToken() {
    try {
        return sessionStorage.getItem(ADMIN_SESSION_STORAGE_KEY);
    } catch {
        return null;
    }
}

export function setAdminSessionToken(token) {
    if (!token) return;
    try {
        sessionStorage.setItem(ADMIN_SESSION_STORAGE_KEY, token);
    } catch {
    }
}

export function clearAdminSessionToken() {
    try {
        sessionStorage.removeItem(ADMIN_SESSION_STORAGE_KEY);
    } catch {
    }
}

function withAdminSession(config = {}) {
    const token = getAdminSessionToken();
    const headers = { ...(config.headers || {}) };

    if (token) {
        headers['X-Admin-Session'] = token;
    }

    return {
        ...config,
        headers,
    };
}

function safeUserId(userId) {
    return encodeURIComponent(String(userId || ''));
}

const adminApi = {
    // ── 2FA Auth ────────────────────────────────────────────────────
    getTwoFactorStatus() {
        return api.get('/admin/auth/status');
    },

    setupTwoFactor() {
        return api.post('/admin/auth/setup-2fa');
    },

    enableTwoFactor(code) {
        return api.post('/admin/auth/enable-2fa', { code });
    },

    verifyTwoFactor(code) {
        return api.post('/admin/auth/verify-2fa', { code });
    },

    validateSession() {
        return api.post('/admin/auth/validate-session', {}, withAdminSession());
    },

    // ── Dashboard ───────────────────────────────────────────────────
    getDashboardStats() {
        return api.get('/admin/dashboard/stats', withAdminSession());
    },

    getFeedbackSummary() {
        return api.get('/feedback/admin/summary', withAdminSession());
    },

    getAutoApprovalSetting() {
        return api.get('/admin/settings/auto-approval', withAdminSession());
    },

    setAutoApprovalSetting(enabled) {
        return api.post('/admin/settings/auto-approval', { enabled: Boolean(enabled) }, withAdminSession());
    },

    getDataFeedConfig() {
        return api.get('/admin/settings/data-feed', withAdminSession());
    },

    updateDataFeedConfig(payload) {
        return api.post('/admin/settings/data-feed', payload, withAdminSession());
    },

    // ── User Management ─────────────────────────────────────────────
    listUsers(params = {}) {
        return api.get('/admin/users', withAdminSession({ params }));
    },

    getUserDetail(userId) {
        return api.get(`/admin/users/${safeUserId(userId)}`, withAdminSession());
    },

    updateUserFinancials(userId, payload) {
        return api.post(
            `/admin/users/${safeUserId(userId)}/financials`,
            payload,
            withAdminSession()
        );
    },

    approveUser(userId, durationDays) {
        return api.post(
            `/admin/users/${safeUserId(userId)}/approve`,
            { duration_days: durationDays },
            withAdminSession()
        );
    },

    deactivateUser(userId, reason, totpCode) {
        return api.post(
            `/admin/users/${safeUserId(userId)}/deactivate`,
            { reason, totp_code: totpCode },
            withAdminSession()
        );
    },

    reactivateUser(userId, durationDays) {
        return api.post(
            `/admin/users/${safeUserId(userId)}/reactivate`,
            { duration_days: durationDays },
            withAdminSession()
        );
    },

    setDuration(userId, durationDays) {
        return api.post(
            `/admin/users/${safeUserId(userId)}/set-duration`,
            { duration_days: durationDays },
            withAdminSession()
        );
    },

    setUserGroup(userId, groupId) {
        return api.post(
            `/admin/users/${safeUserId(userId)}/group`,
            { group_id: groupId || null },
            withAdminSession()
        );
    },

    forceLogoutUser(userId) {
        return api.post(
            `/admin/users/${safeUserId(userId)}/force-logout`,
            {},
            withAdminSession()
        );
    },

    deleteUserAccount(userId, totpCode) {
        return api.delete(
            `/admin/users/${safeUserId(userId)}/delete`,
            withAdminSession({ data: { totp_code: String(totpCode || '') } })
        );
    },

    // ── Group Management (root/max) ────────────────────────────────
    listGroups() {
        return api.get('/admin/groups', withAdminSession());
    },

    createGroup(name) {
        return api.post('/admin/groups', { name }, withAdminSession());
    },

    renameGroup(groupId, name) {
        return api.patch(`/admin/groups/${safeUserId(groupId)}`, { name }, withAdminSession());
    },

    deleteGroup(groupId) {
        return api.delete(`/admin/groups/${safeUserId(groupId)}`, withAdminSession());
    },

    generateGroupLink(groupId) {
        return api.post(`/admin/groups/${safeUserId(groupId)}/generate-link`, {}, withAdminSession());
    },

    setGroupAutoApproval(groupId, enabled) {
        return api.post(`/admin/groups/${safeUserId(groupId)}/auto-approval`, { enabled: Boolean(enabled) }, withAdminSession());
    },

    downloadOverallUsersExcel() {
        return api.get('/admin/exports/users/overall', withAdminSession({ responseType: 'blob' }));
    },

    downloadAppliedUsersExcel(params = {}) {
        return api.get('/admin/exports/users/applied', withAdminSession({ params, responseType: 'blob' }));
    },

    // ── Admin Management (root only) ────────────────────────────────
    listAdmins() {
        return api.get('/admin/admins', withAdminSession());
    },

    promoteToAdmin(email, adminLevel = 'manage') {
        return api.post('/admin/admins/promote', { email, admin_level: adminLevel }, withAdminSession());
    },

    updateAdminLevel(adminId, adminLevel) {
        return api.patch(`/admin/admins/${safeUserId(adminId)}/level`, { admin_level: adminLevel }, withAdminSession());
    },

    revokeAdmin(adminId) {
        return api.delete(`/admin/admins/${safeUserId(adminId)}`, withAdminSession());
    },

    // ── Audit Log ───────────────────────────────────────────────────
    getAuditLog(params = {}) {
        return api.get('/admin/audit-log', withAdminSession({ params }));
    },

    // ── Bug Reports ─────────────────────────────────────────────────
    getBugReportStats() {
        return api.get('/bug-reports/admin/dashboard-stats', withAdminSession());
    },

    listBugReports(params = {}) {
        return api.get('/bug-reports/admin/all', withAdminSession({ params }));
    },

    updateBugReportStatus(reportId, payload) {
        return api.post(`/bug-reports/${safeUserId(reportId)}/update-status`, payload, withAdminSession());
    },
};

export default adminApi;
