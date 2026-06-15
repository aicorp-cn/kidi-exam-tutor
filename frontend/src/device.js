// Layer 1: 客户端冗余持久化 — device_token 写入三层存储
// localStorage ←→ Cookie ←→ IndexedDB
// 任一命中 = known_device，并自愈其余层。

export async function persistDeviceToken(token) {
  localStorage.setItem('_dt', token)

  try {
    await new Promise((resolve, reject) => {
      const req = indexedDB.open('exam_tutor', 1)
      req.onupgradeneeded = () => req.result.createObjectStore('device')
      req.onsuccess = () => {
        const tx = req.result.transaction('device', 'readwrite')
        const putReq = tx.objectStore('device').put({ id: 'current', token })
        putReq.onsuccess = () => resolve()
        putReq.onerror = reject
        tx.onerror = reject
      }
      req.onerror = reject
    })
  } catch {
    // IndexedDB 不可用（隐私模式等），静默跳过
  }

  document.cookie = `_dt=${token}; max-age=31536000; SameSite=Lax; path=/`
}

export function getPersistedDeviceToken() {
  const ls = localStorage.getItem('_dt')
  if (ls) return ls

  const ck = document.cookie.split('; ').find(r => r.startsWith('_dt='))
  if (ck) {
    const token = ck.split('=')[1]
    localStorage.setItem('_dt', token) // 自愈：写回 localStorage
    return token
  }

  return null // IndexedDB 走异步路径 getDeviceTokenFromIDB()
}

export async function getDeviceTokenFromIDB() {
  try {
    return await new Promise((resolve) => {
      const req = indexedDB.open('exam_tutor', 1)
      req.onupgradeneeded = () => req.result.createObjectStore('device')
      req.onsuccess = () => {
        const tx = req.result.transaction('device', 'readonly')
        const get = tx.objectStore('device').get('current')
        get.onsuccess = () => {
          const token = get.result?.token
          if (token) {
            localStorage.setItem('_dt', token)        // 自愈
            document.cookie = `_dt=${token}; max-age=31536000; SameSite=Lax; path=/`
          }
          resolve(token || null)
        }
        get.onerror = () => resolve(null)
      }
      req.onerror = () => resolve(null)
    })
  } catch { return null }
}
