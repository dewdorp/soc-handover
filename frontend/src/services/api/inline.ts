/**
 * 본문 그림 올리기 — 스크린샷 붙여넣기 · 끌어다 놓기 · 파일 선택.
 *
 * 글을 저장하기 전에도 올릴 수 있다(서버가 '초안'으로 받아 올린 사람에게만 보여 준다).
 * 글을 저장하면 본문에 남은 그림만 그 글에 묶이고, 하루 안에 저장하지 않은 그림은 지워진다.
 * 그림은 Base64 로 본문에 넣지 않는다 — 늘 이 주소(/api/v1/attachments/{id}/inline)로 가리킨다.
 */
import { upload } from './client'

export interface InlineImage {
  id: number
  url: string
  name: string
  mime: string
  size: number
}

export const inlineApi = {
  upload: (file: File) => {
    const form = new FormData()
    form.append('file', file, file.name || 'screenshot.png')
    return upload<InlineImage>('/attachments/inline', form)
  },
}
