// WorkspaceSwitcher.jsx — Multi-Tenant Workspace & Identity Switcher
import { useState, useRef, useEffect } from 'react';
import { useAuthStore } from '../../stores/useAuthStore';
import { Building2, UserCheck, ChevronDown, Check, Sparkles } from 'lucide-react';
import toast from 'react-hot-toast';
import { cn } from '../../utils/cn';

export default function WorkspaceSwitcher() {
    const user = useAuthStore((s) => s.user);
    const switchTenant = useAuthStore((s) => s.switchTenant);
    const [open, setOpen] = useState(false);
    const [loading, setLoading] = useState(false);
    const dropdownRef = useRef(null);

    const tenantRoles = user?.tenant_roles || [];
    const activeTenantId = user?.tenant_id;
    
    const activeWorkspace = tenantRoles.find((t) => t.tenant_id === activeTenantId) || {
        tenant_name: user?.tenant_name || 'Individual Workspace',
        tenant_type: user?.tenant_type || 'individual',
        role: user?.academy_role || 'trader',
    };

    useEffect(() => {
        function handleClickOutside(e) {
            if (dropdownRef.current && !dropdownRef.current.contains(e.target)) {
                setOpen(false);
            }
        }
        document.addEventListener('mousedown', handleClickOutside);
        return () => document.removeEventListener('mousedown', handleClickOutside);
    }, []);

    const handleSwitch = async (tId, name, role) => {
        if (tId === activeTenantId || loading) return;
        setLoading(true);
        try {
            await switchTenant(tId);
            toast.success(`Switched workspace to ${name} (${role.toUpperCase()})`);
            setOpen(false);
        } catch (err) {
            toast.error(err?.response?.data?.detail || 'Failed to switch workspace');
        } finally {
            setLoading(false);
        }
    };

    if (tenantRoles.length <= 1) {
        return (
            <div className="hidden sm:inline-flex items-center gap-1.5 px-2.5 py-1 rounded-lg text-xs font-semibold bg-surface-800/40 border border-edge/10 text-slate-300">
                {activeWorkspace.tenant_type === 'individual' ? (
                    <UserCheck className="w-3.5 h-3.5 text-indigo-400" />
                ) : (
                    <Building2 className="w-3.5 h-3.5 text-amber-400" />
                )}
                <span className="truncate max-w-[120px]">{activeWorkspace.tenant_name}</span>
            </div>
        );
    }

    return (
        <div className="relative hidden sm:block" ref={dropdownRef}>
            <button
                type="button"
                onClick={() => setOpen((p) => !p)}
                className="flex items-center gap-2 px-3 py-1.5 rounded-lg text-xs font-semibold bg-indigo-500/15 border border-indigo-500/30 text-indigo-200 hover:bg-indigo-500/25 transition-all shadow-sm cursor-pointer"
            >
                {activeWorkspace.tenant_type === 'individual' ? (
                    <UserCheck className="w-3.5 h-3.5 text-indigo-300" />
                ) : (
                    <Building2 className="w-3.5 h-3.5 text-amber-300" />
                )}
                <span className="truncate max-w-[130px] font-bold">{activeWorkspace.tenant_name}</span>
                <ChevronDown className={cn("w-3.5 h-3.5 transition-transform duration-200", open && "rotate-180")} />
            </button>

            {open && (
                <div className="absolute top-full right-0 mt-2 w-64 rounded-xl border border-white/10 bg-slate-900/95 backdrop-blur-md p-2 shadow-2xl z-50 animate-in fade-in duration-150">
                    <div className="px-2 py-1.5 border-b border-white/10 mb-1">
                        <div className="flex items-center gap-1.5 text-[10px] font-bold uppercase tracking-wider text-slate-400">
                            <Sparkles className="w-3 h-3 text-indigo-400" /> Switch Workspace Context
                        </div>
                    </div>
                    <div className="space-y-1 max-h-60 overflow-y-auto">
                        {tenantRoles.map((t) => {
                            const isSelected = t.tenant_id === activeTenantId;
                            return (
                                <button
                                    key={t.tenant_id}
                                    onClick={() => handleSwitch(t.tenant_id, t.tenant_name, t.role)}
                                    disabled={loading}
                                    className={cn(
                                        "w-full flex items-center justify-between p-2 rounded-lg text-left transition-all text-xs cursor-pointer",
                                        isSelected
                                            ? "bg-indigo-500/20 text-white border border-indigo-500/30 font-bold"
                                            : "hover:bg-white/5 text-slate-300"
                                    )}
                                >
                                    <div className="flex items-center gap-2 min-w-0">
                                        {t.tenant_type === 'individual' ? (
                                            <UserCheck className="w-4 h-4 text-indigo-400 flex-shrink-0" />
                                        ) : (
                                            <Building2 className="w-4 h-4 text-amber-400 flex-shrink-0" />
                                        )}
                                        <div className="min-w-0">
                                            <div className="truncate font-semibold text-white">{t.tenant_name}</div>
                                            <div className="text-[10px] text-slate-400 uppercase tracking-wide font-mono">
                                                {t.role} • {t.tenant_type}
                                            </div>
                                        </div>
                                    </div>
                                    {isSelected && <Check className="w-4 h-4 text-indigo-400 flex-shrink-0 ml-2" />}
                                </button>
                            );
                        })}
                    </div>
                </div>
            )}
        </div>
    );
}
