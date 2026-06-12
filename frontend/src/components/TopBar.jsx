import { useApp } from '../store'

const VERSION = 'v5.4'

export function TopBar() {
  const { screen, goHome, goHistory, typeLabel, variantLabel, examData } = useApp()
  const isHome = screen === 'home'
  const isHistory = screen === 'history'
  const isReview = screen === 'review'
  const qCount = examData?.questions?.length || 0

  return (
    <div className="flex items-center justify-between px-4 min-h-[52px] shrink-0 border-b border-exam-border-light bg-exam-bg z-10">
      {/* Left */}
      <div className="flex items-center gap-1.5 min-w-0">
        {isHome ? (
          <>
            <span className="text-[0.95rem] font-bold text-white tracking-tight">Exam Tutor</span>
            <span className="text-[0.65rem] text-exam-text-muted ml-1">{VERSION}</span>
          </>
        ) : (
          <span
            className="text-sm text-exam-text-secondary cursor-pointer py-2 transition-colors hover:text-exam-text shrink-0"
            onClick={goHome}
          >
            ← 返回
          </span>
        )}
      </div>

      {/* Center title for non-home */}
      {!isHome && (
        <span className="text-[0.95rem] font-semibold text-white tracking-tight truncate mx-2">
          {isHistory && '📚 历史记录'}
        </span>
      )}

      {/* Right */}
      <div className="flex items-center gap-2 shrink-0">
        {isHome && (
          <button
            className="text-sm text-exam-text-muted hover:text-exam-text transition-colors px-1.5 py-1"
            onClick={goHistory}
            title="历史记录"
          >
            📚
          </button>
        )}
        {isReview && (
          <span className="text-xs text-exam-accent bg-exam-accent/8 px-3 py-1 rounded-full font-medium">
            {typeLabel}{variantLabel ? ' · ' + variantLabel : ''}{qCount ? ` · ${qCount}题` : ''}
          </span>
        )}
      </div>
    </div>
  )
}
