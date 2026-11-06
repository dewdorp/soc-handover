/**
 * 인수인계에서 '관련 절차 열기'.
 *
 * 야간에 처음 보는 이벤트를 받은 사람이 절차를 찾으려고 화면을 옮겨 다니게 두면,
 * 결국 안 찾고 넘긴다. 그래서 인계 옆에 바로 붙인다.
 *   · 걸어 둔 문서는 그대로 보여 준다.
 *   · 걸어 둔 것이 없으면 제목에 쓰인 말로 찾아 추천한다(규칙 기반 — AI 가 아니다).
 * 볼 수 없는 문서는 서버가 빼고 주므로 여기에 나오지 않는다.
 */
import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { BookOpen } from 'lucide-react'
import { knowledgeApi } from '@/services/api/knowledge'

export default function RelatedKnowledge({ handoverId, title }: { handoverId: number; title: string }) {
  const linked = useQuery({
    queryKey: ['knowledge-for-handover', handoverId],
    queryFn: () => knowledgeApi.forHandover(handoverId),
  })
  const suggested = useQuery({
    queryKey: ['knowledge-suggest', handoverId],
    queryFn: () => knowledgeApi.suggest(title, handoverId),
    enabled: linked.isSuccess && linked.data.length === 0,
    staleTime: 60_000,
  })
  const rows = linked.data?.length ? linked.data : (suggested.data ?? [])
  if (!rows.length) return null
  return (
    <section>
      <h3 className="text-ink-muted mb-1 flex items-center gap-1">
        <BookOpen size={13} /> 관련 운영 지식
        {!linked.data?.length && <span className="text-xs">(제목에서 찾은 추천)</span>}
      </h3>
      <ul className="space-y-0.5">
        {rows.map((x) => (
          <li key={x.id} className="text-sm">
            <Link className="text-brand hover:underline break-words" to={`/knowledge?id=${x.id}`}>
              {x.title}
            </Link>
            <span className="text-ink-faint"> · {x.category}</span>
          </li>
        ))}
      </ul>
    </section>
  )
}
