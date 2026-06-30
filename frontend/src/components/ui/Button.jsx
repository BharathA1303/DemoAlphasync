import { forwardRef } from 'react';
import { cn } from '../../utils/cn';

const variants = {
    primary: 'bg-primary-600 hover:bg-primary-500 text-white shadow-lg shadow-primary-600/20 hover:shadow-primary-500/30',
    secondary: 'bg-surface-700 hover:bg-surface-700/80 text-heading border border-edge/10 hover:border-edge/20',
    buy: 'bg-buy hover:bg-green-400 text-white shadow-lg shadow-green-500/20',
    sell: 'bg-sell hover:bg-red-400 text-white shadow-lg shadow-red-500/20',
    ghost: 'text-gray-400 hover:text-heading hover:bg-overlay/5',
    danger: 'bg-red-600 hover:bg-red-500 text-white',
    outline: 'border border-edge/20 text-heading hover:bg-overlay/5',
};

const sizes = {
    xs: 'text-xs px-2.5 py-1 rounded-md',
    sm: 'text-sm px-3.5 py-1.5 rounded-lg',
    md: 'text-sm px-5 py-2.5 rounded-lg font-semibold',
    lg: 'text-base px-6 py-3 rounded-lg font-bold',
};

/**
 * Reusable Button component.
 * @param {{ variant?: keyof variants, size?: keyof sizes, isLoading?: boolean }} props
 */
const Button = forwardRef(function Button(
    {
        variant = 'primary',
        size = 'md',
        isLoading = false,
        disabled = false,
        className,
        children,
        ...props
    },
    ref
) {
    return (
        <button
            ref={ref}
            disabled={disabled || isLoading}
            className={cn(
                'inline-flex items-center justify-center gap-2 font-medium transition-all duration-200',
                'active:scale-[0.98] disabled:opacity-50 disabled:cursor-not-allowed',
                variants[variant],
                sizes[size],
                className
            )}
            {...props}
        >
            {isLoading && (
                <span className="w-3.5 h-3.5 border-2 border-current border-t-transparent rounded-full animate-spin" />
            )}
            {children}
        </button>
    );
});

export default Button;
