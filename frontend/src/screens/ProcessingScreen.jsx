import { useEffect, useRef } from 'react'
import { useApp } from '../store'
import { useSSE } from '../hooks/useSSE'

const STEPS = ['上传', '识别', '解析', '精讲']

export function ProcessingScreen({ files: initialFiles }) {
  const { goHome, goReview, config } = useApp()
  const sse = useSSE()
  const timeoutRef = useRef(null)

  // Start when files arrive
  useEffect(() => {
    if (initialFiles?.length) {
      sse.start(initialFiles, config.apiBase)
    }
  }, [])

  // Safety: if no files and no SSE activity after 800ms, dead-end redirect
  useEffect(() => {
    if (initialFiles === null || initialFiles === undefined) {
      timeoutRef.current = setTimeout(() => goHome(), 800)
    }
    return () => { if (timeoutRef.current) clearTimeout(timeoutRef.current) }
  }, [])

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
      setTimeout(() => {
        goReview({
          questions: sse.result.questions || [],
          exam_id: sse.result.exam_id || '',
          exam_type: sse.result.exam_type || '',
          variant: sse.result.variant || '',
          passage: sse.result.passage || '',
          s1_questions: sse.result.s1_questions || [],
          warnings: sse.result.warnings || [],
        })
      }, 400)
    }
  }, [sse.result, sse.stage, goReview])

  const stepIdx = sse.stage === 'uploading' ? 0 : sse.stage === 'ocr' ? 1 : sse.stage === 'stage1' ? 2 : sse.stage === 'stage2' ? 3 : sse.stage === 'done' ? 4 : 0
  const pct = sse.stage === 'done' ? 100 : stepIdx === 3 ? 75 : stepIdx * 25 + 10
  const hasError = sse.stage === 'error'

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
          <div className="text-lg text-exam-error font-semibold mb-2">❌ 出错了</div>
          <div className="text-sm text-exam-text-muted mb-5">{sse.error?.message}</div>
          {sse.error?.recoverable && (
            <button onClick={goHome} className="bg-exam-accent text-white px-7 py-2.5 rounded-full text-sm font-semibold active:scale-95 transition-transform">
              返回重试
            </button>
          )}
        </div>
      ) : (
        <>
          <div className="text-base text-white font-semibold tracking-tight">{sse.statusText || '正在准备…'}</div>
          <div className="text-sm text-exam-text-muted">{sse.detail}</div>
          <div className="text-xs text-exam-text-muted opacity-40">通常在 15-30 秒内完成</div>
          {['uploading','ocr','stage1','stage2'].includes(sse.stage) && (
            <button onClick={() => { sse.cancel(); goHome() }} className="mt-2 text-xs text-exam-text-muted border border-exam-border px-6 py-1.5 rounded-full hover:text-exam-error hover:border-exam-error transition-colors">
              取消
            </button>
          )}
        </>
      )}
    </div>
  )
}
