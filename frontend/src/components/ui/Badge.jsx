import { cn } from '../../utils/cn';

const variants = {
    default: 'bg-surface-800/60 text-gray-500 border border-edge/10',
    primary: 'bg-primary-500/10 text-primary-600 border border-primary-500/20',
    success: 'bg-bull/10 text-bull border border-bull/20',
    danger:  'bg-bear/10 text-bear border border-bear/20',
    warning: 'bg-primary-500/10 text-primary-600 border border-primary-500/20',
    bull:    'bg-bull/10 text-bull border border-bull/20',
    bear:    'bg-bear/10 text-bear border border-bear/20',
};

/**
 * Status/label badge.
 * @param {{ variant?: keyof variants, dot?: boolean }} props
 */
export default function Badge({ variant = 'default', dot = false, className, children }) {
    return (
        <span
            className={cn(
                'inline-flex items-center gap-1.5 text-xs font-medium px-2 py-0.5 rounded-full',
                variants[variant],
                className
            )}
        >
            {dot && (
                <span className={cn('w-1.5 h-1.5 rounded-full', {
                    'bg-primary-500': variant === 'primary' || variant === 'warning',
                    'bg-bull':        variant === 'success' || variant === 'bull',
                    'bg-bear':        variant === 'danger'  || variant === 'bear',
                    'bg-gray-500':    variant === 'default',
                })} />
            )}
            {children}
        </span>
    );
}
