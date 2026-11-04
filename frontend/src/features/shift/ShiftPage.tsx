import { useLocation } from 'react-router-dom'
import CockpitView from '@/features/shift/CockpitView'
import HistoryView from '@/features/shift/HistoryView'
import InboxView from '@/features/shift/InboxView'

export default function ShiftPage() {
  const { pathname } = useLocation()
  const inbox = pathname.startsWith('/shift/inbox')
  const history = pathname.startsWith('/shift/history')
  return (
    <section className="h-full flex flex-col min-h-0">
      <h1 className="sr-only">{inbox ? '인수 확인함' : history ? '인계 이력' : '인계 준비'}</h1>
      {inbox ? <InboxView /> : history ? <HistoryView /> : <CockpitView />}
    </section>
  )
}
