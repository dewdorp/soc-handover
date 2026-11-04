import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { authApi, systemApi } from '@/services/api/auth'
import { ApiRequestError } from '@/services/api/client'
import { announceSessionChange } from '@/services/sessionChanges'
import type { Features, Me } from '@/types/api'

export function useMe() {
  return useQuery<Me | null>({
    queryKey: ['me'],
    queryFn: async () => {
      try {
        return await authApi.me()
      } catch (err) {
        if (err instanceof ApiRequestError && err.status === 401) return null
        throw err
      }
    },
    staleTime: 60_000,
    retry: false,
  })
}

export function useFeatures() {
  const { data: me } = useMe()
  return useQuery<Features>({
    queryKey: ['features'],
    queryFn: systemApi.features,
    enabled: Boolean(me),
    staleTime: 5 * 60_000,
    retry: false,
  })
}

export function useLogin() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ username, password }: { username: string; password: string }) =>
      authApi.login(username, password),
    onSuccess: (me) => {
      announceSessionChange()
      qc.setQueryData(['me'], me)
      qc.invalidateQueries({ queryKey: ['features'] })
    },
  })
}

export function useLogout() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: authApi.logout,
    onSuccess: announceSessionChange,
    onSettled: () => {
      qc.clear()
    },
  })
}

/** 권한 확인. 서버 RBAC의 사본이 아니라 UI 노출 제어용이다(실제 차단은 서버가 한다). */
export function useCan() {
  const { data: me } = useMe()
  return (permission: string) => Boolean(me?.permissions.includes(permission))
}
