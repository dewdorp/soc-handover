/** 최근 검색어 — 이 브라우저에만 남는 편의 기능. 저장소를 못 쓰면(사생활 보호 모드 등) 조용히 건너뛴다. */
const KEY = 'soc.recent-search'
const MAX = 5

export function recentSearches(): string[] {
  try {
    const raw = JSON.parse(localStorage.getItem(KEY) ?? '[]')
    return Array.isArray(raw) ? raw.filter((x): x is string => typeof x === 'string').slice(0, MAX) : []
  } catch {
    return []
  }
}

export function rememberSearch(term: string): void {
  const q = term.trim()
  if (!q) return
  try {
    localStorage.setItem(KEY, JSON.stringify([q, ...recentSearches().filter((x) => x !== q)].slice(0, MAX)))
  } catch {
    /* 저장하지 못해도 검색은 된다 */
  }
}
