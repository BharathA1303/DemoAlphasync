// AcademyDonutChart.jsx - Recharts donut wrapper used for progress/breakdown visuals
import { PieChart, Pie, Cell, Tooltip, ResponsiveContainer, Legend } from 'recharts';

const DEFAULT_COLORS = ['#00bcd4', '#10b981', '#f59e0b', '#8b5cf6', '#ef4444', '#3b82f6'];

export default function AcademyDonutChart({ data, dataKey = 'value', nameKey = 'name', colors = DEFAULT_COLORS, height = 220, centerLabel }) {
    return (
        <div className="relative" style={{ height }}>
            <ResponsiveContainer width="100%" height="100%">
                <PieChart>
                    <Pie
                        data={data}
                        dataKey={dataKey}
                        nameKey={nameKey}
                        innerRadius="62%"
                        outerRadius="90%"
                        paddingAngle={2}
                        stroke="none"
                    >
                        {data.map((_, index) => (
                            <Cell key={index} fill={colors[index % colors.length]} />
                        ))}
                    </Pie>
                    <Tooltip
                        contentStyle={{ background: 'var(--bg-surface)', border: '1px solid var(--border)', borderRadius: 8, fontSize: 12 }}
                    />
                    <Legend
                        verticalAlign="bottom"
                        height={36}
                        formatter={(value) => <span className="text-xs text-text-secondary">{value}</span>}
                    />
                </PieChart>
            </ResponsiveContainer>
            {centerLabel && (
                <div className="pointer-events-none absolute inset-0 flex flex-col items-center justify-center" style={{ marginBottom: 18 }}>
                    <span className="text-xl font-semibold text-heading font-display">{centerLabel}</span>
                </div>
            )}
        </div>
    );
}
