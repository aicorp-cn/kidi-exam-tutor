// sessionStorage 统一访问层 — 命名空间 + 版本化 + 错误日志
//
// Keys (single registry):
//   exam_tutor:v1:review        — exam review data
//   exam_tutor:v1:history_state — search & typeFilter

const NS = 'exam_tutor'
const VERSION = 'v1'

function scoped(key) {
  return `${NS}:${VERSION}:${key}`
}

export const KEYS = {
  REVIEW:        scoped('review'),
  HISTORY_STATE: scoped('history_state'),
  MANUAL_LOGOUT: scoped('manual_logout'),
}

export function sessionGet(key) {
  try {
    const raw = sessionStorage.getItem(key)
    return raw ? JSON.parse(raw) : null
  } catch (e) {
    console.warn('[sessionStorage] read failed:', key, e)
    return null
  }
}

export function sessionSet(key, value) {
  try {
    sessionStorage.setItem(key, JSON.stringify(value))
  } catch (e) {
    console.warn('[sessionStorage] write failed:', key, e)
  }
}

export function sessionRemove(key) {
  try {
    sessionStorage.removeItem(key)
  } catch (e) {
    console.warn('[sessionStorage] remove failed:', key, e)
  }
}
