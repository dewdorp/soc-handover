/**
 * 최근 검색어 — **지금 로그인한 사람의, 지금 세션 동안만**.
 *
 * 교대 PC 는 한 브라우저를 여러 사람이 돌려 쓴다. 예전에는 localStorage 의 공용 키
 * (soc.recent-search)에 담아, 주간 근무자가 찾은 사고명·관계사명이 야간 근무자 화면에
 * 그대로 남았다(재현 ④). 그래서
 *
 *   · 디스크에 쓰지 않는다 — 이 탭의 메모리에만 둔다(새로고침·다른 탭·뒤로 가기에 남지 않는다).
 *   · 사용자 id 를 함께 들고 있다가 주인이 다르면 아예 돌려주지 않는다(같은 탭에서 계정만 바뀐 경우).
 *   · 로그아웃·계정 전환 때 지운다(clearRecentSearches).
 *   · 예전 버전이 남긴 공용 키는 처음 불러올 때 지운다.
 */
const LEGACY_KEY = 'soc.recent-search'
const MAX = 5

let ownerId: number | null = null
let terms: string[] = []

/** 예전 버전이 디스크에 남긴 공용 최근 검색어를 지운다(한 번만). */
function dropLegacy(): void {
  try {
    localStorage.removeItem(LEGACY_KEY)
    sessionStorage.removeItem(LEGACY_KEY)
  } catch {
    /* 저장소를 못 쓰는 환경(사생활 보호 모드 등)은 애초에 남은 것이 없다 */
  }
}
dropLegacy()

export function recentSearches(userId?: number | null): string[] {
  if (userId == null || ownerId !== userId) return []
  return terms.slice(0, MAX)
}

export function rememberSearch(term: string, userId?: number | null): void {
  const q = term.trim()
  if (!q || userId == null) return
  if (ownerId !== userId) {
    ownerId = userId
    terms = []
  }
  terms = [q, ...terms.filter((x) => x !== q)].slice(0, MAX)
}

/** 로그아웃 · 계정 전환 · 세션 초기화 때 호출한다. */
export function clearRecentSearches(): void {
  ownerId = null
  terms = []
  dropLegacy()
}
