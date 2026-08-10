import React, { useState, useEffect, useCallback, useMemo } from 'react';
import { useNavigate } from 'react-router-dom';
import toast from 'react-hot-toast';
import {
    Building2,
    Users,
    GraduationCap,
    UserCheck,
    Plus,
    Search,
    Copy,
    Check,
    Loader2,
    ArrowLeft,
    Shield,
    Globe,
    Trash2,
    Edit3,
    ExternalLink,
    RefreshCw,
    Filter,
    ChevronRight,
} from 'lucide-react';
import adminApi from '../services/adminApi';

function parseApiError(error, fallback = 'Request failed') {
    return error?.response?.data?.detail || error?.message || fallback;
}

export default function InstitutionsManagementPage() {
    const navigate = useNavigate();

    // Stats and List state
    const [institutions, setInstitutions] = useState([]);
    const [loading, setLoading] = useState(true);

    // Modal state for Create Institution
    const [showCreateModal, setShowCreateModal] = useState(false);
    const [createName, setCreateName] = useState('');
    const [createDomain, setCreateDomain] = useState('');
    const [createMaxUsers, setCreateMaxUsers] = useState(1000);
    const [creating, setCreating] = useState(false);

    // Active/Selected Institution for Member Management
    const [selectedTenant, setSelectedTenant] = useState(null);
    const [members, setMembers] = useState([]);
    const [membersLoading, setMembersLoading] = useState(false);
    const [memberSearch, setMemberSearch] = useState('');
    const [memberRoleFilter, setMemberRoleFilter] = useState('all');
    const [updatingUserId, setUpdatingUserId] = useState(null);

    // Edit modal state
    const [editingTenant, setEditingTenant] = useState(null);
    const [editName, setEditName] = useState('');
    const [editDomain, setEditDomain] = useState('');
    const [editMaxUsers, setEditMaxUsers] = useState(1000);
    const [updatingTenant, setUpdatingTenant] = useState(false);

    // Copy Feedback State
    const [copiedId, setCopiedId] = useState(null);

    // Fetch Institutions List
    const fetchInstitutions = useCallback(async () => {
        setLoading(true);
        try {
            const { data } = await adminApi.listInstitutions();
            if (data?.success) {
                setInstitutions(data.institutions || []);
            } else {
                toast.error('Failed to load institutions');
            }
        } catch (err) {
            toast.error(parseApiError(err, 'Failed to load institutions'));
        } finally {
            setLoading(false);
        }
    }, []);

    useEffect(() => {
        fetchInstitutions();
    }, [fetchInstitutions]);

    // Fetch Members for Selected Tenant
    const fetchMembers = useCallback(async (tenantId) => {
        if (!tenantId) return;
        setMembersLoading(true);
        try {
            const { data } = await adminApi.getInstitutionMembers(tenantId, {
                query: memberSearch,
                role: memberRoleFilter,
            });
            if (data?.success) {
                setMembers(data.members || []);
            }
        } catch (err) {
            toast.error(parseApiError(err, 'Failed to fetch members'));
        } finally {
            setMembersLoading(false);
        }
    }, [memberSearch, memberRoleFilter]);

    useEffect(() => {
        if (selectedTenant) {
            fetchMembers(selectedTenant.id);
        }
    }, [selectedTenant, fetchMembers]);

    // Handle Create Institution
    const handleCreateInstitution = async (e) => {
        e.preventDefault();
        if (!createName.trim()) {
            toast.error('Please enter an institution name');
            return;
        }

        setCreating(true);
        try {
            const { data } = await adminApi.createInstitution({
                name: createName.trim(),
                domain: createDomain.trim() || undefined,
                max_users: Number(createMaxUsers) || 1000,
            });

            if (data?.success) {
                toast.success(`Institution "${createName}" created successfully!`);
                setCreateName('');
                setCreateDomain('');
                setCreateMaxUsers(1000);
                setShowCreateModal(false);
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
            toast.success(`Invite link for ${inst.name} copied to clipboard!`);
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
                // Also update role_counts locally
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
            }
        } catch (err) {
            toast.error(parseApiError(err, 'Failed to update status'));
        }
    };

    // Handle Delete Institution
    const handleDeleteInstitution = async (inst) => {
        if (!window.confirm(`Are you sure you want to delete "${inst.name}"? This action cannot be undone.`)) {
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
                        <Building2 size={16} style={{ color: 'var(--brand, #3b82f6)' }} />
                        <span className="text-xs font-bold uppercase tracking-widest" style={{ color: 'var(--text-muted)' }}>
                            Platform Control
                        </span>
                    </div>
                    <h1 className="text-xl sm:text-2xl font-bold flex items-center gap-2">
                        Institutions Management
                    </h1>
                    <p className="text-xs sm:text-sm" style={{ color: 'var(--text-muted)' }}>
                        Manage academic tenants, generate single-link onboarding URLs, and oversee institution roles.
                    </p>
                </div>

                <div className="flex items-center gap-2">
                    <button
                        className="btn-secondary flex items-center gap-2 text-sm"
                        onClick={() => fetchInstitutions()}
                        disabled={loading}
                    >
                        <RefreshCw size={14} className={loading ? 'animate-spin' : ''} />
                        Refresh
                    </button>
                    <button
                        className="btn-secondary flex items-center gap-2 text-sm"
                        onClick={() => navigate('/admin/panel')}
                    >
                        <ArrowLeft size={14} /> Back to Admin Panel
                    </button>
                    <button
                        className="btn-primary flex items-center gap-2 text-sm px-4 py-2"
                        onClick={() => setShowCreateModal(true)}
                    >
                        <Plus size={16} /> Add Institution
                    </button>
                </div>
            </header>

            {/* Metric Summary Grid */}
            <section className="grid grid-cols-1 sm:grid-cols-3 gap-4 mb-6">
                <div
                    className="rounded-xl p-4 flex items-center justify-between"
                    style={{ background: 'var(--bg-muted)', border: '1px solid var(--border)' }}
                >
                    <div>
                        <span className="text-xs font-semibold uppercase tracking-wider block mb-1" style={{ color: 'var(--text-muted)' }}>
                            Total Institutions
                        </span>
                        <span className="text-2xl font-bold font-mono">{totalInstitutions}</span>
                    </div>
                    <div className="p-3 rounded-lg" style={{ background: 'rgba(59, 130, 246, 0.1)', color: '#3b82f6' }}>
                        <Building2 size={24} />
                    </div>
                </div>

                <div
                    className="rounded-xl p-4 flex items-center justify-between"
                    style={{ background: 'var(--bg-muted)', border: '1px solid var(--border)' }}
                >
                    <div>
                        <span className="text-xs font-semibold uppercase tracking-wider block mb-1" style={{ color: 'var(--text-muted)' }}>
                            Active Institution Members
                        </span>
                        <span className="text-2xl font-bold font-mono">{totalMembers}</span>
                    </div>
                    <div className="p-3 rounded-lg" style={{ background: 'rgba(16, 185, 129, 0.1)', color: '#10b981' }}>
                        <Users size={24} />
                    </div>
                </div>

                <div
                    className="rounded-xl p-4 flex items-center justify-between"
                    style={{ background: 'var(--bg-muted)', border: '1px solid var(--border)' }}
                >
                    <div>
                        <span className="text-xs font-semibold uppercase tracking-wider block mb-1" style={{ color: 'var(--text-muted)' }}>
                            Multi-Tenant Mode
                        </span>
                        <span className="text-sm font-semibold text-emerald-400 flex items-center gap-1.5 mt-1">
                            <Shield size={14} /> Enabled & Isolated
                        </span>
                    </div>
                    <div className="p-3 rounded-lg" style={{ background: 'rgba(139, 92, 246, 0.1)', color: '#8b5cf6' }}>
                        <Globe size={24} />
                    </div>
                </div>
            </section>

            {/* Main Content Grid */}
            <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
                {/* Institutions List Panel */}
                <div className={`${selectedTenant ? 'lg:col-span-6' : 'lg:col-span-12'} transition-all duration-300`}>
                    <div className="rounded-xl p-4" style={{ background: 'var(--bg-muted)', border: '1px solid var(--border)' }}>
                        <div className="flex items-center justify-between mb-4">
                            <h2 className="text-lg font-bold flex items-center gap-2">
                                <Building2 size={18} /> Partner Institutions
                            </h2>
                            <span className="text-xs font-mono" style={{ color: 'var(--text-muted)' }}>
                                {institutions.length} Registered
                            </span>
                        </div>

                        {loading ? (
                            <div className="py-12 flex justify-center">
                                <Loader2 className="animate-spin" style={{ color: 'var(--brand)' }} />
                            </div>
                        ) : institutions.length === 0 ? (
                            <div className="text-center py-12" style={{ color: 'var(--text-muted)' }}>
                                <Building2 size={36} className="mx-auto mb-2 opacity-50" />
                                <p className="text-sm">No institutions created yet.</p>
                                <button
                                    className="btn-primary text-xs mt-3 px-3 py-1.5"
                                    onClick={() => setShowCreateModal(true)}
                                >
                                    Create First Institution
                                </button>
                            </div>
                        ) : (
                            <div className="space-y-3">
                                {institutions.map((inst) => {
                                    const isSelected = selectedTenant?.id === inst.id;
                                    return (
                                        <div
                                            key={inst.id}
                                            className={`rounded-lg p-4 transition-all border cursor-pointer ${
                                                isSelected
                                                    ? 'border-blue-500 bg-blue-500/10'
                                                    : 'hover:border-slate-600'
                                            }`}
                                            style={{
                                                background: isSelected ? 'rgba(59, 130, 246, 0.08)' : 'var(--bg-surface)',
                                                borderColor: isSelected ? '#3b82f6' : 'var(--border)',
                                            }}
                                            onClick={() => setSelectedTenant(inst)}
                                        >
                                            <div className="flex items-start justify-between gap-3">
                                                <div>
                                                    <div className="flex items-center gap-2">
                                                        <h3 className="font-bold text-base">{inst.name}</h3>
                                                        <span
                                                            className={`text-[10px] uppercase font-bold px-2 py-0.5 rounded-full ${
                                                                inst.is_active
                                                                    ? 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/20'
                                                                    : 'bg-rose-500/10 text-rose-400 border border-rose-500/20'
                                                            }`}
                                                        >
                                                            {inst.is_active ? 'Active' : 'Inactive'}
                                                        </span>
                                                    </div>
                                                    <div className="flex flex-wrap items-center gap-x-4 gap-y-1 mt-1 text-xs" style={{ color: 'var(--text-muted)' }}>
                                                        <span>Code/Slug: <code className="font-mono text-blue-400">{inst.slug}</code></span>
                                                        {inst.domain && <span>Domain: {inst.domain}</span>}
                                                        <span>Members: <strong className="text-slate-200">{inst.member_count || 0}</strong></span>
                                                    </div>
                                                </div>

                                                <button
                                                    className="p-1.5 rounded-lg hover:bg-white/5 text-slate-400 hover:text-white"
                                                    onClick={(e) => {
                                                        e.stopPropagation();
                                                        setSelectedTenant(inst);
                                                    }}
                                                    title="View Roster"
                                                >
                                                    <ChevronRight size={18} />
                                                </button>
                                            </div>

                                            {/* Invite link & quick actions bar */}
                                            <div className="mt-3 pt-3 flex flex-wrap items-center justify-between gap-2 border-t" style={{ borderColor: 'var(--border)' }}>
                                                <button
                                                    className="flex items-center gap-1.5 text-xs font-semibold px-2.5 py-1.5 rounded-md text-blue-400 hover:bg-blue-500/10"
                                                    onClick={(e) => {
                                                        e.stopPropagation();
                                                        handleCopyLink(inst);
                                                    }}
                                                >
                                                    {copiedId === inst.id ? <Check size={14} className="text-emerald-400" /> : <Copy size={14} />}
                                                    {copiedId === inst.id ? 'Copied Link!' : 'Copy Signup Link'}
                                                </button>

                                                <div className="flex items-center gap-1">
                                                    <button
                                                        className="text-xs px-2.5 py-1 rounded hover:bg-white/5 text-slate-300"
                                                        onClick={(e) => {
                                                            e.stopPropagation();
                                                            handleToggleActive(inst);
                                                        }}
                                                    >
                                                        {inst.is_active ? 'Deactivate' : 'Activate'}
                                                    </button>

                                                    <button
                                                        className="text-xs px-2.5 py-1 rounded hover:bg-rose-500/10 text-rose-400"
                                                        onClick={(e) => {
                                                            e.stopPropagation();
                                                            handleDeleteInstitution(inst);
                                                        }}
                                                    >
                                                        <Trash2 size={14} />
                                                    </button>
                                                </div>
                                            </div>
                                        </div>
                                    );
                                })}
                            </div>
                        )}
                    </div>
                </div>

                {/* Institution Members Management Panel */}
                {selectedTenant && (
                    <div className="lg:col-span-6">
                        <div className="rounded-xl p-4" style={{ background: 'var(--bg-muted)', border: '1px solid var(--border)' }}>
                            <div className="flex items-center justify-between mb-3">
                                <div>
                                    <h2 className="text-lg font-bold flex items-center gap-2">
                                        <Users size={18} /> {selectedTenant.name} Roster
                                    </h2>
                                    <p className="text-xs" style={{ color: 'var(--text-muted)' }}>
                                        Manage student, faculty, and administrator roles for this institution.
                                    </p>
                                </div>
                                <button
                                    className="text-xs text-slate-400 hover:text-white px-2 py-1 rounded bg-white/5"
                                    onClick={() => setSelectedTenant(null)}
                                >
                                    Close Panel
                                </button>
                            </div>

                            {/* Search & Filter bar */}
                            <div className="flex flex-col sm:flex-row gap-2 mb-4">
                                <div className="relative flex-1">
                                    <Search size={14} className="absolute left-3 top-3" style={{ color: 'var(--text-muted)' }} />
                                    <input
                                        className="input-field pl-9 text-xs"
                                        placeholder="Search by name or email..."
                                        value={memberSearch}
                                        onChange={(e) => setMemberSearch(e.target.value)}
                                    />
                                </div>
                                <select
                                    className="input-field text-xs sm:w-40"
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
                                <div className="py-12 flex justify-center">
                                    <Loader2 className="animate-spin" style={{ color: 'var(--brand)' }} />
                                </div>
                            ) : members.length === 0 ? (
                                <div className="text-center py-8 text-xs" style={{ color: 'var(--text-muted)' }}>
                                    No members found for this institution.
                                </div>
                            ) : (
                                <div className="overflow-x-auto rounded-lg" style={{ border: '1px solid var(--border)' }}>
                                    <table className="w-full text-left text-xs" style={{ borderCollapse: 'collapse' }}>
                                        <thead style={{ background: 'var(--bg-surface)' }}>
                                            <tr className="border-b" style={{ borderColor: 'var(--border)' }}>
                                                <th className="p-2.5 font-semibold">User</th>
                                                <th className="p-2.5 font-semibold">Role</th>
                                                <th className="p-2.5 font-semibold text-right">Change Role</th>
                                            </tr>
                                        </thead>
                                        <tbody className="divide-y" style={{ borderColor: 'var(--border)' }}>
                                            {members.map((m) => (
                                                <tr key={m.id} className="hover:bg-white/5 transition-colors">
                                                    <td className="p-2.5">
                                                        <div className="font-semibold text-slate-100">{m.full_name || m.username}</div>
                                                        <div className="text-[11px]" style={{ color: 'var(--text-muted)' }}>{m.email}</div>
                                                    </td>
                                                    <td className="p-2.5">
                                                        <span
                                                            className={`inline-block px-2 py-0.5 rounded text-[10px] font-bold uppercase ${
                                                                m.role === 'institution_admin'
                                                                    ? 'bg-purple-500/20 text-purple-300'
                                                                    : m.role === 'faculty'
                                                                    ? 'bg-blue-500/20 text-blue-300'
                                                                    : 'bg-emerald-500/20 text-emerald-300'
                                                            }`}
                                                        >
                                                            {m.role.replace('_', ' ')}
                                                        </span>
                                                    </td>
                                                    <td className="p-2.5 text-right">
                                                        {updatingUserId === m.id ? (
                                                            <Loader2 size={14} className="animate-spin inline text-blue-400" />
                                                        ) : (
                                                            <select
                                                                className="input-field text-[11px] py-1 px-2 rounded"
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
                    </div>
                )}
            </div>

            {/* Create Institution Modal */}
            {showCreateModal && (
                <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60 backdrop-blur-sm">
                    <div
                        className="rounded-2xl p-6 max-w-md w-full shadow-2xl"
                        style={{ background: 'var(--bg-muted)', border: '1px solid var(--border)' }}
                    >
                        <div className="flex items-center justify-between mb-4">
                            <h3 className="text-lg font-bold flex items-center gap-2">
                                <Building2 size={20} className="text-blue-400" /> Create Institution
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
                                <label className="label-text block mb-1">Institution Name *</label>
                                <input
                                    className="input-field w-full"
                                    placeholder="e.g. Oxford Financial Academy"
                                    value={createName}
                                    onChange={(e) => setCreateName(e.target.value)}
                                    required
                                />
                            </div>

                            <div>
                                <label className="label-text block mb-1">Domain (Optional)</label>
                                <input
                                    className="input-field w-full"
                                    placeholder="e.g. oxford.edu"
                                    value={createDomain}
                                    onChange={(e) => setCreateDomain(e.target.value)}
                                />
                            </div>

                            <div>
                                <label className="label-text block mb-1">User Limit (Max Members)</label>
                                <input
                                    type="number"
                                    className="input-field w-full"
                                    value={createMaxUsers}
                                    onChange={(e) => setCreateMaxUsers(e.target.value)}
                                    min={1}
                                    max={100000}
                                />
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
