/**
 * 백업 현황 — backup.ps1 이 만든 파일과 마지막 백업 경과(일 1회, NFR-08).
 * 웹에서 백업 · 복구를 실행하지 않는다: 백업은 작업 스케줄러 + backup.ps1, 복구는 서버를 멈추고 restore.ps1.
 */
import { useQuery } from '@tanstack/react-query'
import { format, parseISO } from 'date-fns'
import { AlertTriangle, CheckCircle2 } from 'lucide-react'
import { adminApi, formatBytes } from '@/services/api/admin'

/** INSTALL_WINDOWS.md 와 같은 명령 — 설치 폴더에서 관리자 PowerShell 로 한 번 실행. */
const SCHEDULE_CMD = [
  '$action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$PWD\\backup.ps1`""',
  '$trigger = New-ScheduledTaskTrigger -Daily -At 03:00',
  'Register-ScheduledTask -TaskName "SOC-Handover-Backup" -Action $action -Trigger $trigger -RunLevel Highest',
].join('\n')

export default function BackupTab() {
  const { data, isLoading } = useQuery({ queryKey: ['backups'], queryFn: adminApi.backups, refetchInterval: 60_000 })
  if (isLoading || !data) return <p className="text-ink-faint">불러오는 중…</p>
  return (
    <div className="space-y-3 max-w-3xl">
      <section className={`card p-3 flex items-start gap-2 ${data.stale ? 'border-amber-300 bg-amber-50' : ''}`}>
        {data.stale ? <AlertTriangle size={18} className="text-state-check shrink-0" /> : <CheckCircle2 size={18} className="text-state-done shrink-0" />}
        <div>
          <p className="font-medium">
            {data.latest_at ? `마지막 백업 ${format(parseISO(data.latest_at), 'yyyy-MM-dd HH:mm')} (${data.hours_since_latest}시간 전)` : '백업이 없습니다'}
          </p>
          <p className="text-sm text-ink-muted">
            {data.stale ? '하루(26시간) 넘게 백업이 없습니다. 아래 예약 작업을 등록했는지 확인하십시오.' : '일 1회 백업 기준을 지키고 있습니다.'}
            {' '}DB: {data.database === 'sqlite' ? 'SQLite(개발용)' : 'PostgreSQL'} · 첨부 {data.attachments.count.toLocaleString()}개 ({formatBytes(data.attachments.bytes)})
          </p>
        </div>
      </section>

      <section className="card p-3 space-y-1.5">
        <h2 className="font-medium">백업 파일</h2>
        <p className="text-xs text-ink-muted font-mono break-all">{data.backup_dir}</p>
        <table className="w-full text-base">
          <thead className="text-sm text-ink-muted"><tr><th className="text-left font-medium">파일</th><th className="text-right font-medium">크기</th><th className="text-right font-medium">만든 때</th></tr></thead>
          <tbody>
            {data.files.map((f) => (
              <tr key={f.name} className="border-t border-surface-border/60">
                <td className="py-1 font-mono text-sm break-all">{f.name}</td>
                <td className="text-right tabular-nums">{formatBytes(f.size)}</td>
                <td className="text-right tabular-nums text-ink-muted">{format(parseISO(f.modified_at), 'yyyy-MM-dd HH:mm')}</td>
              </tr>
            ))}
            {!data.files.length && <tr><td colSpan={3} className="py-3 text-ink-faint">백업 파일이 없습니다.</td></tr>}
          </tbody>
        </table>
      </section>

      <section className="card p-3 space-y-1.5 text-sm">
        <h2 className="font-medium">백업 · 복구 방법</h2>
        <p>지금 백업: 서버 PC 에서 <code className="bg-surface-sunken px-1 rounded">.\backup.ps1</code> — DB 와 첨부를 함께 백업하고 감사로그에 '백업'으로 남습니다.</p>
        <p>매일 자동 백업 — 설치 폴더에서 관리자 PowerShell 로 한 번 등록(INSTALL_WINDOWS.md 와 같음):</p>
        <pre className="bg-surface-sunken rounded p-2 text-xs whitespace-pre-wrap break-all">{SCHEDULE_CMD}</pre>
        <p>복구: 서버를 멈춘 뒤 <code className="bg-surface-sunken px-1 rounded">.\restore.ps1 -File &lt;백업파일&gt;</code> — 확인 문구를 입력해야 진행되고, 감사로그에 '복구'로 남습니다.
          웹 화면에서 복구하지 않는 것은 복구가 서버를 멈추고 하는 작업이기 때문입니다.</p>
      </section>
    </div>
  )
}
