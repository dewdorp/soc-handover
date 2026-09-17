import { Construction } from 'lucide-react'

/**
 * 아직 구현되지 않은 화면을 "동작하는 척" 보여주지 않기 위한 컴포넌트.
 * 어떤 Phase 에서 어떤 기능이 들어오는지 명시한다(§88 Mock 화면 금지).
 */
export default function PhasePlaceholder({
  title, phase, items,
}: { title: string; phase: string; items: string[] }) {
  return (
    <div className="p-4">
      <div className="card p-4 max-w-2xl">
        <div className="flex items-center gap-2 mb-2">
          <Construction size={16} className="text-amber-600" />
          <h1 className="text-md font-semibold">{title}</h1>
          <span className="chip ml-auto">{phase} 구현 예정</span>
        </div>
        <p className="text-sm text-ink-muted mb-3">
          이 화면은 아직 구현되지 않았습니다. 동작하지 않는 화면을 미리 보여주지 않기 위해
          구현 예정 내용만 표시합니다.
        </p>
        <ul className="text-sm space-y-1">
          {items.map((i) => (
            <li key={i} className="flex gap-2">
              <span className="text-ink-faint">·</span>
              <span>{i}</span>
            </li>
          ))}
        </ul>
      </div>
    </div>
  )
}
