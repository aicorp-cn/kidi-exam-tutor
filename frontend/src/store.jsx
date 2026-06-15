import { createContext, useContext, useState, useCallback, useEffect, useRef } from 'react'
import { persistDeviceToken, getPersistedDeviceToken, getDeviceTokenFromIDB } from './device'
import { KEYS, sessionGet, sessionSet } from './storage'

const AppContext = createContext(null)

const TYPE_LABEL = { grammar_cloze:'语法选择', cloze:'完形填空', reading_comp:'阅读理解', true_false:'正误判断' }
const VARIANT_LABEL = { open_ended:'开放型填空' }
const TTS_AUTO_MAP = {
  grammar_cloze: ['解析','考点','上下文'],
  cloze: ['解析','考点','上下文'],
  reading_comp: ['解析','考点','题干定位'],
  true_false: ['解析','考点','原句/题干','原文依据']
}

const HASH_SCREEN = { '': 'home', '#home': 'home', '#history': 'history', '#review': 'review', '#profile': 'profile' }
const SCREEN_HASH = { home: '#home', history: '#history', review: '#review', profile: '#profile' }
// Screens that require authentication
const PROTECTED = new Set(['home', 'history', 'review', 'profile'])
// Screens that are transient and should not appear in hash
const TRANSIENT = new Set(['processing', 'login'])

function getScreenFromHash() {
  return HASH_SCREEN[window.location.hash] || 'home'
}

function loadStoredUser() {
  try {
    const raw = localStorage.getItem('exam_tutor_user')
    return raw ? JSON.parse(raw) : null
  } catch { return null }
}

export function AppProvider({ children }) {
  // ── State ──
  const [screen, setScreen] = useState(() => getScreenFromHash())
  const [pendingFiles, setPendingFiles] = useState(null)
  const [examData, setExamData] = useState(null)
  const [history, setHistory] = useState([])
  const [historyVersion, setHistoryVersion] = useState(0)
  const [config, setConfig] = useState({ apiBase:'', pageSize:20, allowedTypes:[] })

  // Auth state
  const [authToken, setAuthToken] = useState(null)
  const [currentUser, setCurrentUser] = useState(null)
  const [logoutMessage, setLogoutMessage] = useState('')
  const [storedUser, setStoredUser] = useState(loadStoredUser)
  // Prevent auth guard from firing before auth restore completes on mount
  const [authReady, setAuthReady] = useState(false)

  // Auth guard: when authToken becomes null, force redirect to login
  const authRef = useRef(authToken)
  authRef.current = authToken

  // ── Auth helpers ──

  const setAuth = useCallback((token, user) => {
    setAuthToken(token)
    setCurrentUser(user)
    const u = { student_id: user.student_id, name: user.name, has_password: !!user.has_password }
    localStorage.setItem('exam_tutor_user', JSON.stringify(u))
    localStorage.setItem('exam_tutor_token', token)
    setStoredUser(u)
    if (user.device_token) {
      persistDeviceToken(user.device_token)
    }
    setScreen('home')
  }, [])

  const clearAuth = useCallback(() => {
    localStorage.removeItem('exam_tutor_token')
    setAuthToken(null)
    setCurrentUser(null)
    setLogoutMessage('已安全退出')
    setScreen('login')
    // Clear hash so back button doesn't return to protected page
    if (window.location.hash) {
      window.location.hash = ''
    }
  }, [])

  const forgetUser = useCallback(() => {
    localStorage.removeItem('exam_tutor_user')
    localStorage.removeItem('exam_tutor_token')
    setStoredUser(null)
    setAuthToken(null)
    setCurrentUser(null)
    setLogoutMessage('')
  }, [])

  // ── Init effects ──

  // Config + device self-heal (fire-and-forget, no screen dependency)
  useEffect(() => {
    fetch('/api/config')
      .then(r => r.json())
      .then(cfg => setConfig({
        apiBase: cfg.api_base || '',
        pageSize: cfg.page_size || 20,
        allowedTypes: cfg.allowed_types || [],
      }))
      .catch(() => {})
    getPersistedDeviceToken()
    getDeviceTokenFromIDB()
  }, [])

  // Auth restore — respects initial hash
  useEffect(() => {
    const token = localStorage.getItem('exam_tutor_token')
    if (!token) {
      setAuthReady(true)
      setScreen('login')
      return
    }
    fetch(config.apiBase + '/auth/me', {
      headers: { 'Authorization': 'Bearer ' + token },
    }).then(r => r.ok ? r.json() : null)
      .then(user => {
        if (user) {
          setAuthToken(token)
          setCurrentUser(user)
          // Navigate to the hash target, not unconditionally 'home'
          const hashTarget = getScreenFromHash()
          const resolved = TRANSIENT.has(hashTarget) ? 'home' : hashTarget
          setScreen(resolved)
        } else {
          localStorage.removeItem('exam_tutor_token')
          setScreen('login')
        }
      })
      .catch(() => setScreen('login'))
      .finally(() => setAuthReady(true))
  }, [config.apiBase])

  // Hash → Screen sync (bi-directional)
  useEffect(() => {
    const onHash = () => {
      const s = getScreenFromHash()
      // Don't override transient screens via hash
      if (TRANSIENT.has(s)) return
      setScreen(s)
    }
    window.addEventListener('hashchange', onHash)
    return () => window.removeEventListener('hashchange', onHash)
  }, [])

  // Review restore: MUST wait for authReady before deciding.
  // Otherwise auth restore races and overwrites the hash, losing user intent.
  useEffect(() => {
    if (!authReady) return
    if (screen !== 'review') return
    if (examData) return  // Already loaded
    try {
      const stored = sessionGet(KEYS.REVIEW)
      if (stored) {
        setExamData(stored)
      } else {
        // No review data — likely direct URL / tab reopen.
        // Redirect to history (natural fallback), not home.
        navigateInternal('history')
      }
    } catch {
      navigateInternal('history')
    }
  }, [screen, examData, authReady])

  // ── Derived ──

  const examType = examData?.exam_type || ''
  const variant = examData?.variant || ''
  const questions = examData?.questions || []
  const ttsAutoSeq = TTS_AUTO_MAP[examType] || []
  const typeLabel = TYPE_LABEL[examType] || examType
  const variantLabel = variant && variant !== 'multiple_choice' ? VARIANT_LABEL[variant] || variant : ''

  // ── Navigation — single source of truth ──

  const navigateInternal = useCallback((s) => {
    setScreen(s)
    const h = SCREEN_HASH[s]
    if (h && window.location.hash !== h) {
      window.location.hash = h
    }
  }, [])

  // Public navigate: enforces auth guard for protected pages
  const navigate = useCallback((s) => {
    if (PROTECTED.has(s) && !authRef.current) {
      setScreen('login')
      if (window.location.hash) window.location.hash = ''
      return
    }
    navigateInternal(s)
  }, [navigateInternal])

  // switchScreen for transient screens (processing, login without logout)
  // Bypasses hash sync AND auth guard — caller must ensure valid context
  const switchScreen = useCallback((s) => {
    setScreen(s)
  }, [])

  // ── Screen transitions ──

  const goHome = useCallback(() => { navigate('home'); setPendingFiles(null) }, [navigate])
  const goProcessing = useCallback((files) => { setPendingFiles(files); switchScreen('processing') }, [switchScreen])
  const refreshHistory = useCallback(() => setHistoryVersion(v => v + 1), [])

  const goReview = useCallback((data) => {
    setExamData(data)
    sessionSet(KEYS.REVIEW, data)
    setPendingFiles(null)
    refreshHistory()
    navigate('review')
  }, [navigate, refreshHistory])

  const goHistory = useCallback(() => { navigate('history') }, [navigate])
  const goProfile = useCallback(() => { navigate('profile') }, [navigate])
  const goLogin = useCallback(() => { clearAuth() }, [clearAuth])

  const loadReviewFromHistory = useCallback(async (id, apiBase) => {
    try {
      const r = await fetch(apiBase + '/review/' + id, {
        headers: { 'Authorization': 'Bearer ' + authRef.current },
      })
      const data = await r.json()
      if (data.questions?.length) { goReview(data); return }
      goHome()
    } catch {
      goHome()
    }
  }, [goReview, goHome])

  // ── Auth guard (App-level) ──

  // If on a protected screen without auth, redirect to login.
  // This catches: expired tokens, browser-back after logout, hash manipulation.
  // Must NOT fire before auth restore completes (authReady gate).
  useEffect(() => {
    if (!authReady) return
    if (PROTECTED.has(screen) && !authToken) {
      setScreen('login')
      if (window.location.hash) window.location.hash = ''
    }
  }, [screen, authToken, authReady])

  return (
    <AppContext.Provider value={{
      screen, setScreen, goHome, goProcessing, goReview, goHistory, goProfile, goLogin,
      loadReviewFromHistory,
      pendingFiles, authToken, currentUser, setCurrentUser, setAuth, clearAuth,
      logoutMessage, setLogoutMessage, storedUser, setStoredUser, forgetUser,
      examData, setExamData, examType, variant, questions,
      history, setHistory, historyVersion, refreshHistory,
      config, setConfig, ttsAutoSeq, typeLabel, variantLabel,
      TYPE_LABEL, VARIANT_LABEL,
      authReady, PROTECTED,
    }}>
      {children}
    </AppContext.Provider>
  )
}

export function useApp() {
  const ctx = useContext(AppContext)
  if (!ctx) throw new Error('useApp must be used within AppProvider')
  return ctx
}
