// ActivityHeatmap.jsx - hand-rolled CSS grid heatmap (Recharts has no heatmap primitive)
const DAY_LABELS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];

function intensityClass(minutes) {
    if (minutes <= 0) return 'bg-edge/10';
    if (minutes < 20) return 'bg-brand-primary/25';
    if (minutes < 45) return 'bg-brand-primary/50';
    if (minutes < 75) return 'bg-brand-primary/75';
    return 'bg-brand-primary';
}

export default function ActivityHeatmap({ weeks }) {
    return (
        <div className="flex gap-3">
            <div className="flex flex-col justify-between py-1 text-[10px] text-text-muted">
                {DAY_LABELS.map((d) => (
                    <span key={d} className="h-4 leading-4">{d}</span>
                ))}
            </div>
            <div className="flex flex-1 gap-1.5 overflow-x-auto">
                {weeks.map((week) => (
                    <div key={week.week} className="flex flex-col gap-1.5">
                        {week.days.map((day) => (
                            <div
                                key={day.date}
                                title={`${day.date}: ${day.minutes} min`}
                                className={`h-4 w-4 rounded-sm ${intensityClass(day.minutes)}`}
                            />
                        ))}
                    </div>
                ))}
            </div>
        </div>
    );
}
