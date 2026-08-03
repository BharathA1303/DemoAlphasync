// api.js - AlphaSync Academy API wrapper around the shared axios instance
import api from '../services/api';

export const academyApi = {
    getDashboard: () => api.get('/academy/dashboard').then((res) => res.data),
    getAnalytics: () => api.get('/academy/analytics').then((res) => res.data),
    getMentorWelcome: () => api.get('/academy/mentor/welcome').then((res) => res.data),
    sendMentorMessage: (payload) => api.post('/academy/mentor', payload).then((res) => res.data),
    getFacultyDashboard: () => api.get('/academy/faculty/dashboard').then((res) => res.data),

    // Teacher & Student APIs
    getTeacherStudents: () => api.get('/academy/teacher/students').then((res) => res.data),
    addTeacherStudent: (payload) => api.post('/academy/teacher/students/add', payload).then((res) => res.data),
    removeTeacherStudent: (studentId) => api.delete(`/academy/teacher/students/${studentId}`).then((res) => res.data),
    getStudentLogs: (studentId) => api.get(`/academy/teacher/students/${studentId}/logs`).then((res) => res.data),

    // Challenges APIs
    getChallenges: () => api.get('/academy/challenges').then((res) => res.data),
    createChallenge: (payload) => api.post('/academy/challenges', payload).then((res) => res.data),
    enrollChallenge: (challengeId) => api.post(`/academy/challenges/${challengeId}/enroll`).then((res) => res.data),
    getAssignedTeacherInfo: () => api.get('/academy/student/teacher-info').then((res) => res.data),

    // Admin Matrix APIs
    assignTeacherStudentAdmin: (payload) => api.post('/admin/assign-teacher-student', payload).then((res) => res.data),
    getTeacherStudentMatrixAdmin: () => api.get('/admin/teacher-student-matrix').then((res) => res.data),
};

export default academyApi;

