import { Component } from 'react';
import { AlertCircle, RefreshCw } from 'lucide-react';

/**
 * React class-based error boundary.
 *
 * Usage:
 *   <ErrorBoundary fallback="Chart failed to load">
 *     <TradingChart ... />
 *   </ErrorBoundary>
 *
 * Or wrap with the higher-order helper:
 *   withErrorBoundary(TradingChart, 'Chart unavailable')
 */
export default class ErrorBoundary extends Component {
    constructor(props) {
        super(props);
        this.state = { hasError: false, error: null };
    }

    static getDerivedStateFromError(error) {
        return { hasError: true, error };
    }

    componentDidCatch(error, info) {
        if (process.env.NODE_ENV === 'development') {
            console.error('[ErrorBoundary]', error, info.componentStack);
        }
    }

    reset = () => this.setState({ hasError: false, error: null });

    render() {
        if (this.state.hasError) {
            if (this.props.fallback) {
                if (typeof this.props.fallback === 'string') {
                    return (
                        <div className="flex flex-col items-center justify-center h-full min-h-[120px] gap-3 text-center p-4">
                            <AlertCircle className="w-8 h-8 text-red-500/70" />
                            <p className="text-sm text-gray-500">{this.props.fallback}</p>
                            <button
                                onClick={this.reset}
                                className="flex items-center gap-1.5 text-xs text-primary-600 hover:text-primary-500 transition-colors"
                            >
                                <RefreshCw className="w-3.5 h-3.5" />
                                Try again
                            </button>
                        </div>
                    );
                }
                return this.props.fallback;
            }

            return (
                <div className="flex flex-col items-center justify-center h-full min-h-[200px] gap-4 text-center p-6">
                    <AlertCircle className="w-10 h-10 text-red-500/70" />
                    <div>
                        <p className="text-sm font-medium text-gray-400 mb-1">Something went wrong</p>
                        {process.env.NODE_ENV === 'development' && (
                            <p className="text-xs text-gray-600 font-mono max-w-xs truncate">
                                {this.state.error?.message}
                            </p>
                        )}
                    </div>
                    <button
                        onClick={this.reset}
                        className="flex items-center gap-2 px-4 py-2 text-sm bg-surface-800 hover:bg-surface-700 border border-edge/10 rounded-lg text-heading transition-colors"
                    >
                        <RefreshCw className="w-4 h-4" />
                        Try again
                    </button>
                </div>
            );
        }

        return this.props.children;
    }
}

/**
 * Higher-order component that wraps a component in an ErrorBoundary.
 *
 * @param {React.ComponentType} WrappedComponent
 * @param {string} [fallbackMessage]
 */
export function withErrorBoundary(WrappedComponent, fallbackMessage) {
    const displayName = WrappedComponent.displayName || WrappedComponent.name || 'Component';
    const Wrapped = (props) => (
        <ErrorBoundary fallback={fallbackMessage}>
            <WrappedComponent {...props} />
        </ErrorBoundary>
    );
    Wrapped.displayName = `withErrorBoundary(${displayName})`;
    return Wrapped;
}
