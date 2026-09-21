/**
 * Excel · CSV Import 마법사 (UI_STRUCTURE §7).
 *   ① 파일 → ② Sheet 분석 → ③ 컬럼 매핑 → ④ 미리보기 → ⑤ 검증 → ⑥ 중복검사 → ⑦ Import → ⑧ 결과
 *
 * 진행 중인 Job 은 URL(?job=)에 있다. 새로고침하거나 창을 닫았다 열어도 이어서 본다.
 * 긴 작업은 서버가 백그라운드로 돌리고, 화면은 1초 간격으로 진행률을 묻는다.
 */
import { useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { AlertTriangle, CheckCircle2, Download, FileSpreadsheet, RotateCcw, Search, Upload } from 'lucide-react'
import MappingStep from '@/features/import/MappingStep'
import ReviewStep from '@/features/import/ReviewStep'
import ConfirmDialog from '@/components/ui/ConfirmDialog'
import { useCan } from '@/hooks/useAuth'
import { ApiRequestError } from '@/services/api/client'
import { importApi, type ImportJob, type JobStatus } from '@/services/api/imports'

const STEPS = ['파일', 'Sheet 분석', '컬럼 매핑', '미리보기', '검증', '중복검사', 'Import', '결과']

const PHASE_LABEL: Record<string, string> = {
  STAGE: '원본 적재 · 검증 · 중복검사 중', PREPARE: '검증 · 중복검사 중',
  COMMIT: '인수인계로 가져오는 중', ROLLBACK: '되돌리는 중',
}

function stepOf(job: ImportJob | undefined): number {
  if (!job) return 1
  const byStatus: Partial<Record<JobStatus, number>> = {
    ANALYZED: 3, MAPPED: 3, STAGED: 3, DEDUPED: 6, COMPLETED: 8, ROLLED_BACK: 8,
  }
  if (job.status === 'RUNNING') return job.phase === 'COMMIT' ? 7 : job.phase === 'ROLLBACK' ? 8 : 5
  if (job.status === 'FAILED') return job.phase === 'COMMIT' ? 7 : 5
  return byStatus[job.status] ?? 1
}

export default function ImportWizardPage() {
  const can = useCan()
  const [params, setParams] = useSearchParams()
  const jobId = params.get('job') ? Number(params.get('job')) : null
  const qc = useQueryClient()
  const [remapping, setRemapping] = useState(false)

  const { data: job } = useQuery({
    queryKey: ['import-job', jobId],
    queryFn: () => importApi.get(jobId!),
    enabled: jobId != null,
    // 서버가 일하는 동안만 1초마다 묻는다. 끝나면 멈춘다.
    refetchInterval: (q) => (q.state.data?.status === 'RUNNING' ? 1000 : false),
  })

  const setJob = (id: number | null) => {
    const next = new URLSearchParams(params)
    if (id == null) next.delete('job'); else next.set('job', String(id))
    setParams(next, { replace: false })
  }

  const kick = () => qc.invalidateQueries({ queryKey: ['import-job', jobId] })

  if (!can('import:run')) {
    return <div className="p-6 text-ink-muted">Import 는 근무 관리자 이상만 사용할 수 있습니다.</div>
  }

  const step = stepOf(job)

  return (
    <div className="p-4 space-y-3 max-w-[1280px]">
      <div className="flex items-center gap-2">
        <h1 className="text-md font-medium">Excel · CSV Import</h1>
        {job && <span className="text-ink-muted">· {job.file_name} <span className="text-ink-faint">({job.job_code})</span></span>}
        <span className="flex-1" />
        {job && <button className="btn" onClick={() => setJob(null)}>새 파일</button>}
      </div>

      <ol className="flex flex-wrap gap-1 text-sm" aria-label="진행 단계">
        {STEPS.map((label, i) => {
          const n = i + 1
          const state = n < step ? 'done' : n === step ? 'current' : 'todo'
          return (
            <li key={label} aria-current={state === 'current' ? 'step' : undefined}
                className={`chip ${state === 'current' ? 'bg-brand text-white border-brand'
                  : state === 'done' ? 'text-state-done' : 'text-ink-faint'}`}>
              {state === 'done' ? '✔' : `${'①②③④⑤⑥⑦⑧'[i]}`} {label}
            </li>
          )
        })}
      </ol>

      {!job && <UploadStep onUploaded={(j) => setJob(j.id)} />}

      {job?.status === 'RUNNING' && (
        <div className="card p-4 space-y-2" role="status" aria-live="polite">
          <p>{PHASE_LABEL[job.phase ?? ''] ?? '처리 중'} … <b className="tabular-nums">{job.progress}%</b></p>
          <div className="h-2 bg-surface-sunken rounded overflow-hidden">
            <div className="h-full bg-brand transition-all" style={{ width: `${job.progress}%` }} />
          </div>
          <p className="text-sm text-ink-faint">창을 닫아도 서버에서 계속 진행됩니다. 이 주소로 다시 들어오면 이어서 볼 수 있습니다.</p>
        </div>
      )}

      {job?.status === 'FAILED' && <FailedPanel job={job} onRetry={kick} />}

      {job && (['ANALYZED', 'MAPPED', 'STAGED'].includes(job.status)
        || (job.status === 'DEDUPED' && remapping)) && (
        <>
          {remapping && (
            <button className="btn btn-sm" onClick={() => setRemapping(false)}>← 검토로 돌아가기</button>
          )}
          <MappingStep key={job.id} job={job}
                       onStarted={() => { setRemapping(false); kick() }} />
        </>
      )}

      {job?.status === 'DEDUPED' && !remapping && (
        <ReviewStep job={job} onWorkStarted={kick} onRemap={() => setRemapping(true)} />
      )}

      {job && (job.status === 'COMPLETED' || job.status === 'ROLLED_BACK') && (
        <ResultStep job={job} onChanged={kick} />
      )}

      {!job && <RecentJobs onOpen={setJob} />}
    </div>
  )
}

function UploadStep({ onUploaded }: { onUploaded: (job: ImportJob) => void }) {
  const input = useRef<HTMLInputElement>(null)
  const [dragging, setDragging] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const up = useMutation({
    mutationFn: (file: File) => importApi.upload(file),
    onSuccess: (job) => { setError(null); onUploaded(job) },
    onError: (err) => setError(err instanceof ApiRequestError ? err.message : '올리지 못했습니다.'),
  })
  const pick = (files: FileList | null) => files?.[0] && up.mutate(files[0])

  return (
    <section className="space-y-2">
      <div onDragOver={(e) => { e.preventDefault(); setDragging(true) }}
           onDragLeave={() => setDragging(false)}
           onDrop={(e) => { e.preventDefault(); setDragging(false); pick(e.dataTransfer.files) }}
           className={`card border-dashed border-2 p-8 grid place-items-center gap-2 text-center
                       ${dragging ? 'border-brand bg-brand-soft' : ''}`}>
        <FileSpreadsheet size={28} className="text-ink-faint" />
        <p>① 인수인계 파일(Excel .xlsx 또는 CSV .csv · .tsv)을 끌어다 놓거나</p>
        <button className="btn btn-primary" disabled={up.isPending} onClick={() => input.current?.click()}>
          <Upload size={12} /> {up.isPending ? '분석 중…' : '파일 선택'}
        </button>
        <input ref={input} type="file" accept=".xlsx,.xlsm,.csv,.tsv" className="hidden"
               onChange={(e) => pick(e.target.files)} />
        <p className="text-sm text-ink-faint">
          바로 반영되지 않습니다. 분석 → 매핑 → 검증 → 중복검사를 거쳐 확인한 행만 가져옵니다.
        </p>
        <p className="text-xs text-ink-faint">
          CSV 는 인코딩(한국어 Windows Excel 의 cp949 · UTF-8)과 구분자(쉼표 · 탭 · 세미콜론)를 알아서 맞춥니다.
        </p>
      </div>
      {error && (
        <p role="alert" className="text-sm text-state-urgent bg-red-50 border border-red-200
                                   rounded px-2 py-1">{error}</p>
      )}
    </section>
  )
}

function FailedPanel({ job, onRetry }: { job: ImportJob; onRetry: () => void }) {
  const retry = useMutation({
    mutationFn: () => (job.phase === 'COMMIT' ? importApi.commit(job.id)
      : job.phase === 'ROLLBACK' ? importApi.rollback(job.id) : importApi.stage(job.id)),
    onSuccess: onRetry,
  })
  return (
    <div className="card p-4 space-y-2 border-red-200 bg-red-50">
      <p className="flex gap-1 text-state-urgent font-medium">
        <AlertTriangle size={16} /> 작업이 중단되었습니다 ({PHASE_LABEL[job.phase ?? ''] ?? job.phase})
      </p>
      <p className="text-sm break-words">{job.error_message}</p>
      {job.phase === 'COMMIT' && (
        <p className="text-sm text-ink-muted">
          다시 실행하면 이미 들어간 행은 건너뛰고 남은 행만 가져옵니다(두 번 들어가지 않습니다).
        </p>
      )}
      <button className="btn" disabled={retry.isPending} onClick={() => retry.mutate()}>
        <RotateCcw size={12} /> 다시 실행
      </button>
    </div>
  )
}

function ResultStep({ job, onChanged }: { job: ImportJob; onChanged: () => void }) {
  const can = useCan()
  const navigate = useNavigate()
  const { data: report } = useQuery({
    queryKey: ['import-report', job.id, job.status], queryFn: () => importApi.report(job.id),
  })
  const rollback = useMutation({ mutationFn: () => importApi.rollback(job.id), onSuccess: onChanged })
  const [confirmRollback, setConfirmRollback] = useState(false)

  const imported = report?.imported ?? job.success_rows
  const skipped = (report?.total ?? 0) - imported

  const openInGrid = () => {
    const f = JSON.stringify([{ field: 'import_job_id', op: 'eq', value: job.id }])
    navigate(`/handovers?f=${encodeURIComponent(f)}`)
  }

  return (
    <section className="card p-4 space-y-3">
      {job.status === 'ROLLED_BACK' ? (
        <p className="flex items-center gap-1 font-medium text-state-check">
          <RotateCcw size={16} /> 되돌렸습니다 — {report?.rollback?.removed ?? 0}건 삭제
          {(report?.rollback?.kept_modified ?? 0) > 0 &&
            `, 가져온 뒤 수정된 ${report!.rollback!.kept_modified}건은 남겨 두었습니다`}
        </p>
      ) : (
        <p className="flex items-center gap-1 font-medium text-state-done">
          <CheckCircle2 size={16} /> ⑧ 가져오기 완료
        </p>
      )}
      <div className="flex flex-wrap gap-5">
        <span>총 <b className="tabular-nums">{(report?.total ?? 0).toLocaleString()}</b></span>
        <span>성공 <b className="tabular-nums text-state-done">{imported.toLocaleString()}</b></span>
        <span>중복의심 <b className="tabular-nums text-state-check">{(report?.duplicate ?? 0).toLocaleString()}</b></span>
        <span>실패 <b className="tabular-nums text-state-urgent">{(report?.error ?? 0).toLocaleString()}</b></span>
        <span className="text-ink-muted">가져오지 않음 {Math.max(0, skipped).toLocaleString()} · 빈 행 {(report?.blank ?? 0).toLocaleString()}</span>
      </div>
      <div className="flex gap-2">
        {(report?.error ?? 0) > 0 && (
          <button className="btn" onClick={() => importApi.downloadErrors(job.id)}>
            <Download size={12} /> 오류 Excel 다운로드
          </button>
        )}
        {job.status === 'COMPLETED' && (
          <button className="btn btn-primary" onClick={openInGrid}>
            <Search size={12} /> 가져온 인수인계 보기
          </button>
        )}
        <span className="flex-1" />
        {job.status === 'COMPLETED' && can('import:rollback') && (
          <button className="btn text-state-urgent" disabled={rollback.isPending}
                  onClick={() => setConfirmRollback(true)}>
            <RotateCcw size={12} /> 이 Import 되돌리기
          </button>
        )}
        {confirmRollback && (
          <ConfirmDialog title="이 작업으로 들어온 인수인계를 삭제 처리합니다" confirmLabel="되돌리기" danger
                         busy={rollback.isPending}
                         onCancel={() => setConfirmRollback(false)}
                         onConfirm={() => { setConfirmRollback(false); rollback.mutate() }}>
            <p>가져온 뒤 누군가 수정한 건은 남겨 둡니다.</p>
          </ConfirmDialog>
        )}
      </div>
    </section>
  )
}

function RecentJobs({ onOpen }: { onOpen: (id: number) => void }) {
  const { data } = useQuery({ queryKey: ['import-jobs'], queryFn: importApi.list })
  if (!data?.length) return null
  const LABEL: Record<string, string> = {
    ANALYZED: '매핑 대기', MAPPED: '검증 대기', STAGED: '검증 대기', DEDUPED: '검토 중',
    RUNNING: '진행 중', COMPLETED: '완료', FAILED: '실패', ROLLED_BACK: '되돌림',
  }
  return (
    <section className="card">
      <h2 className="font-medium px-3 pt-2 pb-1">최근 Import</h2>
      <table className="w-full text-base">
        <thead className="text-ink-muted bg-surface-sunken">
          <tr>
            <th className="text-left font-medium px-3 py-1">작업</th>
            <th className="text-left font-medium px-3 py-1">파일</th>
            <th className="text-left font-medium px-3 py-1">상태</th>
            <th className="text-right font-medium px-3 py-1">가져옴</th>
            <th className="text-left font-medium px-3 py-1">시각</th>
          </tr>
        </thead>
        <tbody>
          {data.map((j) => (
            <tr key={j.id} className="border-t border-surface-border/60 hover:bg-surface-sunken cursor-pointer"
                onClick={() => onOpen(j.id)}>
              <td className="px-3 py-1 tabular-nums">{j.job_code}</td>
              <td className="px-3 py-1 truncate max-w-[280px]">{j.file_name}</td>
              <td className="px-3 py-1">{LABEL[j.status] ?? j.status}</td>
              <td className="px-3 py-1 text-right tabular-nums">{j.success_rows.toLocaleString()}</td>
              <td className="px-3 py-1 text-ink-muted tabular-nums">
                {new Date(j.created_at).toLocaleString('ko-KR', { hour12: false })}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  )
}
