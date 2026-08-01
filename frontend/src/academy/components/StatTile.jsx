// StatTile.jsx - small KPI tile used across the Academy dashboard/analytics pages
export default function StatTile({ icon: Icon, label, value, sublabel, accentClass = 'text-brand-primary' }) {
    return (
        <div className="kpi-card">
            <div className="flex items-center justify-between">
                <span className="metric-label">{label}</span>
                {Icon && <Icon className={`h-4 w-4 ${accentClass}`} />}
            </div>
            <span className="text-2xl font-semibold text-heading font-display">{value}</span>
            {sublabel && <span className="text-xs text-text-secondary">{sublabel}</span>}
        </div>
    );
}
