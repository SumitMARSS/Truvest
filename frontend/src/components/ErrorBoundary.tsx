import { Component, type ErrorInfo, type ReactNode } from "react";

interface Props {
  children: ReactNode;
}

interface State {
  error: Error | null;
}

/** A render-time exception anywhere in the brief used to blank the whole
 * page with no recovery path (docs/AUDIT.md #6.1). This isolates that to a
 * single recoverable panel. */
export class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    // eslint-disable-next-line no-console
    console.error("BriefView render error:", error, info.componentStack);
  }

  render() {
    if (this.state.error) {
      return (
        <div className="rounded-2xl border border-danger/30 bg-danger/5 p-6 text-danger">
          <p className="font-semibold">Something went wrong rendering this brief.</p>
          <p className="mt-2 text-sm text-danger/80">
            The underlying data was fetched successfully — this is a display bug, not a data
            problem. Try running the search again.
          </p>
          <button
            type="button"
            onClick={() => this.setState({ error: null })}
            className="mt-4 rounded-lg bg-danger px-4 py-2 text-sm font-semibold text-white hover:bg-danger/90"
          >
            Try rendering again
          </button>
        </div>
      );
    }
    return this.props.children;
  }
}
