import { cn } from '../../utils/cn';

/**
 * Skeleton shimmer loader.
 *
 * Variants map to shapes matching specific components:
 *   text, circle, chart, watchlist-row, stat-card, table-row
 *
 * @param {{
 *   variant?: 'text'|'circle'|'chart'|'watchlist-row'|'stat-card'|'table-row',
 *   width?: string,
 *   height?: string,
 *   className?: string,
 * }} props
 */
export default function Skeleton({ variant = 'text', width, height, className, count = 1 }) {
    const base = 'bg-surface-700 rounded animate-skeleton bg-gradient-to-r from-surface-700 via-surface-800 to-surface-700 bg-[length:200%_100%]';

    const renderSingle = (key) => {
        if (variant === 'chart') {
            return (
                <div key={key} className={cn('w-full rounded-xl', base, className)} style={{ height: height || '300px' }} />
            );
        }
        if (variant === 'watchlist-row') {
            return (
                <div key={key} className="flex items-center justify-between px-3 py-2.5 gap-3">
                    <div className="flex flex-col gap-1.5 flex-1">
                        <div className={cn('h-3.5 w-20 rounded', base)} />
                        <div className={cn('h-2.5 w-28 rounded', base)} />
                    </div>
                    <div className="flex flex-col items-end gap-1.5">
                        <div className={cn('h-3.5 w-16 rounded', base)} />
                        <div className={cn('h-2.5 w-12 rounded', base)} />
                    </div>
                </div>
            );
        }
        if (variant === 'stat-card') {
            return (
                <div key={key} className="glass-card p-5 flex flex-col gap-2">
                    <div className={cn('h-2.5 w-20 rounded', base)} />
                    <div className={cn('h-6 w-28 rounded', base)} />
                    <div className={cn('h-2 w-16 rounded', base)} />
                </div>
            );
        }
        if (variant === 'table-row') {
            return (
                <div key={key} className="flex items-center gap-4 py-3 px-2">
                    <div className={cn('h-3.5 w-20 rounded', base)} />
                    <div className={cn('h-3.5 w-12 rounded ml-auto', base)} />
                    <div className={cn('h-3.5 w-16 rounded', base)} />
                    <div className={cn('h-3.5 w-16 rounded', base)} />
                    <div className={cn('h-3.5 w-20 rounded', base)} />
                </div>
            );
        }
        if (variant === 'circle') {
            const s = width || height || '40px';
            return <div key={key} className={cn('rounded-full', base, className)} style={{ width: s, height: s }} />;
        }
        // default: text line
        return (
            <div
                key={key}
                className={cn('h-4 rounded', base, className)}
                style={{ width: width || '100%', height: height }}
            />
        );
    };

    if (count === 1) return renderSingle(0);
    return (
        <div className="flex flex-col gap-2">
            {Array.from({ length: count }, (_, i) => renderSingle(i))}
        </div>
    );
}
