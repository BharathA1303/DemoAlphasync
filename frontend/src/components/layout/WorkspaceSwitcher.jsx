// WorkspaceSwitcher.jsx — Multi-Tenant Workspace & Identity Switcher
import { useState, useRef, useEffect } from 'react';
import { useAuthStore } from '../../stores/useAuthStore';
import { Building2, UserCheck, ChevronDown, Check, Layers } from 'lucide-react';
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
            toast.success(`Switched to ${name} (${role.toUpperCase()})`);
            setOpen(false);
        } catch (err) {
            toast.error(err?.response?.data?.detail || 'Failed to switch workspace');
        } finally {
            setLoading(false);
        }
    };

    // Single workspace — show a static label pill
    if (tenantRoles.length <= 1) {
        return (
            <div className="hidden sm:inline-flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg text-xs font-semibold bg-surface-800/50 border border-edge/10 text-text-secondary">
                {activeWorkspace.tenant_type === 'individual' ? (
                    <UserCheck className="w-3.5 h-3.5 text-brand-primary" />
                ) : (
                    <Building2 className="w-3.5 h-3.5 text-brand-primary" />
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
                className="flex items-center gap-2 px-3 py-1.5 rounded-xl text-xs font-semibold btn-action cursor-pointer"
            >
                {activeWorkspace.tenant_type === 'individual' ? (
                    <UserCheck className="w-3.5 h-3.5 text-brand-primary" />
                ) : (
                    <Building2 className="w-3.5 h-3.5 text-brand-primary" />
                )}
                <span className="truncate max-w-[130px] font-bold text-heading">{activeWorkspace.tenant_name}</span>
                <ChevronDown className={cn("w-3.5 h-3.5 text-text-muted transition-transform duration-200", open && "rotate-180")} />
            </button>

            {open && (
                <div className="absolute top-full right-0 mt-2 w-64 card-panel-elevated p-2 shadow-2xl z-50">
                    <div className="px-2 py-1.5 border-b border-edge/8 mb-1">
                        <div className="flex items-center gap-1.5 text-[10px] font-bold uppercase tracking-wider text-text-muted">
                            <Layers className="w-3 h-3 text-brand-primary" /> Switch Workspace Context
                        </div>
                    </div>
                    <div className="space-y-0.5 max-h-60 overflow-y-auto">
                        {tenantRoles.map((t) => {
                            const isSelected = t.tenant_id === activeTenantId;
                            return (
                                <button
                                    key={t.tenant_id}
                                    onClick={() => handleSwitch(t.tenant_id, t.tenant_name, t.role)}
                                    disabled={loading}
                                    className={cn(
                                        "w-full flex items-center justify-between p-2.5 rounded-lg text-left transition-all text-xs cursor-pointer",
                                        isSelected
                                            ? "bg-brand-primary/15 text-heading border border-brand-primary/25 font-bold"
                                            : "hover:bg-surface-800/50 text-text-secondary hover:text-heading"
                                    )}
                                >
                                    <div className="flex items-center gap-2 min-w-0">
                                        {t.tenant_type === 'individual' ? (
                                            <UserCheck className="w-4 h-4 text-brand-primary flex-shrink-0" />
                                        ) : (
                                            <Building2 className="w-4 h-4 text-brand-primary flex-shrink-0" />
                                        )}
                                        <div className="min-w-0">
                                            <div className="truncate font-semibold text-heading">{t.tenant_name}</div>
                                            <div className="text-[10px] text-text-muted uppercase tracking-wide font-mono">
                                                {t.role} • {t.tenant_type}
                                            </div>
                                        </div>
                                    </div>
                                    {isSelected && <Check className="w-4 h-4 text-brand-primary flex-shrink-0 ml-2" />}
                                </button>
                            );
                        })}
                    </div>
                </div>
            )}
        </div>
    );
}
