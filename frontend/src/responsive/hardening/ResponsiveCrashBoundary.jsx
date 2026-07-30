import { Component } from 'react';

export class ResponsiveCrashBoundary extends Component {
  constructor(props) {
    super(props);
    this.state = { hasError: false };
  }

  static getDerivedStateFromError() {
    return { hasError: true };
  }

  componentDidCatch(error, info) {
    if (import.meta.env?.DEV) {
      console.error('[ResponsiveCrashBoundary]', error, info);
    }
  }

  render() {
    if (this.state.hasError) {
      return (
        <div className="p-4 text-sm text-gray-500" role="alert">
          {this.props.fallback ?? 'Responsive layer recovered. Refresh if layout looks wrong.'}
        </div>
      );
    }
    return this.props.children;
  }
}

export default ResponsiveCrashBoundary;
