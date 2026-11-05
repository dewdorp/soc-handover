/** 다른 탭과는 인증 변경 신호만 주고받는다. 계정이나 메모 내용은 저장하지 않는다. */
const eventName = 'soc-session-changed'
let channel: BroadcastChannel | undefined
try { channel = new BroadcastChannel(eventName) } catch { /* 지원하지 않는 환경은 storage 이벤트 사용 */ }

export function announceSessionChange() {
  if (channel) channel.postMessage(null)
  else {
    try { localStorage.setItem(eventName, String(Math.random())) } catch { /* 저장소 차단 환경 */ }
  }
}

export function rejectStaleSession(expectedUserId: number) {
  window.dispatchEvent(new CustomEvent(eventName, { detail: expectedUserId }))
}

export function watchSessionChanges(reset: (expectedUserId?: number) => void) {
  const remote = () => reset()
  const local = (e: Event) => reset((e as CustomEvent<number>).detail)
  const onStorage = (e: StorageEvent) => { if (e.key === eventName) reset() }
  const onRestore = (e: PageTransitionEvent) => { if (e.persisted) reset() }
  channel?.addEventListener('message', remote)
  window.addEventListener('storage', onStorage)
  window.addEventListener('pageshow', onRestore)
  window.addEventListener(eventName, local)
  return () => {
    channel?.removeEventListener('message', remote)
    window.removeEventListener('storage', onStorage)
    window.removeEventListener('pageshow', onRestore)
    window.removeEventListener(eventName, local)
  }
}
