import { createContext, useContext, useState, useCallback, useEffect } from 'react'

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
  const [screen, setScreen] = useState('login')
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

  const setAuth = useCallback((token, user) => {
    setAuthToken(token)
    setCurrentUser(user)
    // Persist user identity so next visit shows "Welcome back"
    const u = { student_id: user.student_id, name: user.name, has_password: !!user.has_password }
    localStorage.setItem('exam_tutor_user', JSON.stringify(u))
    setStoredUser(u)
    setScreen('home')
  }, [])

  const clearAuth = useCallback(() => {
    localStorage.removeItem('exam_tutor_token')
    setAuthToken(null)
    setCurrentUser(null)
    // Keep exam_tutor_user — same-device returning users get "Welcome back"
    setLogoutMessage('已安全退出')
    setScreen('login')
  }, [])

  const forgetUser = useCallback(() => {
    localStorage.removeItem('exam_tutor_user')
    localStorage.removeItem('exam_tutor_token')
    setStoredUser(null)
    setAuthToken(null)
    setCurrentUser(null)
    setLogoutMessage('')
  }, [])

  // Load config on mount
  useEffect(() => {
    fetch('/api/config')
      .then(r => r.json())
      .then(cfg => setConfig({
        apiBase: cfg.api_base || '',
        pageSize: cfg.page_size || 20,
        allowedTypes: cfg.allowed_types || [],
      }))
      .catch(() => {})
  }, [])

  // Restore auth from localStorage
  useEffect(() => {
    const token = localStorage.getItem('exam_tutor_token')
    if (!token) {
      // No token — show login. storedUser may exist (for "Welcome back")
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
          setScreen('home')
        } else {
          localStorage.removeItem('exam_tutor_token')
          setScreen('login')
        }
      })
      .catch(() => setScreen('login'))
  }, [config.apiBase])

  // Hash routing
  useEffect(() => {
    const onHash = () => {
      const s = getScreenFromHash()
      if (s === 'processing') return
      setScreen(s)
    }
    window.addEventListener('hashchange', onHash)
    return () => window.removeEventListener('hashchange', onHash)
  }, [])

  // Review state restore
  useEffect(() => {
    if (screen === 'review' && !examData) {
      try {
        const stored = sessionStorage.getItem('exam_review')
        if (stored) setExamData(JSON.parse(stored))
        else window.location.hash = '#home'
      } catch { window.location.hash = '#home' }
    }
  }, [screen, examData])

  const navigate = useCallback((s) => {
    setScreen(s); const h = SCREEN_HASH[s]
    if (h && window.location.hash !== h) window.location.hash = h
  }, [])
  const switchScreen = useCallback((s) => { setScreen(s) }, [])

  const examType = examData?.exam_type || ''
  const variant = examData?.variant || ''
  const questions = examData?.questions || []
  const ttsAutoSeq = TTS_AUTO_MAP[examType] || []
  const typeLabel = TYPE_LABEL[examType] || examType
  const variantLabel = variant && variant !== 'multiple_choice' ? VARIANT_LABEL[variant] || variant : ''

  const goHome = useCallback(() => { navigate('home'); setPendingFiles(null) }, [navigate])
  const goProcessing = useCallback((files) => { setPendingFiles(files); switchScreen('processing') }, [switchScreen])
  const refreshHistory = useCallback(() => setHistoryVersion(v => v + 1), [])
  const goReview = useCallback((data) => {
    setExamData(data)
    try { sessionStorage.setItem('exam_review', JSON.stringify(data)) } catch {}
    setPendingFiles(null)
    refreshHistory()
    navigate('review')
  }, [navigate, refreshHistory])
  const goHistory = useCallback(() => { navigate('history') }, [navigate])
  const goProfile = useCallback(() => { navigate('profile') }, [navigate])
  const goLogin = useCallback(() => { clearAuth() }, [clearAuth])

  const loadReviewFromHistory = useCallback(async (id, apiBase) => {
    switchScreen('processing'); setPendingFiles([])
    try {
      const r = await fetch(apiBase + '/review/' + id, {
        headers: { 'Authorization': 'Bearer ' + authToken },
      })
      const data = await r.json()
      if (data.questions?.length) { goReview(data); return }
      // Record exists but has no review data — go back to home
      goHome()
    } catch {
      // Network/auth error — go back to home, record is still there
      goHome()
    }
  }, [goReview, goHome, switchScreen, authToken])

  return (
    <AppContext.Provider value={{
      screen, setScreen, goHome, goProcessing, goReview, goHistory, goProfile, goLogin,
      pendingFiles, authToken, currentUser, setCurrentUser, setAuth, clearAuth,
      logoutMessage, setLogoutMessage, storedUser, setStoredUser, forgetUser,
      examData, setExamData, examType, variant, questions,
      history, setHistory, historyVersion, refreshHistory,
      config, setConfig, ttsAutoSeq, typeLabel, variantLabel,
      TYPE_LABEL, VARIANT_LABEL,
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
