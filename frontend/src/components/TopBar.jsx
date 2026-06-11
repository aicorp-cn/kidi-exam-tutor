import { useApp } from '../store'

export function TopBar() {
  const { screen, goHome, typeLabel, variantLabel, examData } = useApp()
  const isHome = screen === 'home'
  const isReview = screen === 'review'
  const qCount = examData?.questions?.length || 0

  return (
    <div className="flex items-center justify-between px-4 min-h-[52px] shrink-0 border-b border-exam-border-light bg-exam-bg z-10">
      <span
        className={`text-sm text-exam-text-secondary cursor-pointer py-2 transition-colors hover:text-exam-text ${isHome ? 'invisible' : ''}`}
        onClick={goHome}
      >
        ← 返回
      </span>
      <span className="text-[0.95rem] font-semibold text-white tracking-tight">
        {isHome ? 'Exam Tutor' : ''}
      </span>
      {isReview && (
        <span className="text-xs text-exam-accent bg-exam-accent/8 px-3 py-1 rounded-full font-medium">
          {typeLabel}{variantLabel ? ' · ' + variantLabel : ''}{qCount ? ` · ${qCount}题` : ''}
        </span>
      )}
      {!isHome && !isReview && <span />}
    </div>
  )
}
