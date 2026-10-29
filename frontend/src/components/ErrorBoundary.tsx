import { Component, type ErrorInfo, type ReactNode } from 'react'
import { Button } from '@/components/ui/button'

interface State { error: Error | null }

/** Keeps a crash on one screen from blanking the whole app: shows what went wrong and lets the person carry on. */
export class ErrorBoundary extends Component<{ children: ReactNode }, State> {
  state: State = { error: null }

  static getDerivedStateFromError(error: Error): State {
    return { error }
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error('Screen crashed', error, info.componentStack)
  }

  render() {
    if (!this.state.error) return this.props.children
    return (
      <div role="alert" className="mx-auto max-w-lg space-y-3 rounded-xl border border-danger/30 bg-danger-soft p-5 text-sm">
        <p className="text-base font-semibold text-danger">This screen hit a problem</p>
        <p>The rest of the app still works. Try again, or use the menu to go somewhere else. If it keeps happening, tell your administrator what is written below.</p>
        <pre className="whitespace-pre-wrap rounded bg-surface p-2 text-xs">{this.state.error.message}</pre>
        <Button variant="outline" onClick={() => this.setState({ error: null })}>Try again</Button>
      </div>
    )
  }
}
