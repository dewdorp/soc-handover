/**
 * 한 줄이 망가져도 화면 전체를 삼키지 않게 막는 울타리.
 *
 * 설정 화면에서 값 하나가 예상 밖의 모양이면(예: 목록이어야 할 값이 문자열),
 * 그 줄을 그리다 난 예외가 React 트리를 통째로 지워 **설정 전체가 안 보인다**.
 * 그러면 잘못된 값 하나 때문에 고칠 화면조차 못 여는 막다른 길이 된다.
 * 여기서 줄 단위로 붙잡아, 나머지 줄은 멀쩡히 보이고 그 줄만 원래 값과 함께 보여 준다.
 */
import { Component, type ReactNode } from 'react'

interface Props {
  /** 무엇을 그리다 실패했는지 사람 말로 */
  label: string
  /** 실패했을 때 함께 보여 줄 원래 값(있으면 JSON 으로 보여 준다) */
  raw?: unknown
  children: ReactNode
}

interface State {
  error: Error | null
}

export default class RowErrorBoundary extends Component<Props, State> {
  state: State = { error: null }

  static getDerivedStateFromError(error: Error): State {
    return { error }
  }

  render() {
    const { error } = this.state
    if (!error) return this.props.children
    let raw = ''
    try {
      raw = JSON.stringify(this.props.raw, null, 2) ?? ''
    } catch {
      raw = String(this.props.raw)
    }
    return (
      <div role="alert" className="px-3 py-2.5 space-y-1.5 bg-state-urgent-soft/30">
        <p className="font-medium text-state-urgent">
          ‘{this.props.label}’ 항목을 그리지 못했습니다 — 저장된 값의 모양이 예상과 다릅니다.
        </p>
        <p className="text-sm text-ink-muted">
          다른 항목은 정상입니다. 아래 값을 확인한 뒤 서버에서 바로잡으십시오.
        </p>
        {raw && (
          <pre className="bg-surface-sunken rounded p-2 text-xs whitespace-pre-wrap break-all">{raw}</pre>
        )}
        <p className="text-xs text-ink-faint">{error.message}</p>
      </div>
    )
  }
}
