import { createContext, useContext, useState, useCallback } from 'react'

const AppContext = createContext(null)

const TYPE_LABEL = { grammar_cloze:'语法选择', cloze:'完形填空', reading_comp:'阅读理解', true_false:'正误判断' }
const VARIANT_LABEL = { open_ended:'开放型填空' }
const TTS_AUTO_MAP = {
  grammar_cloze: ['解析','考点','上下文'],
  cloze: ['解析','考点','上下文'],
  reading_comp: ['解析','考点','题干定位'],
  true_false: ['解析','考点','原句/题干','原文依据']
}

export function AppProvider({ children }) {
  const [screen, setScreen] = useState('home')
  const [pendingFiles, setPendingFiles] = useState(null)
  const [examData, setExamData] = useState(null)
  const [history, setHistory] = useState([])
  const [histPage, setHistPage] = useState(1)
  const [histDone, setHistDone] = useState(false)
  const [config, setConfig] = useState({ apiBase:'', pageSize:20, allowedTypes:[] })

  const examType = examData?.exam_type || ''
  const variant = examData?.variant || ''
  const questions = examData?.questions || []

  const ttsAutoSeq = TTS_AUTO_MAP[examType] || []
  const typeLabel = TYPE_LABEL[examType] || examType
  const variantLabel = variant && variant !== 'multiple_choice' ? VARIANT_LABEL[variant] || variant : ''

  const goHome = useCallback(() => { setScreen('home'); setPendingFiles(null) }, [])
  const goProcessing = useCallback((files) => { setPendingFiles(files); setScreen('processing') }, [])
  const goReview = useCallback((data) => { setExamData(data); setPendingFiles(null); setScreen('review') }, [])

  const loadReviewFromHistory = useCallback(async (id, apiBase) => {
    setScreen('processing')
    setPendingFiles(null)
    try {
      const r = await fetch(apiBase + '/exams/' + id)
      const e = await r.json()
      if (e.tutorial) {
        goReview({
          questions: JSON.parse(e.tutorial),
          exam_id: e.id,
          exam_type: e.exam_type || '',
          variant: e.variant || '',
          passage: e.passage || '',
          s1_questions: e.s1_questions ? JSON.parse(e.s1_questions) : [],
          warnings: [],
        })
      } else {
        setScreen('home')
      }
    } catch { setScreen('home') }
  }, [goReview])

  return (
    <AppContext.Provider value={{
      screen, setScreen, goHome, goProcessing, goReview, loadReviewFromHistory,
      pendingFiles,
      examData, setExamData, examType, variant, questions,
      history, setHistory, histPage, setHistPage, histDone, setHistDone,
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
