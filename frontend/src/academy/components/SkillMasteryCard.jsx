// SkillMasteryCard.jsx - single skill progress bar with Beginner/Intermediate/Advanced badge
const LEVEL_STYLES = {
    Advanced: 'bg-profit/15 text-profit',
    Intermediate: 'bg-accent-amber/15 text-accent-amber',
    Beginner: 'bg-accent-blue/15 text-accent-blue',
};

export default function SkillMasteryCard({ skill, mastery_percent, level }) {
    return (
        <div className="rounded-xl border border-edge/5 bg-surface-900/60 p-4">
            <div className="flex items-center justify-between mb-2">
                <span className="text-sm font-medium text-heading">{skill}</span>
                <span className={`rounded-full px-2 py-0.5 text-[10px] font-medium ${LEVEL_STYLES[level] || LEVEL_STYLES.Beginner}`}>
                    {level}
                </span>
            </div>
            <div className="h-1.5 w-full rounded-full bg-edge/10 overflow-hidden">
                <div
                    className="h-full rounded-full bg-brand-primary"
                    style={{ width: `${mastery_percent}%` }}
                />
            </div>
            <span className="mt-1 block text-xs text-text-secondary">{mastery_percent}% mastery</span>
        </div>
    );
}
