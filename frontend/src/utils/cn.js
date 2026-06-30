import { clsx } from 'clsx';
import { twMerge } from 'tailwind-merge';

/**
 * Merges Tailwind CSS class names, resolving conflicts correctly.
 * @param {...import('clsx').ClassValue} inputs
 * @returns {string}
 */
export const cn = (...inputs) => twMerge(clsx(inputs));
