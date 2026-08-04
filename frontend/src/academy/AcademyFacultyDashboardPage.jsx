// AcademyFacultyDashboardPage.jsx - Comprehensive Teacher Control Center & Student Performance Inspector
import { useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Users, BookOpen, TrendingUp, Target, Search, UserPlus, Eye, Plus, Award, AlertCircle, FileText, Check, X, Shield, Activity } from 'lucide-react';
import academyApi from './api';
import StatTile from './components/StatTile';
import { Skeleton } from '../components/ui';
import { toast } from 'react-hot-toast';

export default function AcademyFacultyDashboardPage() {
    const navigate = useNavigate();
    const [data, setData] = useState(null);
    const [assignedStudents, setAssignedStudents] = useState([]);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState(null);
    const [query, setQuery] = useState('');

    const handleTestRunChallenge = (challenge) => {
        toast.success(`Launching Test-Run Sandbox for "${challenge.title || 'Challenge'}". Trade with practice capital!`);
        navigate('/terminal?mode=test_run_preview');
    };

    // Modals & Drawers
    const [showAddStudent, setShowAddStudent] = useState(false);
    const [addEmail, setAddEmail] = useState('');
    const [addNotes, setAddNotes] = useState('');
    const [adding, setAdding] = useState(false);

    const [showCreateChallenge, setShowCreateChallenge] = useState(false);
    const [chTitle, setChTitle] = useState('');
    const [chDesc, setChDesc] = useState('');
    const [chCategory, setChCategory] = useState('Trading & Risk');
    const [chMetric, setChMetric] = useState('pnl');
    const [chTarget, setChTarget] = useState('2000');
    const [creatingCh, setCreatingCh] = useState(false);

    const [selectedStudent, setSelectedStudent] = useState(null);
    const [studentLogs, setStudentLogs] = useState(null);
    const [loadingLogs, setLoadingLogs] = useState(false);

    const loadDashboardData = async () => {
        try {
            setLoading(true);
            const [facRes, studRes] = await Promise.all([
                academyApi.getFacultyDashboard().catch(() => null),
                academyApi.getTeacherStudents().catch(() => ({ students: [] })),
            ]);
            setData(facRes || { stats: { total_students: 0, active_courses: 0, avg_class_progress: 0, avg_quiz_score: 0 }, courses: [], roster: [] });
            setAssignedStudents(studRes.students || []);
        } catch (err) {
            setError('Could not load teacher dashboard.');
        } finally {
            setLoading(false);
        }
    };

    useEffect(() => {
        loadDashboardData();
    }, []);

    const handleAddStudentSubmit = async (e) => {
        e.preventDefault();
        if (!addEmail.trim()) {
            toast.error('Please enter student email');
            return;
        }
        try {
            setAdding(true);
            const res = await academyApi.addTeacherStudent({ student_email: addEmail.trim(), notes: addNotes });
            toast.success(res.message || 'Student added to your roster!');
            setAddEmail('');
            setAddNotes('');
            setShowAddStudent(false);
            loadDashboardData();
        } catch (err) {
            toast.error(err.response?.data?.detail || 'Failed to add student.');
        } finally {
            setAdding(false);
        }
    };

    const handleCreateChallengeSubmit = async (e) => {
        e.preventDefault();
        if (!chTitle.trim() || !chDesc.trim()) {
            toast.error('Please fill in title and description');
            return;
        }
        try {
            setCreatingCh(true);
            await academyApi.createChallenge({
                title: chTitle,
                description: chDesc,
                category: chCategory,
                target_metric: chMetric,
                target_value: parseFloat(chTarget) || 1000,
                reward_points: 200,
            });
            toast.success('Trading challenge created successfully!');
            setShowCreateChallenge(false);
            setChTitle('');
            setChDesc('');
        } catch (err) {
            toast.error(err.response?.data?.detail || 'Failed to create challenge.');
        } finally {
            setCreatingCh(false);
        }
    };

    const handleInspectStudentLogs = async (student) => {
        setSelectedStudent(student);
        setLoadingLogs(true);
        try {
            const logs = await academyApi.getStudentLogs(student.student_id);
            setStudentLogs(logs);
        } catch (err) {
            toast.error('Could not fetch student logs.');
            setStudentLogs(null);
        } finally {
            setLoadingLogs(false);
        }
    };

    const filteredAssignedStudents = useMemo(() => {
        const q = query.trim().toLowerCase();
        if (!q) return assignedStudents;
        return assignedStudents.filter(s =>
            s.full_name?.toLowerCase().includes(q) ||
            s.email?.toLowerCase().includes(q)
        );
    }, [assignedStudents, query]);

    if (loading) {
        return (
            <div className="p-6 space-y-4">
                <Skeleton variant="text" width="240px" height="28px" />
                <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
                    {Array.from({ length: 4 }).map((_, i) => <Skeleton key={i} variant="rect" height="90px" />)}
                </div>
                <Skeleton variant="rect" height="300px" />
            </div>
        );
    }

    const { stats, courses } = data || {};

    return (
        <div className="p-6 space-y-6 max-w-7xl mx-auto">
            {/* Top Bar Header */}
            <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 border-b border-edge/10 pb-4">
                <div>
                    <div className="flex items-center gap-3">
                        <h1 className="text-2xl font-bold text-heading font-display">Teacher Dashboard</h1>
                        <span className="px-2.5 py-0.5 rounded-full text-xs font-semibold bg-violet-500/20 text-violet-400 border border-violet-500/30">
                            TEACHER / FACULTY ROLE
                        </span>
                    </div>
                    <p className="text-sm text-text-secondary mt-1">
                        Monitor assigned students, inspect trading execution logs, assign financial challenges, and review performance.
                    </p>
                </div>
                <div className="flex items-center gap-3">
                    <button
                        onClick={() => setShowAddStudent(true)}
                        className="flex items-center gap-2 px-3.5 py-2 rounded-xl bg-brand-primary text-surface-950 font-medium text-xs hover:bg-brand-primary/90 transition-all shadow-md shadow-brand-primary/10"
                    >
                        <UserPlus className="h-4 w-4" />
                        <span>Add Student</span>
                    </button>
                    <button
                        onClick={() => setShowCreateChallenge(true)}
                        className="flex items-center gap-2 px-3.5 py-2 rounded-xl bg-surface-800 border border-edge/10 text-heading font-medium text-xs hover:bg-surface-700 transition-all"
                    >
                        <Plus className="h-4 w-4 text-violet-400" />
                        <span>Create Challenge</span>
                    </button>
                </div>
            </div>

            {/* Quick Stat Tiles */}
            <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
                <StatTile icon={Users} label="Assigned Students" value={assignedStudents.length || stats?.total_students || 0} accentClass="text-accent-blue" />
                <StatTile icon={BookOpen} label="Active Courses" value={courses?.length || 0} accentClass="text-brand-primary" />
                <StatTile icon={TrendingUp} label="Avg Win Rate" value={`${assignedStudents.length > 0 ? (assignedStudents.reduce((acc, s) => acc + (s.trading_stats?.win_rate || 0), 0) / assignedStudents.length).toFixed(1) : 0}%`} accentClass="text-profit" />
                <StatTile icon={Target} label="Avg Quiz Score" value={`${stats?.avg_quiz_score || 0}%`} accentClass="text-accent-purple" />
            </div>

            {/* Main Assigned Students Table & Log Monitor */}
            <div className="rounded-xl border border-edge/10 bg-surface-900/80 backdrop-blur-md p-5 space-y-4">
                <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
                    <div>
                        <h2 className="text-base font-bold text-heading flex items-center gap-2">
                            <Shield className="h-4 w-4 text-brand-primary" />
                            <span>My Assigned Student Roster ({assignedStudents.length})</span>
                        </h2>
                        <p className="text-xs text-text-secondary">Students directly assigned to your class. Click "Inspect Logs" for execution history.</p>
                    </div>
                    <div className="relative w-full sm:w-64">
                        <Search className="h-3.5 w-3.5 absolute left-3 top-1/2 -translate-y-1/2 text-text-muted" />
                        <input
                            value={query}
                            onChange={(e) => setQuery(e.target.value)}
                            placeholder="Filter by name or email..."
                            className="w-full h-8 pl-9 pr-3 rounded-lg border border-edge/10 bg-surface-950/60 text-xs text-heading placeholder:text-text-muted focus:outline-none focus:border-brand-primary"
                        />
                    </div>
                </div>

                {filteredAssignedStudents.length === 0 ? (
                    <div className="py-12 text-center rounded-xl border border-dashed border-edge/10 bg-surface-950/30">
                        <Users className="h-8 w-8 mx-auto text-text-muted mb-2" />
                        <p className="text-sm font-medium text-heading">No students on your roster yet</p>
                        <p className="text-xs text-text-secondary max-w-md mx-auto mt-1 mb-4">
                            Click "Add Student" above to enter a student's email or ask your Administrator to pair students with your account.
                        </p>
                        <button
                            onClick={() => setShowAddStudent(true)}
                            className="px-4 py-2 rounded-lg bg-brand-primary/20 text-brand-primary border border-brand-primary/30 text-xs font-semibold hover:bg-brand-primary/30 transition-all"
                        >
                            + Add First Student
                        </button>
                    </div>
                ) : (
                    <div className="overflow-x-auto">
                        <table className="w-full text-xs text-left">
                            <thead>
                                <tr className="uppercase tracking-wider text-text-muted border-b border-edge/10 bg-surface-950/40">
                                    <th className="py-3 px-4 font-semibold">Student</th>
                                    <th className="py-3 px-4 font-semibold">Total PnL</th>
                                    <th className="py-3 px-4 font-semibold">Win Rate</th>
                                    <th className="py-3 px-4 font-semibold">Total Trades</th>
                                    <th className="py-3 px-4 font-semibold">Quiz Score</th>
                                    <th className="py-3 px-4 font-semibold">Study Time</th>
                                    <th className="py-3 px-4 font-semibold text-right">Actions</th>
                                </tr>
                            </thead>
                            <tbody className="divide-y divide-edge/5">
                                {filteredAssignedStudents.map((s) => (
                                    <tr key={s.student_id} className="hover:bg-surface-800/40 transition-colors">
                                        <td className="py-3 px-4">
                                            <div className="font-semibold text-heading">{s.full_name}</div>
                                            <div className="text-[11px] text-text-secondary">{s.email}</div>
                                        </td>
                                        <td className="py-3 px-4 font-medium">
                                            <span className={s.trading_stats.total_pnl >= 0 ? 'text-profit' : 'text-loss'}>
                                                {s.trading_stats.total_pnl >= 0 ? '+' : ''}${s.trading_stats.total_pnl.toLocaleString()}
                                            </span>
                                        </td>
                                        <td className="py-3 px-4 text-heading font-medium">
                                            {s.trading_stats.win_rate}%
                                        </td>
                                        <td className="py-3 px-4 text-text-secondary">
                                            {s.trading_stats.total_trades} orders
                                        </td>
                                        <td className="py-3 px-4 text-accent-purple font-medium">
                                            {s.academy_stats.avg_quiz_score}%
                                        </td>
                                        <td className="py-3 px-4 text-text-secondary">
                                            {s.academy_stats.total_study_minutes} mins
                                        </td>
                                        <td className="py-3 px-4 text-right">
                                            <button
                                                onClick={() => handleInspectStudentLogs(s)}
                                                className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-brand-primary/10 text-brand-primary border border-brand-primary/20 text-xs font-medium hover:bg-brand-primary/20 transition-all"
                                            >
                                                <Eye className="h-3.5 w-3.5" />
                                                <span>Inspect Logs</span>
                                            </button>
                                        </td>
                                    </tr>
                                ))}
                            </tbody>
                        </table>
                    </div>
                )}
            </div>

            {/* Courses Overview & Authored Challenge Test-Run Previews */}
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
                <div className="rounded-xl border border-edge/10 bg-surface-900/60 p-5 space-y-3">
                    <h2 className="text-sm font-bold text-heading flex items-center gap-2">
                        <BookOpen className="h-4 w-4 text-accent-blue" />
                        <span>Catalog Courses Taught</span>
                    </h2>
                    <div className="space-y-3">
                        {courses?.map((c) => (
                            <div key={c.course_id} className="rounded-xl border border-edge/10 bg-surface-950/60 p-4 space-y-2">
                                <div className="flex items-center justify-between">
                                    <span className="text-[10px] uppercase font-bold tracking-wider px-2 py-0.5 rounded bg-brand-primary/10 text-brand-primary">{c.category}</span>
                                    <span className="text-xs text-text-muted">{c.student_count} Students</span>
                                </div>
                                <p className="text-sm font-semibold text-heading">{c.title}</p>
                                <div className="space-y-1">
                                    <div className="flex justify-between text-xs text-text-secondary">
                                        <span>Class Progress</span>
                                        <span>{c.avg_progress}%</span>
                                    </div>
                                    <div className="h-1.5 w-full rounded-full bg-surface-800 overflow-hidden">
                                        <div className="h-full rounded-full bg-brand-primary" style={{ width: `${c.avg_progress}%` }} />
                                    </div>
                                </div>
                            </div>
                        ))}
                    </div>
                </div>

                {/* Faculty Challenge Sandbox Preview */}
                <div className="rounded-xl border border-edge/10 bg-surface-900/60 p-5 space-y-3">
                    <div className="flex items-center justify-between">
                        <h2 className="text-sm font-bold text-heading flex items-center gap-2">
                            <Target className="h-4 w-4 text-violet-400" />
                            <span>Authored Challenge Test-Runs</span>
                        </h2>
                        <button
                            onClick={() => setShowCreateChallenge(true)}
                            className="text-xs font-semibold text-violet-400 hover:text-violet-300 transition-colors"
                        >
                            + New Challenge
                        </button>
                    </div>
                    <p className="text-xs text-text-secondary">Test-run your authored financial challenges using your practice portfolio before publishing to students.</p>
                    
                    <div className="space-y-2">
                        {[
                            { id: 1, title: 'Risk-Managed Intraday Challenge', target: 'PnL > ₹2,000 with Max DD < 2%', category: 'Trading & Risk' },
                            { id: 2, title: 'Option Hedging Sandbox', target: 'Delta Neutral Strategy Execution', category: 'Options & Hedging' }
                        ].map((ch) => (
                            <div key={ch.id} className="p-3.5 rounded-xl border border-edge/10 bg-surface-950/60 flex items-center justify-between gap-3">
                                <div>
                                    <div className="text-xs font-bold text-heading">{ch.title}</div>
                                    <div className="text-[10px] text-text-muted font-mono">{ch.category} • {ch.target}</div>
                                </div>
                                <button
                                    onClick={() => handleTestRunChallenge(ch)}
                                    className="px-3 py-1.5 rounded-lg bg-violet-500/20 text-violet-300 border border-violet-500/30 text-xs font-bold hover:bg-violet-500/30 transition-all flex items-center gap-1.5 cursor-pointer flex-shrink-0"
                                >
                                    <Activity className="w-3.5 h-3.5 text-violet-400" />
                                    <span>Test-Run Preview</span>
                                </button>
                            </div>
                        ))}
                    </div>
                </div>
            </div>

            {/* MODAL 1: Add Student Modal */}
            {showAddStudent && (
                <div className="fixed inset-0 z-50 bg-black/70 backdrop-blur-sm flex items-center justify-center p-4">
                    <div className="bg-surface-900 border border-edge/10 rounded-2xl max-w-md w-full p-6 space-y-4 shadow-2xl">
                        <div className="flex items-center justify-between border-b border-edge/10 pb-3">
                            <div className="flex items-center gap-2">
                                <UserPlus className="h-5 w-5 text-brand-primary" />
                                <h3 className="text-base font-bold text-heading">Add Student to Roster</h3>
                            </div>
                            <button onClick={() => setShowAddStudent(false)} className="text-text-muted hover:text-heading">
                                <X className="h-5 w-5" />
                            </button>
                        </div>
                        <form onSubmit={handleAddStudentSubmit} className="space-y-4">
                            <div>
                                <label className="block text-xs font-semibold text-heading mb-1">Student Email Address *</label>
                                <input
                                    type="email"
                                    required
                                    value={addEmail}
                                    onChange={(e) => setAddEmail(e.target.value)}
                                    placeholder="e.g. student@alphasync.ac"
                                    className="w-full h-10 px-3 rounded-xl border border-edge/10 bg-surface-950 text-xs text-heading placeholder:text-text-muted focus:outline-none focus:border-brand-primary"
                                />
                            </div>
                            <div>
                                <label className="block text-xs font-semibold text-heading mb-1">Notes / Group Name</label>
                                <input
                                    type="text"
                                    value={addNotes}
                                    onChange={(e) => setAddNotes(e.target.value)}
                                    placeholder="e.g. Algo Trading Batch 2026"
                                    className="w-full h-10 px-3 rounded-xl border border-edge/10 bg-surface-950 text-xs text-heading placeholder:text-text-muted focus:outline-none focus:border-brand-primary"
                                />
                            </div>
                            <div className="flex justify-end gap-2 pt-2">
                                <button
                                    type="button"
                                    onClick={() => setShowAddStudent(false)}
                                    className="px-4 py-2 rounded-xl bg-surface-800 text-xs text-heading hover:bg-surface-700"
                                >
                                    Cancel
                                </button>
                                <button
                                    type="submit"
                                    disabled={adding}
                                    className="px-4 py-2 rounded-xl bg-brand-primary text-surface-950 text-xs font-bold hover:bg-brand-primary/90 disabled:opacity-50"
                                >
                                    {adding ? 'Adding...' : 'Confirm & Add'}
                                </button>
                            </div>
                        </form>
                    </div>
                </div>
            )}

            {/* MODAL 2: Create Challenge Modal */}
            {showCreateChallenge && (
                <div className="fixed inset-0 z-50 bg-black/70 backdrop-blur-sm flex items-center justify-center p-4">
                    <div className="bg-surface-900 border border-edge/10 rounded-2xl max-w-lg w-full p-6 space-y-4 shadow-2xl">
                        <div className="flex items-center justify-between border-b border-edge/10 pb-3">
                            <div className="flex items-center gap-2">
                                <Award className="h-5 w-5 text-violet-400" />
                                <h3 className="text-base font-bold text-heading">Create Financial Trading Challenge</h3>
                            </div>
                            <button onClick={() => setShowCreateChallenge(false)} className="text-text-muted hover:text-heading">
                                <X className="h-5 w-5" />
                            </button>
                        </div>
                        <form onSubmit={handleCreateChallengeSubmit} className="space-y-3">
                            <div>
                                <label className="block text-xs font-semibold text-heading mb-1">Challenge Title *</label>
                                <input
                                    type="text"
                                    required
                                    value={chTitle}
                                    onChange={(e) => setChTitle(e.target.value)}
                                    placeholder="e.g. Risk Guard: Max Drawdown < 4%"
                                    className="w-full h-9 px-3 rounded-xl border border-edge/10 bg-surface-950 text-xs text-heading placeholder:text-text-muted focus:outline-none focus:border-brand-primary"
                                />
                            </div>
                            <div>
                                <label className="block text-xs font-semibold text-heading mb-1">Description *</label>
                                <textarea
                                    required
                                    rows={2}
                                    value={chDesc}
                                    onChange={(e) => setChDesc(e.target.value)}
                                    placeholder="Detailed guidelines and goals for the student..."
                                    className="w-full p-3 rounded-xl border border-edge/10 bg-surface-950 text-xs text-heading placeholder:text-text-muted focus:outline-none focus:border-brand-primary"
                                />
                            </div>
                            <div className="grid grid-cols-2 gap-3">
                                <div>
                                    <label className="block text-xs font-semibold text-heading mb-1">Category</label>
                                    <select
                                        value={chCategory}
                                        onChange={(e) => setChCategory(e.target.value)}
                                        className="w-full h-9 px-2 rounded-xl border border-edge/10 bg-surface-950 text-xs text-heading focus:outline-none"
                                    >
                                        <option value="Trading & Risk">Trading & Risk</option>
                                        <option value="Options & Hedging">Options & Hedging</option>
                                        <option value="LLM Strategy">LLM Strategy</option>
                                        <option value="Algo Prompting">Algo Prompting</option>
                                    </select>
                                </div>
                                <div>
                                    <label className="block text-xs font-semibold text-heading mb-1">Target Metric</label>
                                    <select
                                        value={chMetric}
                                        onChange={(e) => setChMetric(e.target.value)}
                                        className="w-full h-9 px-2 rounded-xl border border-edge/10 bg-surface-950 text-xs text-heading focus:outline-none"
                                    >
                                        <option value="pnl">Cumulative PnL ($)</option>
                                        <option value="win_rate">Win Rate (%)</option>
                                        <option value="max_drawdown">Max Drawdown (%)</option>
                                        <option value="sharpe">Sharpe Ratio</option>
                                    </select>
                                </div>
                            </div>
                            <div>
                                <label className="block text-xs font-semibold text-heading mb-1">Target Value</label>
                                <input
                                    type="number"
                                    required
                                    value={chTarget}
                                    onChange={(e) => setChTarget(e.target.value)}
                                    className="w-full h-9 px-3 rounded-xl border border-edge/10 bg-surface-950 text-xs text-heading focus:outline-none"
                                />
                            </div>
                            <div className="flex justify-end gap-2 pt-2">
                                <button
                                    type="button"
                                    onClick={() => setShowCreateChallenge(false)}
                                    className="px-4 py-2 rounded-xl bg-surface-800 text-xs text-heading"
                                >
                                    Cancel
                                </button>
                                <button
                                    type="submit"
                                    disabled={creatingCh}
                                    className="px-4 py-2 rounded-xl bg-violet-600 text-white text-xs font-bold hover:bg-violet-500 disabled:opacity-50"
                                >
                                    {creatingCh ? 'Creating...' : 'Publish Challenge'}
                                </button>
                            </div>
                        </form>
                    </div>
                </div>
            )}

            {/* DRAWER: Student Logs Inspector */}
            {selectedStudent && (
                <div className="fixed inset-0 z-50 bg-black/75 backdrop-blur-sm flex justify-end">
                    <div className="bg-surface-900 border-l border-edge/10 w-full max-w-2xl h-full p-6 space-y-6 overflow-y-auto shadow-2xl">
                        <div className="flex items-center justify-between border-b border-edge/10 pb-4">
                            <div>
                                <div className="flex items-center gap-2">
                                    <Activity className="h-5 w-5 text-brand-primary" />
                                    <h3 className="text-lg font-bold text-heading">{selectedStudent.full_name}</h3>
                                </div>
                                <p className="text-xs text-text-secondary">{selectedStudent.email} • Inspection Logs</p>
                            </div>
                            <button onClick={() => { setSelectedStudent(null); setStudentLogs(null); }} className="text-text-muted hover:text-heading">
                                <X className="h-6 w-6" />
                            </button>
                        </div>

                        {loadingLogs ? (
                            <div className="py-20 text-center space-y-3">
                                <Skeleton variant="rect" height="120px" />
                                <Skeleton variant="rect" height="200px" />
                            </div>
                        ) : studentLogs ? (
                            <div className="space-y-6">
                                {/* Order Execution History Logs */}
                                <div className="space-y-3">
                                    <h4 className="text-xs uppercase font-bold text-brand-primary tracking-wider flex items-center gap-2">
                                        <FileText className="h-4 w-4" />
                                        <span>Trade Execution Order History ({studentLogs.orders?.length || 0})</span>
                                    </h4>
                                    {studentLogs.orders?.length === 0 ? (
                                        <p className="text-xs text-text-muted p-4 rounded-xl border border-edge/10 bg-surface-950">No trade orders recorded yet for this student.</p>
                                    ) : (
                                        <div className="space-y-2 max-h-80 overflow-y-auto pr-1">
                                            {studentLogs.orders.map((o) => (
                                                <div key={o.id} className="p-3 rounded-xl border border-edge/10 bg-surface-950/80 flex items-center justify-between text-xs">
                                                    <div>
                                                        <div className="font-semibold text-heading flex items-center gap-2">
                                                            <span className={o.side === 'BUY' ? 'text-profit font-bold' : 'text-loss font-bold'}>{o.side}</span>
                                                            <span>{o.symbol}</span>
                                                            <span className="text-text-muted">({o.quantity} qty)</span>
                                                        </div>
                                                        <div className="text-[11px] text-text-secondary">
                                                            Type: {o.order_type} • Price: ${o.filled_price || o.price}
                                                        </div>
                                                    </div>
                                                    <div className="text-right">
                                                        <span className="px-2 py-0.5 rounded text-[10px] font-bold bg-surface-800 text-text-secondary border border-edge/10">
                                                            {o.status}
                                                        </span>
                                                        <div className="text-[10px] text-text-muted mt-1">
                                                            {o.created_at ? new Date(o.created_at).toLocaleTimeString() : ''}
                                                        </div>
                                                    </div>
                                                </div>
                                            ))}
                                        </div>
                                    )}
                                </div>

                                {/* Study Activity & Quiz Logs */}
                                <div className="space-y-3">
                                    <h4 className="text-xs uppercase font-bold text-accent-purple tracking-wider flex items-center gap-2">
                                        <BookOpen className="h-4 w-4" />
                                        <span>Study & Quiz Activity Timeline</span>
                                    </h4>
                                    {studentLogs.activities?.length === 0 ? (
                                        <p className="text-xs text-text-muted p-4 rounded-xl border border-edge/10 bg-surface-950">No activity logs found.</p>
                                    ) : (
                                        <div className="space-y-2 max-h-60 overflow-y-auto pr-1">
                                            {studentLogs.activities.map((a) => (
                                                <div key={a.id} className="p-3 rounded-xl border border-edge/10 bg-surface-950/60 flex items-center justify-between text-xs">
                                                    <div className="flex items-center gap-2">
                                                        <span className="capitalize font-medium text-heading">{a.activity_type}</span>
                                                        <span className="text-text-muted">• {a.minutes_spent} minutes</span>
                                                    </div>
                                                    <span className="text-text-secondary text-[11px]">{a.activity_date}</span>
                                                </div>
                                            ))}
                                        </div>
                                    )}
                                </div>
                            </div>
                        ) : (
                            <p className="text-xs text-text-muted">No log data found.</p>
                        )}
                    </div>
                </div>
            )}
        </div>
    );
}
