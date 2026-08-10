import React, { useState, useEffect, useMemo } from 'react';
import { useNavigate } from 'react-router-dom';
import {
    Building2,
    Users,
    Plus,
    Copy,
    Check,
    Search,
    Shield,
    Trash2,
    Loader2,
    RefreshCw,
    ArrowLeft,
    Clock,
    UserCheck,
    ChevronRight,
    ExternalLink,
    BadgeCheck,
} from 'lucide-react';
import { adminApi, parseApiError } from '../services/adminApi';
import { toast } from 'react-hot-toast';

export default function InstitutionsManagementPage() {
    const navigate = useNavigate();

    // Institution List State
    const [institutions, setInstitutions] = useState([]);
    const [loading, setLoading] = useState(true);
    const [copiedId, setCopiedId] = useState(null);

    // Selected Institution Roster View
    const [selectedTenant, setSelectedTenant] = useState(null);
    const [members, setMembers] = useState([]);
    const [membersLoading, setMembersLoading] = useState(false);
    const [memberSearch, setMemberSearch] = useState('');
    const [memberRoleFilter, setMemberRoleFilter] = useState('all');
    const [updatingUserId, setUpdatingUserId] = useState(null);

    // Create Modal State
    const [showCreateModal, setShowCreateModal] = useState(false);
    const [createName, setCreateName] = useState('');
    const [createDomain, setCreateDomain] = useState('');
    const [createMaxUsers, setCreateMaxUsers] = useState('1000');
    const [creating, setCreating] = useState(false);

    // Fetch Institutions List
    const fetchInstitutions = async () => {
        setLoading(true);
        try {
            const { data } = await adminApi.listInstitutions();
            if (data?.success) {
                setInstitutions(data.institutions || []);
            }
        } catch (err) {
            toast.error(parseApiError(err, 'Failed to fetch institutions'));
        } finally {
            setLoading(false);
        }
    };

    useEffect(() => {
        fetchInstitutions();
    }, []);

    // Fetch Members when selectedTenant changes or search/filter updates
    const fetchMembers = async () => {
        if (!selectedTenant) return;
        setMembersLoading(true);
        try {
            const { data } = await adminApi.getInstitutionMembers(
                selectedTenant.id,
                memberSearch,
                memberRoleFilter
            );
            if (data?.success) {
                setMembers(data.members || []);
            }
        } catch (err) {
            toast.error(parseApiError(err, 'Failed to fetch members'));
        } finally {
            setMembersLoading(false);
        }
    };

    useEffect(() => {
        if (selectedTenant) {
            fetchMembers();
        }
    }, [selectedTenant, memberSearch, memberRoleFilter]);

    // Handle Create Institution
    const handleCreateInstitution = async (e) => {
        e.preventDefault();
        if (!createName.trim()) {
            toast.error('Please enter institution name');
            return;
        }

        setCreating(true);
        try {
            const { data } = await adminApi.createInstitution({
                name: createName.trim(),
                domain: createDomain.trim() || undefined,
                max_users: parseInt(createMaxUsers) || 1000,
            });

            if (data?.success) {
                toast.success(`Institution "${data.institution.name}" created successfully!`);
                setShowCreateModal(false);
                setCreateName('');
                setCreateDomain('');
                setCreateMaxUsers('1000');
                fetchInstitutions();
            }
        } catch (err) {
            toast.error(parseApiError(err, 'Failed to create institution'));
        } finally {
            setCreating(false);
        }
    };

    // Handle Copy Invite Link
    const handleCopyLink = async (inst) => {
        const link = inst.invite_url || `${window.location.origin}/login?inst=${inst.slug}`;
        try {
            await navigator.clipboard.writeText(link);
            setCopiedId(inst.id);
            toast.success(`Onboarding link for ${inst.name} copied to clipboard!`);
            setTimeout(() => setCopiedId(null), 2500);
        } catch {
            toast.error('Failed to copy link');
        }
    };

    // Handle Update Role
    const handleRoleChange = async (userId, newRole) => {
        if (!selectedTenant) return;
        setUpdatingUserId(userId);
        try {
            const { data } = await adminApi.updateInstitutionMemberRole(selectedTenant.id, userId, newRole);
            if (data?.success) {
                toast.success(`Role updated to ${newRole}`);
                setMembers((prev) =>
                    prev.map((m) => (m.id === userId ? { ...m, role: newRole } : m))
                );
                fetchInstitutions();
            }
        } catch (err) {
            toast.error(parseApiError(err, 'Failed to update member role'));
        } finally {
            setUpdatingUserId(null);
        }
    };

    // Handle Toggle Active Status
    const handleToggleActive = async (inst) => {
        try {
            const { data } = await adminApi.updateInstitution(inst.id, {
                is_active: !inst.is_active,
            });
            if (data?.success) {
                toast.success(`Institution set to ${!inst.is_active ? 'Active' : 'Inactive'}`);
                fetchInstitutions();
                if (selectedTenant?.id === inst.id) {
                    setSelectedTenant((prev) => (prev ? { ...prev, is_active: !inst.is_active } : null));
                }
            }
        } catch (err) {
            toast.error(parseApiError(err, 'Failed to update institution status'));
        }
    };

    // Handle Delete Institution
    const handleDeleteInstitution = async (inst) => {
        if (
            !window.confirm(
                `Are you sure you want to delete "${inst.name}"? This action cannot be undone.`
            )
        ) {
            return;
        }

        try {
            const { data } = await adminApi.deleteInstitution(inst.id);
            if (data?.success) {
                toast.success(`Institution "${inst.name}" deleted.`);
                if (selectedTenant?.id === inst.id) {
                    setSelectedTenant(null);
                }
                fetchInstitutions();
            }
        } catch (err) {
            toast.error(parseApiError(err, 'Failed to delete institution'));
        }
    };

    // Derived Statistics
    const totalInstitutions = institutions.length;
    const totalMembers = useMemo(
        () => institutions.reduce((acc, inst) => acc + (inst.member_count || 0), 0),
        [institutions]
    );

    return (
        <div className="min-h-screen p-3 sm:p-4 md:p-5 lg:p-6" style={{ background: 'var(--bg-base)', color: 'var(--text-primary)' }}>
            {/* Header */}
            <header className="flex flex-wrap items-start sm:items-center justify-between gap-3 mb-6">
                <div>
                    <div className="flex items-center gap-2 mb-1">
                        <Building2 size={16} style={{ color: 'var(--brand, #059669)' }} />
                        <span className="text-xs font-bold uppercase tracking-widest" style={{ color: 'var(--text-muted)' }}>
                            Platform Control
                        </span>
                    </div>
                    <h1 className="text-xl sm:text-2xl font-bold flex items-center gap-2" style={{ color: 'var(--text-primary)' }}>
                        Institutions Management
                    </h1>
                    <p className="text-xs sm:text-sm mt-0.5" style={{ color: 'var(--text-muted)' }}>
                        Manage academic tenants, generate single-link onboarding URLs, and oversee institution roles.
                    </p>
                </div>

                <div className="flex items-center gap-2">
                    <button
                        className="btn-secondary flex items-center gap-2 text-xs sm:text-sm"
                        onClick={() => fetchInstitutions()}
                        disabled={loading}
                    >
                        <RefreshCw size={14} className={loading ? 'animate-spin' : ''} />
                        Refresh
                    </button>
                    <button
                        className="btn-secondary flex items-center gap-2 text-xs sm:text-sm"
                        onClick={() => navigate('/admin/panel')}
                    >
                        <ArrowLeft size={14} /> Back to Admin Panel
                    </button>
                    <button
                        className="btn-primary flex items-center gap-2 text-xs sm:text-sm px-4 py-2"
                        onClick={() => setShowCreateModal(true)}
                    >
                        <Plus size={16} /> Add Institution
                    </button>
                </div>
            </header>

            {/* Metric Summary Grid */}
            <section className="grid grid-cols-1 sm:grid-cols-3 gap-4 mb-6">
                <div
                    className="rounded-xl p-4 flex items-center justify-between shadow-sm"
                    style={{ background: 'var(--bg-surface)', border: '1px solid var(--border)' }}
                >
                    <div>
                        <span className="text-xs font-semibold uppercase tracking-wider block mb-1" style={{ color: 'var(--text-muted)' }}>
                            Total Institutions
                        </span>
                        <span className="text-2xl font-bold font-mono" style={{ color: 'var(--text-primary)' }}>{totalInstitutions}</span>
                    </div>
                    <div className="p-3 rounded-lg" style={{ background: 'rgba(59, 130, 246, 0.1)', color: '#3b82f6' }}>
                        <Building2 size={24} />
                    </div>
                </div>

                <div
                    className="rounded-xl p-4 flex items-center justify-between shadow-sm"
                    style={{ background: 'var(--bg-surface)', border: '1px solid var(--border)' }}
                >
                    <div>
                        <span className="text-xs font-semibold uppercase tracking-wider block mb-1" style={{ color: 'var(--text-muted)' }}>
                            Active Institution Members
                        </span>
                        <span className="text-2xl font-bold font-mono" style={{ color: 'var(--text-primary)' }}>{totalMembers}</span>
                    </div>
                    <div className="p-3 rounded-lg" style={{ background: 'rgba(16, 185, 129, 0.1)', color: '#10b981' }}>
                        <Users size={24} />
                    </div>
                </div>

                <div
                    className="rounded-xl p-4 flex items-center justify-between shadow-sm"
                    style={{ background: 'var(--bg-surface)', border: '1px solid var(--border)' }}
                >
                    <div>
                        <span className="text-xs font-semibold uppercase tracking-wider block mb-1" style={{ color: 'var(--text-muted)' }}>
                            Single-Link Onboarding
                        </span>
                        <span className="text-sm font-bold text-emerald-600 dark:text-emerald-400 flex items-center gap-1.5 mt-1">
                            <Clock size={14} /> Permanent / Lifetime Valid
                        </span>
                    </div>
                    <div className="p-3 rounded-lg" style={{ background: 'rgba(139, 92, 246, 0.1)', color: '#8b5cf6' }}>
                        <Shield size={24} />
                    </div>
                </div>
            </section>

            {/* Main Content Area — Switch between Institutions List and Full Roster View */}
            {!selectedTenant ? (
                /* ── View 1: Partner Institutions Cards Grid ── */
                <div className="rounded-xl p-4 sm:p-5 shadow-sm" style={{ background: 'var(--bg-surface)', border: '1px solid var(--border)' }}>
                    <div className="flex items-center justify-between mb-4">
                        <h2 className="text-lg font-bold flex items-center gap-2" style={{ color: 'var(--text-primary)' }}>
                            <Building2 size={18} className="text-emerald-500" /> Partner Institutions
                        </h2>
                        <span className="text-xs font-mono font-semibold" style={{ color: 'var(--text-muted)' }}>
                            {institutions.length} Registered
                        </span>
                    </div>

                    {loading ? (
                        <div className="py-16 flex justify-center">
                            <Loader2 className="animate-spin" style={{ color: 'var(--brand)' }} />
                        </div>
                    ) : institutions.length === 0 ? (
                        <div className="text-center py-16" style={{ color: 'var(--text-muted)' }}>
                            <Building2 size={42} className="mx-auto mb-3 opacity-40" />
                            <p className="text-sm font-semibold">No institutions created yet.</p>
                            <p className="text-xs mt-1" style={{ color: 'var(--text-muted)' }}>Create your first institution to generate permanent onboarding invite URLs.</p>
                            <button
                                className="btn-primary text-xs mt-4 px-4 py-2"
                                onClick={() => setShowCreateModal(true)}
                            >
                                Create First Institution
                            </button>
                        </div>
                    ) : (
                        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
                            {institutions.map((inst) => (
                                <div
                                    key={inst.id}
                                    className="rounded-xl p-5 transition-all border flex flex-col justify-between hover:shadow-md cursor-pointer group"
                                    style={{
                                        background: 'var(--bg-muted)',
                                        borderColor: 'var(--border)',
                                    }}
                                    onClick={() => setSelectedTenant(inst)}
                                >
                                    <div>
                                        <div className="flex items-start justify-between gap-3 mb-2">
                                            <div>
                                                <h3 className="font-bold text-base group-hover:text-blue-500 transition-colors" style={{ color: 'var(--text-primary)' }}>
                                                    {inst.name}
                                                </h3>
                                                <span className="text-xs font-mono" style={{ color: 'var(--text-muted)' }}>
                                                    Code: <strong className="text-blue-500 font-bold">{inst.slug}</strong>
                                                </span>
                                            </div>
                                            <span
                                                className={`text-[10px] uppercase font-bold px-2.5 py-0.5 rounded-full border ${
                                                    inst.is_active
                                                        ? 'bg-emerald-500/10 text-emerald-600 dark:text-emerald-400 border-emerald-500/20'
                                                        : 'bg-rose-500/10 text-rose-600 dark:text-rose-400 border-rose-500/20'
                                                }`}
                                            >
                                                {inst.is_active ? 'Active' : 'Inactive'}
                                            </span>
                                        </div>

                                        {/* Info Pills */}
                                        <div className="flex flex-wrap items-center gap-2 mt-3 text-xs">
                                            <span className="px-2.5 py-1 rounded-md font-medium flex items-center gap-1.5" style={{ background: 'var(--bg-surface)', border: '1px solid var(--border)', color: 'var(--text-secondary)' }}>
                                                <Users size={12} className="text-blue-500" /> Members: <strong style={{ color: 'var(--text-primary)' }}>{inst.member_count || 0}</strong>
                                            </span>
                                            {inst.domain && (
                                                <span className="px-2 py-1 rounded-md font-medium" style={{ background: 'var(--bg-surface)', border: '1px solid var(--border)', color: 'var(--text-secondary)' }}>
                                                    Domain: {inst.domain}
                                                </span>
                                            )}
                                        </div>

                                        {/* Link Expiry Notice */}
                                        <div className="mt-3 p-2.5 rounded-lg flex items-center gap-2 text-[11px]" style={{ background: 'rgba(59, 130, 246, 0.08)', border: '1px solid rgba(59, 130, 246, 0.2)', color: 'var(--text-secondary)' }}>
                                            <Clock size={13} className="text-blue-500 flex-shrink-0" />
                                            <span>Invite Link: <strong className="text-blue-500">Permanent / Lifetime Access</strong> (Auto-verified)</span>
                                        </div>
                                    </div>

                                    {/* Action Footer */}
                                    <div className="mt-4 pt-3 flex items-center justify-between gap-2 border-t" style={{ borderColor: 'var(--border)' }}>
                                        <button
                                            className="flex items-center gap-1.5 text-xs font-semibold px-3 py-1.5 rounded-lg text-blue-600 dark:text-blue-400 hover:bg-blue-500/10 transition-colors"
                                            onClick={(e) => {
                                                e.stopPropagation();
                                                handleCopyLink(inst);
                                            }}
                                        >
                                            {copiedId === inst.id ? <Check size={14} className="text-emerald-500" /> : <Copy size={14} />}
                                            {copiedId === inst.id ? 'Copied Link!' : 'Copy Signup Link'}
                                        </button>

                                        <div className="flex items-center gap-2">
                                            <button
                                                className="btn-primary text-xs px-3 py-1.5 flex items-center gap-1"
                                                onClick={(e) => {
                                                    e.stopPropagation();
                                                    setSelectedTenant(inst);
                                                }}
                                            >
                                                Manage Roster <ChevronRight size={14} />
                                            </button>

                                            <button
                                                className="p-1.5 rounded-lg text-rose-500 hover:bg-rose-500/10 transition-colors"
                                                onClick={(e) => {
                                                    e.stopPropagation();
                                                    handleDeleteInstitution(inst);
                                                }}
                                                title="Delete Institution"
                                            >
                                                <Trash2 size={15} />
                                            </button>
                                        </div>
                                    </div>
                                </div>
                            ))}
                        </div>
                    )}
                </div>
            ) : (
                /* ── View 2: Full-Width Member Management & Roster View ── */
                <div className="rounded-xl p-4 sm:p-6 shadow-sm animate-fade-in" style={{ background: 'var(--bg-surface)', border: '1px solid var(--border)' }}>
                    {/* Top Navigation & Back Button */}
                    <div className="flex flex-wrap items-center justify-between gap-4 mb-6 pb-4 border-b" style={{ borderColor: 'var(--border)' }}>
                        <div className="flex items-center gap-3">
                            <button
                                className="btn-secondary flex items-center gap-2 text-xs sm:text-sm font-semibold px-3.5 py-2"
                                onClick={() => setSelectedTenant(null)}
                            >
                                <ArrowLeft size={16} /> Back to All Institutions
                            </button>
                            <span className="text-xs font-mono px-2.5 py-1 rounded-md" style={{ background: 'var(--bg-muted)', color: 'var(--text-muted)' }}>
                                Code: <strong className="text-blue-500">{selectedTenant.slug}</strong>
                            </span>
                        </div>

                        <div className="flex items-center gap-2">
                            <button
                                className="flex items-center gap-1.5 text-xs font-semibold px-3 py-2 rounded-lg text-blue-600 dark:text-blue-400 bg-blue-500/10 hover:bg-blue-500/20 transition-colors"
                                onClick={() => handleCopyLink(selectedTenant)}
                            >
                                {copiedId === selectedTenant.id ? <Check size={14} className="text-emerald-500" /> : <Copy size={14} />}
                                {copiedId === selectedTenant.id ? 'Copied Onboarding Link!' : 'Copy Onboarding Link'}
                            </button>

                            <button
                                className={`text-xs font-semibold px-3 py-2 rounded-lg transition-colors ${
                                    selectedTenant.is_active
                                        ? 'bg-amber-500/10 text-amber-600 dark:text-amber-400 hover:bg-amber-500/20'
                                        : 'bg-emerald-500/10 text-emerald-600 dark:text-emerald-400 hover:bg-emerald-500/20'
                                }`}
                                onClick={() => handleToggleActive(selectedTenant)}
                            >
                                {selectedTenant.is_active ? 'Deactivate Institution' : 'Activate Institution'}
                            </button>
                        </div>
                    </div>

                    {/* Section Header */}
                    <div className="flex flex-wrap items-start justify-between gap-4 mb-6">
                        <div>
                            <div className="flex items-center gap-2">
                                <Building2 size={22} className="text-blue-500" />
                                <h2 className="text-xl sm:text-2xl font-bold" style={{ color: 'var(--text-primary)' }}>
                                    {selectedTenant.name} Roster
                                </h2>
                                <span className="px-2.5 py-0.5 text-xs font-bold uppercase rounded-full bg-emerald-500/10 text-emerald-600 dark:text-emerald-400 border border-emerald-500/20">
                                    {selectedTenant.is_active ? 'Active Tenant' : 'Inactive Tenant'}
                                </span>
                            </div>
                            <p className="text-xs sm:text-sm mt-1" style={{ color: 'var(--text-muted)' }}>
                                Overview and role assignments for members enrolled in this institution. Users coming via signup link are automatically verified.
                            </p>
                        </div>

                        {/* Link Time Limit Notice Badge */}
                        <div className="px-3 py-2 rounded-xl flex items-center gap-2 text-xs" style={{ background: 'var(--bg-muted)', border: '1px solid var(--border)', color: 'var(--text-secondary)' }}>
                            <BadgeCheck size={16} className="text-emerald-500 flex-shrink-0" />
                            <div>
                                <span className="font-semibold block" style={{ color: 'var(--text-primary)' }}>Invite Link Time Limit:</span>
                                <span className="text-[11px] text-emerald-600 dark:text-emerald-400 font-mono font-bold">Permanent / Lifetime Valid</span>
                            </div>
                        </div>
                    </div>

                    {/* Search & Filter Bar */}
                    <div className="flex flex-col sm:flex-row gap-3 mb-5">
                        <div className="relative flex-1">
                            <Search size={15} className="absolute left-3.5 top-3" style={{ color: 'var(--text-muted)' }} />
                            <input
                                className="input-field pl-10 text-xs sm:text-sm w-full"
                                placeholder="Search member by full name, username, or email address..."
                                value={memberSearch}
                                onChange={(e) => setMemberSearch(e.target.value)}
                            />
                        </div>
                        <select
                            className="input-field text-xs sm:text-sm sm:w-48"
                            value={memberRoleFilter}
                            onChange={(e) => setMemberRoleFilter(e.target.value)}
                        >
                            <option value="all">All Roles</option>
                            <option value="student">Student</option>
                            <option value="faculty">Faculty</option>
                            <option value="institution_admin">Institution Admin</option>
                            <option value="trader">Trader</option>
                        </select>
                    </div>

                    {/* Members Table */}
                    {membersLoading ? (
                        <div className="py-20 flex justify-center">
                            <Loader2 className="animate-spin" size={28} style={{ color: 'var(--brand)' }} />
                        </div>
                    ) : members.length === 0 ? (
                        <div className="text-center py-16 rounded-xl" style={{ background: 'var(--bg-muted)', border: '1px dashed var(--border)' }}>
                            <Users size={38} className="mx-auto mb-2 opacity-40" />
                            <p className="text-sm font-semibold" style={{ color: 'var(--text-primary)' }}>No members found for this institution.</p>
                            <p className="text-xs mt-1" style={{ color: 'var(--text-muted)' }}>Share the onboarding link to enroll students and faculty automatically.</p>
                        </div>
                    ) : (
                        <div className="overflow-x-auto rounded-xl shadow-sm" style={{ border: '1px solid var(--border)' }}>
                            <table className="w-full text-left text-xs sm:text-sm" style={{ borderCollapse: 'collapse' }}>
                                <thead style={{ background: 'var(--bg-muted)', color: 'var(--text-secondary)' }}>
                                    <tr className="border-b" style={{ borderColor: 'var(--border)' }}>
                                        <th className="p-3.5 font-bold">User / Member</th>
                                        <th className="p-3.5 font-bold">Email Address</th>
                                        <th className="p-3.5 font-bold">Current Role</th>
                                        <th className="p-3.5 font-bold">Account Status</th>
                                        <th className="p-3.5 font-bold">Enrolled On</th>
                                        <th className="p-3.5 font-bold text-right">Change Role</th>
                                    </tr>
                                </thead>
                                <tbody className="divide-y" style={{ borderColor: 'var(--border)' }}>
                                    {members.map((m) => (
                                        <tr key={m.id} className="hover:bg-blue-500/5 transition-colors">
                                            {/* User Name */}
                                            <td className="p-3.5 font-bold" style={{ color: 'var(--text-primary)' }}>
                                                {m.full_name || m.username}
                                                {m.username && <span className="block text-xs font-normal font-mono" style={{ color: 'var(--text-muted)' }}>@{m.username}</span>}
                                            </td>

                                            {/* Email Address — 100% visible in Light & Dark Mode */}
                                            <td className="p-3.5 font-semibold font-mono" style={{ color: 'var(--text-primary)' }}>
                                                <span className="px-2 py-0.5 rounded" style={{ background: 'var(--bg-muted)', color: 'var(--text-primary)' }}>
                                                    {m.email}
                                                </span>
                                            </td>

                                            {/* Role Badge */}
                                            <td className="p-3.5">
                                                <span
                                                    className={`inline-block px-2.5 py-1 rounded-md text-xs font-bold uppercase ${
                                                        m.role === 'institution_admin'
                                                            ? 'bg-purple-500/15 text-purple-600 dark:text-purple-300 border border-purple-500/30'
                                                            : m.role === 'faculty'
                                                            ? 'bg-blue-500/15 text-blue-600 dark:text-blue-300 border border-blue-500/30'
                                                            : 'bg-emerald-500/15 text-emerald-600 dark:text-emerald-300 border border-emerald-500/30'
                                                    }`}
                                                >
                                                    {m.role.replace('_', ' ')}
                                                </span>
                                            </td>

                                            {/* Status */}
                                            <td className="p-3.5">
                                                <span className="inline-flex items-center gap-1 text-xs font-semibold text-emerald-600 dark:text-emerald-400">
                                                    <BadgeCheck size={14} /> Auto-Verified & Active
                                                </span>
                                            </td>

                                            {/* Date */}
                                            <td className="p-3.5 text-xs font-mono" style={{ color: 'var(--text-secondary)' }}>
                                                {m.created_at ? new Date(m.created_at).toLocaleDateString() : '—'}
                                            </td>

                                            {/* Change Role Selector */}
                                            <td className="p-3.5 text-right">
                                                {updatingUserId === m.id ? (
                                                    <Loader2 size={16} className="animate-spin inline text-blue-500" />
                                                ) : (
                                                    <select
                                                        className="input-field text-xs py-1.5 px-2.5 rounded-lg font-medium"
                                                        value={m.role}
                                                        onChange={(e) => handleRoleChange(m.id, e.target.value)}
                                                    >
                                                        <option value="student">Student</option>
                                                        <option value="faculty">Faculty</option>
                                                        <option value="institution_admin">Institution Admin</option>
                                                        <option value="trader">Trader</option>
                                                    </select>
                                                )}
                                            </td>
                                        </tr>
                                    ))}
                                </tbody>
                            </table>
                        </div>
                    )}
                </div>
            )}

            {/* Create Institution Modal */}
            {showCreateModal && (
                <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60 backdrop-blur-sm">
                    <div
                        className="rounded-2xl p-6 max-w-md w-full shadow-2xl animate-scale-in"
                        style={{ background: 'var(--bg-surface)', border: '1px solid var(--border)' }}
                    >
                        <div className="flex items-center justify-between mb-4">
                            <h3 className="text-lg font-bold flex items-center gap-2" style={{ color: 'var(--text-primary)' }}>
                                <Building2 size={20} className="text-blue-500" /> Create Institution
                            </h3>
                            <button
                                className="text-slate-400 hover:text-white text-lg font-bold"
                                onClick={() => setShowCreateModal(false)}
                            >
                                ×
                            </button>
                        </div>

                        <form onSubmit={handleCreateInstitution} className="space-y-4">
                            <div>
                                <label className="label-text block mb-1" style={{ color: 'var(--text-secondary)' }}>Institution Name *</label>
                                <input
                                    className="input-field w-full text-sm"
                                    placeholder="e.g. Oxford Financial Academy"
                                    value={createName}
                                    onChange={(e) => setCreateName(e.target.value)}
                                    required
                                />
                            </div>

                            <div>
                                <label className="label-text block mb-1" style={{ color: 'var(--text-secondary)' }}>Domain (Optional)</label>
                                <input
                                    className="input-field w-full text-sm"
                                    placeholder="e.g. oxford.edu"
                                    value={createDomain}
                                    onChange={(e) => setCreateDomain(e.target.value)}
                                />
                            </div>

                            <div>
                                <label className="label-text block mb-1" style={{ color: 'var(--text-secondary)' }}>User Limit (Max Members)</label>
                                <input
                                    type="number"
                                    className="input-field w-full text-sm"
                                    value={createMaxUsers}
                                    onChange={(e) => setCreateMaxUsers(e.target.value)}
                                    min={1}
                                    max={100000}
                                />
                            </div>

                            {/* Link Time Limit Notice */}
                            <div className="p-3 rounded-lg text-xs" style={{ background: 'rgba(59, 130, 246, 0.08)', border: '1px solid rgba(59, 130, 246, 0.2)', color: 'var(--text-secondary)' }}>
                                <span className="font-semibold text-blue-500 block mb-0.5">🔗 Single-Link Onboarding Information</span>
                                Links generated have <strong>Permanent / Lifetime Validity</strong>. Users registering through the link bypass manual admin approval queues and log in automatically.
                            </div>

                            <div className="flex justify-end gap-2 pt-2">
                                <button
                                    type="button"
                                    className="btn-secondary text-xs px-4 py-2"
                                    onClick={() => setShowCreateModal(false)}
                                >
                                    Cancel
                                </button>
                                <button
                                    type="submit"
                                    className="btn-primary text-xs px-4 py-2 flex items-center gap-1.5"
                                    disabled={creating}
                                >
                                    {creating ? <Loader2 size={14} className="animate-spin" /> : <Plus size={14} />}
                                    Create & Generate Link
                                </button>
                            </div>
                        </form>
                    </div>
                </div>
            )}
        </div>
    );
}
