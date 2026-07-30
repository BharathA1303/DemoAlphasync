import { forwardRef } from 'react';
import { cn } from '../../utils/cn';

/**
 * Reusable Input component.
 * @param {{ label?: string, error?: string, hint?: string, leftAddon?: ReactNode, rightAddon?: ReactNode }} props
 */
const Input = forwardRef(function Input(
    { label, error, hint, leftAddon, rightAddon, className, id, ...props },
    ref
) {
    const inputId = id || label?.toLowerCase().replace(/\s+/g, '-');

    return (
        <div className="flex flex-col gap-1">
            {label && (
                <label htmlFor={inputId} className="text-sm font-medium text-gray-400">
                    {label}
                </label>
            )}
            <div className="relative flex items-center">
                {leftAddon && (
                    <div className="absolute left-3 text-gray-500 pointer-events-none">
                        {leftAddon}
                    </div>
                )}
                <input
                    ref={ref}
                    id={inputId}
                    className={cn(
                        'w-full bg-surface-900/80 border rounded-lg px-4 py-2.5 text-sm text-heading',
                        'placeholder-gray-500 transition-all duration-200',
                        'focus:outline-none focus:ring-1',
                        error
                            ? 'border-red-500/50 focus:ring-red-500/20 focus:border-red-500/70'
                            : 'border-edge/10 focus:border-primary-500/50 focus:ring-primary-500/20',
                        leftAddon && 'pl-9',
                        rightAddon && 'pr-9',
                        className
                    )}
                    {...props}
                />
                {rightAddon && (
                    <div className="absolute right-3 text-gray-500">
                        {rightAddon}
                    </div>
                )}
            </div>
            {error && <p className="text-xs text-red-500">{error}</p>}
            {!error && hint && <p className="text-xs text-gray-500">{hint}</p>}
        </div>
    );
});

export default Input;
