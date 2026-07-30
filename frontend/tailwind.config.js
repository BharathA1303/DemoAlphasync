/** @type {import('tailwindcss').Config} */
export default {
    content: [
        "./index.html",
        "./src/**/*.{js,ts,jsx,tsx}",
    ],
    darkMode: 'class',
    theme: {
        screens: {
            'xs': '480px',
            'sm': '640px',
            'md': '768px',
            'lg': '1024px',
            'xl': '1400px',
            '2xl': '1920px',
        },
        extend: {
            colors: {
                // ── Dark theme primary palette ─────────────────────────────
                navy: {
                    DEFAULT: '#0f0f1e',
                    50: '#1a1f3a',
                    100: '#242f4a',
                    200: '#2d3a55',
                    300: '#364560',
                    400: '#3d516b',
                    500: '#475c77',
                    600: '#556d88',
                    700: '#687e99',
                    800: '#7a8faa',
                    900: '#8da0bb',
                },
                gold: {
                    DEFAULT: '#00bcd4',
                    50: '#b2ebf2',
                    100: '#80deea',
                    200: '#4dd0e1',
                    300: '#26c6da',
                    400: '#00bcd4',
                    500: '#00acc1',
                    600: '#0097a7',
                    700: '#00838f',
                    800: '#006c7a',
                    900: '#004d5c',
                },
                teal: {
                    DEFAULT: '#0097a7',
                    50: '#b2ebf2',
                    100: '#80deea',
                    200: '#4dd0e1',
                    300: '#26c6da',
                    400: '#00bcd4',
                    500: '#00acc1',
                    600: '#0097a7',
                    700: '#00838f',
                    800: '#006c7a',
                    900: '#004d5c',
                },
                // ── Brand primary — CSS-variable-backed for accent color switching ─
                primary: {
                    50: 'rgb(var(--primary-50) / <alpha-value>)',
                    100: 'rgb(var(--primary-100) / <alpha-value>)',
                    200: 'rgb(var(--primary-200) / <alpha-value>)',
                    300: 'rgb(var(--primary-300) / <alpha-value>)',
                    400: 'rgb(var(--primary-400) / <alpha-value>)',
                    500: 'rgb(var(--primary-500) / <alpha-value>)',
                    600: 'rgb(var(--primary-600) / <alpha-value>)',
                    700: 'rgb(var(--primary-700) / <alpha-value>)',
                    800: 'rgb(var(--primary-800) / <alpha-value>)',
                    900: 'rgb(var(--primary-900) / <alpha-value>)',
                },
                // ── CSS-var-backed surface / text tokens ──────────────────────
                surface: {
                    50: 'rgb(var(--surface-50) / <alpha-value>)',
                    100: 'rgb(var(--surface-100) / <alpha-value>)',
                    200: 'rgb(var(--surface-200) / <alpha-value>)',
                    700: 'rgb(var(--surface-700) / <alpha-value>)',
                    800: 'rgb(var(--surface-800) / <alpha-value>)',
                    850: 'rgb(var(--surface-850) / <alpha-value>)',
                    900: 'rgb(var(--surface-900) / <alpha-value>)',
                    950: 'rgb(var(--surface-950) / <alpha-value>)',
                },
                gray: {
                    300: 'rgb(var(--gray-300) / <alpha-value>)',
                    400: 'rgb(var(--gray-400) / <alpha-value>)',
                    500: 'rgb(var(--gray-500) / <alpha-value>)',
                    600: 'rgb(var(--gray-600) / <alpha-value>)',
                    700: 'rgb(var(--gray-700) / <alpha-value>)',
                },
                heading: 'rgb(var(--c-heading) / <alpha-value>)',
                edge: 'rgb(var(--c-edge) / <alpha-value>)',
                overlay: 'rgb(var(--c-overlay) / <alpha-value>)',
                accent: {
                    warm: '#00bcd4',
                    copper: '#0097a7',
                    sand: '#b2ebf2',
                    // Semantic accent aliases used across Dashboard/components
                    cyan: '#00bcd4',
                    emerald: '#10b981',
                    blue: '#3b82f6',
                    amber: '#f59e0b',
                    rose: '#f43f5e',
                    purple: '#8b5cf6',
                    violet: '#7c3aed',
                },
                // ── Semantic trading colors ───────────────────────────────────
                profit: '#10b981',
                loss: '#ef4444',
                buy: '#10b981',
                sell: '#ef4444',
                // ── Trading design system tokens ─────────────────────────────
                brand: {
                    primary: '#00bcd4',
                    dim: '#0097a7',
                    glow: 'rgba(0,188,212,0.15)',
                },
                bull: {
                    DEFAULT: '#10b981',
                    dim: '#059669',
                    glow: 'rgba(16,185,129,0.15)',
                },
                bear: {
                    DEFAULT: '#ef4444',
                    dim: '#dc2626',
                    glow: 'rgba(239,68,68,0.15)',
                },
                text: {
                    primary: '#ffffff',
                    secondary: '#b0bfd4',
                    muted: '#7a8fa8',
                    inverse: '#0f0f1e',
                },
            },
            fontFamily: {
                sans: ['Inter', 'system-ui', '-apple-system', 'sans-serif'],
                mono: ['JetBrains Mono', 'Menlo', 'Consolas', 'monospace'],
                price: ['JetBrains Mono', 'Menlo', 'Consolas', 'monospace'],
                display: ['Inter', 'system-ui', '-apple-system', 'sans-serif'],
                body: ['Inter', 'system-ui', '-apple-system', 'sans-serif'],
            },
            // ── Trading-specific font sizes ───────────────────────────────────
            fontSize: {
                'price-lg': ['clamp(1.125rem, 1.5vw, 1.5rem)', { lineHeight: '1', letterSpacing: '-0.02em', fontWeight: '600' }],
                'price-md': ['clamp(0.875rem, 1vw, 1.125rem)', { lineHeight: '1', letterSpacing: '-0.01em', fontWeight: '600' }],
                'price-sm': ['0.875rem', { lineHeight: '1', letterSpacing: '-0.01em', fontWeight: '500' }],
                'label': ['0.6875rem', { lineHeight: '1.2', letterSpacing: '0.04em', fontWeight: '500' }],
                'adaptive': ['clamp(0.75rem, 0.8vw, 0.875rem)', { lineHeight: '1.4' }],
            },
            spacing: {
                'panel-gap': '2px',
            },
            // ── Shadows ───────────────────────────────────────────────────────
            boxShadow: {
                'card': '0 1px 3px rgba(0,0,0,0.2)',
                'card-hover': '0 8px 24px rgba(0,188,212,0.12), 0 2px 8px rgba(0,188,212,0.06)',
                'panel': '0 4px 24px rgba(0,188,212,0.12)',
                'bull': '0 0 12px rgba(16,185,129,0.3)',
                'bear': '0 0 12px rgba(239,68,68,0.3)',
                'focused': '0 0 0 2px rgba(0,188,212,0.4)',
                'glow-gold': '0 0 20px rgba(0,188,212,0.20)',
                'glow-blue': '0 0 20px rgba(0,188,212,0.20)',
            },
            // ── Animations ────────────────────────────────────────────────────
            animation: {
                // existing
                'fade-in': 'fadeIn 0.3s ease-out',
                'fadeIn': 'fadeIn 0.25s ease-out',
                'slide-up': 'slideUp 0.3s ease-out',
                'slide-in-right': 'slideInRight 0.3s ease-out',
                'pulse-subtle': 'pulseSubtle 2s ease-in-out infinite',
                'glow': 'glow 2s ease-in-out infinite alternate',
                // new trading-grade
                'price-up': 'priceFlash 600ms ease-out',
                'price-down': 'priceFlashRed 600ms ease-out',
                'skeleton': 'shimmer 1.5s infinite',
                'slide-in': 'slideIn 200ms ease-out',
                'marquee': 'marquee 40s linear infinite',
                'float': 'float 6s ease-in-out infinite',
                'shimmer-slow': 'shimmerSlow 3s ease-in-out infinite',
                // modal animations
                'scale-in': 'scaleIn 0.2s ease-out',
                'slide-in-left': 'slideInLeft 0.3s ease-out',
            },
            keyframes: {
                // existing
                fadeIn: {
                    '0%': { opacity: '0' },
                    '100%': { opacity: '1' },
                },
                slideUp: {
                    '0%': { opacity: '0', transform: 'translateY(10px)' },
                    '100%': { opacity: '1', transform: 'translateY(0)' },
                },
                slideInRight: {
                    '0%': { opacity: '0', transform: 'translateX(20px)' },
                    '100%': { opacity: '1', transform: 'translateX(0)' },
                },
                pulseSubtle: {
                    '0%, 100%': { opacity: '1' },
                    '50%': { opacity: '0.8' },
                },
                glow: {
                    '0%': { boxShadow: '0 0 5px rgba(0, 188, 212, 0.2)' },
                    '100%': { boxShadow: '0 0 20px rgba(0, 188, 212, 0.4)' },
                },
                // new
                priceFlash: {
                    '0%': { backgroundColor: 'rgba(38,166,154,0.35)' },
                    '100%': { backgroundColor: 'transparent' },
                },
                priceFlashRed: {
                    '0%': { backgroundColor: 'rgba(239,83,80,0.35)' },
                    '100%': { backgroundColor: 'transparent' },
                },
                shimmer: {
                    '0%': { backgroundPosition: '-200% 0' },
                    '100%': { backgroundPosition: '200% 0' },
                },
                slideIn: {
                    '0%': { transform: 'translateY(-4px)', opacity: '0' },
                    '100%': { transform: 'translateY(0)', opacity: '1' },
                },
                marquee: {
                    '0%': { transform: 'translateX(0)' },
                    '100%': { transform: 'translateX(-50%)' },
                },
                float: {
                    '0%, 100%': { transform: 'translateY(0px)' },
                    '50%': { transform: 'translateY(-12px)' },
                },
                shimmerSlow: {
                    '0%, 100%': { opacity: '0.5' },
                    '50%': { opacity: '1' },
                },
                scaleIn: {
                    '0%': { transform: 'scale(0.95)', opacity: '0' },
                    '100%': { transform: 'scale(1)', opacity: '1' },
                },
                slideInLeft: {
                    '0%': { transform: 'translateX(-100%)', opacity: '0' },
                    '100%': { transform: 'translateX(0)', opacity: '1' },
                },
            },
        },
    },
    plugins: [],
}
