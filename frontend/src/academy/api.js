// api.js - AlphaSync Academy API wrapper around the shared axios instance
import api from '../services/api';

export const academyApi = {
    getDashboard: () => api.get('/academy/dashboard').then((res) => res.data),
    getAnalytics: () => api.get('/academy/analytics').then((res) => res.data),
    getMentorWelcome: () => api.get('/academy/mentor/welcome').then((res) => res.data),
    sendMentorMessage: (payload) => api.post('/academy/mentor', payload).then((res) => res.data),
    getFacultyDashboard: () => api.get('/academy/faculty/dashboard').then((res) => res.data),
};

export default academyApi;
