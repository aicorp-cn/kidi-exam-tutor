import { useEffect, useRef, useState } from 'react'
import { useApp } from '../store'
import { useSSE } from '../hooks/useSSE'

const STEPS = ['上传', '识别', '解析', '精讲']
const STALL_TIMEOUT_MS = 90_000  // 90s no progress → timeout

export function ProcessingScreen({ files: initialFiles }) {
  const { goHome, goReview, config, authToken } = useApp()
  const sse = useSSE()
  const timeoutRef = useRef(null)
  const stallRef = useRef(null)
  const [stalled, setStalled] = useState(false)

  useEffect(() => {
    if (initialFiles?.length) {
      sse.start(initialFiles, config.apiBase, authToken)
    }
  }, [])

  // Safety: redirect if truly dead-end (null/undefined files, not empty array)
  // Empty array = loading from history — parent navigates when fetch completes.
  // Set a 10s safety timeout as fallback.
  useEffect(() => {
    const isDeadEnd = initialFiles === null || initialFiles === undefined
    const isEmptyLoad = Array.isArray(initialFiles) && initialFiles.length === 0
    if (isDeadEnd) {
      timeoutRef.current = setTimeout(() => goHome(), 800)
    } else if (isEmptyLoad) {
      timeoutRef.current = setTimeout(() => goHome(), 10000)
    }
    return () => { if (timeoutRef.current) clearTimeout(timeoutRef.current) }
  }, [])

  // Stall detection: reset on stage change, timeout if stuck
  useEffect(() => {
    if (sse.stage === 'done' || sse.stage === 'error' || sse.stage === 'cancelled') {
      if (stallRef.current) clearTimeout(stallRef.current)
      return
    }
    if (stallRef.current) clearTimeout(stallRef.current)
    stallRef.current = setTimeout(() => {
      sse.cancel()
      setStalled(true)
    }, STALL_TIMEOUT_MS)
    return () => { if (stallRef.current) clearTimeout(stallRef.current) }
  }, [sse.stage])

  // Navigate home when user cancels
  useEffect(() => {
    if (sse.stage === 'cancelled') {
      goHome()
    }
  }, [sse.stage, goHome])

  // Navigate to review when done — cancel timeout
  useEffect(() => {
    if (sse.result && sse.stage === 'done') {
      if (timeoutRef.current) clearTimeout(timeoutRef.current)
      goReview({
        questions: sse.result.questions || [],
        exam_id: sse.result.exam_id || '',
        exam_type: sse.result.exam_type || '',
        variant: sse.result.variant || '',
        passage: sse.result.passage || '',
        s1_questions: sse.result.s1_questions || [],
        warnings: sse.result.warnings || [],
        vocabulary: sse.result.vocabulary || {high:[], medium:[], low:[]},
      })
    }
  }, [sse.result, sse.stage, goReview])

  const isEmptyLoad = Array.isArray(initialFiles) && initialFiles.length === 0
  const stepIdx = sse.stage === 'uploading' ? 0 : sse.stage === 'ocr' ? 1 : sse.stage === 'stage1' ? 2 : sse.stage === 'stage2' ? 3 : sse.stage === 'done' ? 4 : 0
  const pct = sse.stage === 'done' ? 100 : stepIdx === 3 ? 75 : stepIdx * 25 + 10
  const hasError = sse.stage === 'error' || stalled
  const isLoading = isEmptyLoad && !sse.result && !hasError

  return (
    <div className="flex-1 flex flex-col items-center justify-center text-center px-6 gap-6">
      {/* Progress bar */}
      <div className="w-full max-w-[260px]">
        <div className="h-1 bg-exam-border rounded-full overflow-hidden mb-5">
          <div
            className={`h-full rounded-full transition-all duration-700 ease-out ${hasError ? 'bg-exam-error' : 'bg-gradient-to-r from-indigo-400 to-purple-400'}`}
            style={{ width: pct + '%' }}
          />
        </div>
        <div className="flex justify-between">
          {STEPS.map((label, i) => {
            const dotClass = i < stepIdx ? 'bg-exam-success shadow-emerald-400/20' :
              i === stepIdx && !hasError ? 'bg-exam-accent shadow-indigo-400/30 shadow-[0_0_8px]' :
              i === stepIdx && hasError ? 'bg-exam-error shadow-red-400/20' :
              'bg-exam-border'
            return (
              <div key={i} className="flex flex-col items-center gap-2 flex-1">
                <div className={`w-3 h-3 rounded-full transition-all duration-500 ${dotClass}`} />
                <span className="text-[0.68rem] text-exam-text-muted font-medium">{label}</span>
              </div>
            )
          })}
        </div>
      </div>

      {/* Status */}
      {hasError ? (
        <div>
          <div className="text-lg text-exam-error font-semibold mb-2">
            {stalled ? '⏱️ 处理超时' : '❌ 出错了'}
          </div>
          <div className="text-sm text-exam-text-muted mb-5">
            {stalled ? '服务器响应超时，试卷可能已处理完成。请返回首页查看。' : sse.error?.message}
          </div>
          <button onClick={goHome} className="bg-exam-accent text-white px-7 py-2.5 rounded-full text-sm font-semibold active:scale-95 transition-transform">
            返回首页
          </button>
        </div>
      ) : (
        <>
          <div className="text-base text-white font-semibold tracking-tight">{isLoading ? '加载中…' : (sse.statusText || '正在准备…')}</div>
          <div className="text-sm text-exam-text-muted">{isLoading ? '' : sse.detail}</div>
          <div className="text-xs text-exam-text-muted opacity-40">{isLoading ? '正在获取试卷详情' : '通常在 15-30 秒内完成'}</div>
          {['uploading','ocr','stage1','stage2'].includes(sse.stage) && (
            <button onClick={sse.cancel} className="mt-2 text-xs text-exam-text-muted border border-exam-border px-6 py-1.5 rounded-full hover:text-exam-error hover:text-exam-error hover:border-exam-error transition-colors">
              取消
            </button>
          )}
        </>
      )}
    </div>
  )
}
