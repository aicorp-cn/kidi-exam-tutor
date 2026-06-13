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

// processing is NOT a navigable route — it's a transient state
const HASH_SCREEN = { '': 'home', '#home': 'home', '#history': 'history', '#review': 'review' }
const SCREEN_HASH = { home: '#home', history: '#history', review: '#review' }

function getScreenFromHash() {
  return HASH_SCREEN[window.location.hash] || 'home'
}

export function AppProvider({ children }) {
  const [screen, setScreen] = useState(getScreenFromHash)
  const [pendingFiles, setPendingFiles] = useState(null)
  const [examData, setExamData] = useState(null)
  const [history, setHistory] = useState([])
  const [historyVersion, setHistoryVersion] = useState(0)
  const [config, setConfig] = useState({ apiBase:'', pageSize:20, allowedTypes:[] })

  useEffect(() => {
    const onHash = () => {
      const s = getScreenFromHash()
      if (s === 'processing') return
      setScreen(s)
    }
    window.addEventListener('hashchange', onHash)
    return () => window.removeEventListener('hashchange', onHash)
  }, [])

  // Refresh safety: restore review data from sessionStorage
  useEffect(() => {
    if (screen === 'review' && !examData) {
      try {
        const stored = sessionStorage.getItem('exam_review')
        if (stored) {
          setExamData(JSON.parse(stored))
        } else {
          window.location.hash = '#home'
        }
      } catch { window.location.hash = '#home' }
    }
  }, [screen, examData])

  const navigate = useCallback((s) => {
    setScreen(s)
    const h = SCREEN_HASH[s]
    if (h && window.location.hash !== h) {
      window.location.hash = h
    }
  }, [])

  // Internal screen switch — no hash change (for transient states)
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

  const loadReviewFromHistory = useCallback(async (id, apiBase) => {
    switchScreen('processing')
    setPendingFiles([])
    try {
      const r = await fetch(apiBase + '/review/' + id)
      const data = await r.json()
      if (data.questions && data.questions.length > 0) {
        goReview(data)
      } else {
        navigate('home')
      }
    } catch { navigate('home') }
  }, [goReview, navigate, switchScreen])

  return (
    <AppContext.Provider value={{
      screen, setScreen, goHome, goProcessing, goReview, goHistory, loadReviewFromHistory,
      pendingFiles,
      examData, setExamData, examType, variant, questions,
      history, setHistory, historyVersion, refreshHistory,
      config, setConfig,
      ttsAutoSeq, typeLabel, variantLabel,
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
