import { useState, useRef, useMemo } from 'react'
import { useApp } from '../store'
import { useTTS } from '../hooks/useTTS'

const MODULE_ORDER = {
  '上下文': ['上下文','生词洞察','选项词义','考点','解析','排除法'],
  '题干定位': ['题干定位','选项词义','考点','解析','排除法'],
  '原句/题干': ['原句/题干','原文依据','考点','解析'],
  '上下文_open': ['上下文','生词洞察','考点','解析','推断思路'],
  '题干定位_open': ['题干定位','考点','解析','推断思路'],
}
const DEFAULTS_OPEN = ['解析','上下文','题干定位','原句/题干','推断思路']

export function ReviewScreen() {
  const { goHome, examData, ttsAutoSeq, questions, variant, passageText = examData?.passage || '', s1Questions = examData?.s1_questions || [] } = useApp()
  const [current, setCurrent] = useState(0)
  const [visited, setVisited] = useState(new Set([0]))
  const [passageOpen, setPassageOpen] = useState(false)
  const [overlayOpen, setOverlayOpen] = useState(false)
  const [toast, setToast] = useState(null)
  const [openModules, setOpenModules] = useState(() => {
    const map = {}
    questions.forEach((_, i) => { map[i] = new Set(DEFAULTS_OPEN) })
    return map
  })
  const ctRef = useRef(null)
  const touchX = useRef(0)

  const tts = useTTS()

  const warnings = examData?.warnings || []

  // Show warnings as toast
  if (warnings.length && !toast) {
    setTimeout(() => setToast(warnings.join('; ')), 500)
  }

  const q = questions[current]
  if (!q) return null

  const getModuleOrder = (modules) => {
    if (variant === 'open_ended') {
      if ('上下文' in modules) return MODULE_ORDER['上下文_open']
      if ('题干定位' in modules) return MODULE_ORDER['题干定位_open']
    }
    if ('上下文' in modules) return MODULE_ORDER['上下文']
    if ('题干定位' in modules) return MODULE_ORDER['题干定位']
    if ('原句/题干' in modules) return MODULE_ORDER['原句/题干']
    return Object.keys(modules)
  }

  const moduleOrder = getModuleOrder(q.modules || {})

  const go = (i) => {
    if (i < 0 || i >= questions.length) return
    setCurrent(i)
    setVisited(prev => new Set([...prev, i]))
  }

  const toggleModule = (qIdx, name) => {
    setOpenModules(prev => {
      const next = { ...prev }
      next[qIdx] = new Set(prev[qIdx] || [])
      if (next[qIdx].has(name)) next[qIdx].delete(name)
      else next[qIdx].add(name)
      return next
    })
  }

  const speakCard = () => {
    if (tts.playing) { tts.stop(); return }
    const m = q.modules
    const texts = ttsAutoSeq.map(mod => m[mod]).filter(Boolean)
    if (texts.length) tts.speak(texts)
  }

  const speakModule = (name) => {
    const text = q.modules[name]
    if (text) tts.speak([text])
  }

  const speakPassage = () => {
    if (passageText) tts.speak([passageText])
  }

  // Touch swipe
  const onTouchStart = (e) => { touchX.current = e.touches[0].clientX }
  const onTouchEnd = (e) => {
    const dx = e.changedTouches[0].clientX - touchX.current
    if (Math.abs(dx) > 50) {
      if (dx < 0 && current < questions.length - 1) go(current + 1)
      else if (dx > 0 && current > 0) go(current - 1)
    }
  }

  // Keyboard
  const onKeyDown = (e) => {
    if (e.key === 'ArrowRight' && current < questions.length - 1) go(current + 1)
    if (e.key === 'ArrowLeft' && current > 0) go(current - 1)
    if (e.key === 'Escape') setOverlayOpen(false)
  }

  // Format module text
  const formatText = (t) => {
    return t ? t
      .replace(/<u>(.+?)<\/u>/g, '<u class="text-yellow-400 underline underline-offset-[3px]">$1</u>')
      .replace(/\*\*(.+?)\*\*/g, '<strong class="text-white font-semibold">$1</strong>')
      .replace(/\n/g, '<br>') : ''
  }

  return (
    <div className="flex-1 flex flex-col overflow-hidden" onKeyDown={onKeyDown} tabIndex={-1}>
      {/* Toast */}
      {toast && (
        <div className="fixed top-3 left-1/2 -translate-x-1/2 z-20 bg-yellow-400/10 border border-exam-warn text-exam-warn px-5 py-2.5 rounded-full text-xs font-medium max-w-[90%] truncate animate-[slideDown_0.3s_ease]">
          ⚠ {toast}
        </div>
      )}

      {/* Passage block */}
      {passageText && (
        <div className="mx-4 my-2 bg-exam-surface rounded-lg border border-exam-border-light overflow-hidden shrink-0">
          <div className="flex items-center justify-between px-3.5 py-3 cursor-pointer select-none" onClick={() => setPassageOpen(!passageOpen)}>
            <span className="text-sm text-exam-text-secondary font-medium">📄 原文</span>
            <div className="flex items-center gap-2">
              <span className="text-sm opacity-40 hover:opacity-100 transition-opacity cursor-pointer" onClick={e => { e.stopPropagation(); speakPassage() }}>🔊</span>
              <span className={`text-xs text-exam-text-muted transition-transform duration-200 ${passageOpen ? 'rotate-180' : ''}`}>▼</span>
            </div>
          </div>
          <div className={`grid transition-all duration-300 ${passageOpen ? 'grid-rows-[1fr]' : 'grid-rows-[0fr]'}`}>
            <div className="overflow-hidden">
              <div className="px-3.5 pb-3 text-sm leading-relaxed text-exam-text font-mono whitespace-pre-wrap break-words">{passageText}</div>
            </div>
          </div>
        </div>
      )}

      {/* Cards */}
      <div className="flex-1 overflow-hidden relative">
        <div
          ref={ctRef}
          className="flex h-full transition-transform duration-300 ease-out"
          style={{ transform: `translateX(-${current * 100}%)` }}
          onTouchStart={onTouchStart}
          onTouchEnd={onTouchEnd}
        >
          {questions.map((q, i) => (
            <div key={i} className="flex-[0_0_100%] h-full overflow-y-auto px-4 pb-20">
              {/* Card header */}
              <div className="flex items-baseline gap-2.5 py-4">
                <span className="text-base font-bold text-exam-accent">第 {q.number} 题</span>
                {q.answer && <span className="text-xs font-semibold text-exam-success bg-emerald-400/10 px-2.5 py-0.5 rounded-full">{q.answer}</span>}
                <span className="text-[0.68rem] text-exam-text-muted ml-auto">{variant === 'open_ended' ? '开放型' : '选择'}</span>
              </div>

              {/* Modules */}
              {moduleOrder.map(name => {
                if (!q.modules[name]) return null
                const isOpen = openModules[i]?.has(name)
                const canTTS = ttsAutoSeq.includes(name) || name === '生词洞察'
                return (
                  <div key={name} className="mb-0.5">
                    <div className="flex items-center justify-between py-3 min-h-[44px] cursor-pointer select-none" onClick={() => toggleModule(i, name)}>
                      <span className="text-sm font-semibold text-exam-accent tracking-tight">{name}</span>
                      <div className="flex items-center gap-2">
                        {canTTS && <span className="text-sm opacity-40 hover:opacity-100 transition-opacity px-1" onClick={e => { e.stopPropagation(); speakModule(name) }}>🔊</span>}
                        <span className={`text-xs text-exam-text-muted transition-transform duration-200 ${isOpen ? 'rotate-180' : ''}`}>▼</span>
                      </div>
                    </div>
                    <div className={`grid transition-all duration-300 ${isOpen ? 'grid-rows-[1fr]' : 'grid-rows-[0fr]'}`}>
                      <div className="overflow-hidden">
                        <div className={`pb-3 text-sm leading-[1.85] text-exam-text ${isOpen ? 'pl-3 border-l-2 border-exam-border' : ''}`} dangerouslySetInnerHTML={{ __html: formatText(q.modules[name]) }} />
                      </div>
                    </div>
                  </div>
                )
              })}

              {/* Source context */}
              {s1Questions[i] && (() => {
                const sq = s1Questions[i]
                const src = [sq.context_before, sq.sentence_with_blank, sq.context_after].filter(Boolean)
                if (!src.length) return null
                return (
                  <div className="bg-exam-surface rounded-lg border border-exam-border-light overflow-hidden mt-2.5 mb-1">
                    <div className="flex items-center justify-between px-3.5 py-2.5 cursor-pointer select-none">
                      <span className="text-xs text-exam-text-muted font-medium">📎 原始文本</span>
                      <span className="text-[0.65rem] text-exam-text-muted">▼</span>
                    </div>
                    <div className="grid grid-rows-[0fr] transition-all duration-300">
                      <div className="overflow-hidden">
                        <div className="px-3.5 pb-2.5 text-xs leading-relaxed text-exam-text-muted font-mono whitespace-pre-wrap break-words">{src.join('\n')}</div>
                      </div>
                    </div>
                  </div>
                )
              })()}
            </div>
          ))}
        </div>
      </div>

      {/* Bottom nav */}
      <div className="flex items-center justify-center py-2.5 px-4 gap-3 border-t border-exam-border-light bg-exam-bg shrink-0 pb-[calc(0.625rem+env(safe-area-inset-bottom,16px))]">
        <button className="text-exam-accent text-sm font-medium px-3 py-2.5 rounded-lg active:bg-indigo-400/8 transition-colors disabled:text-exam-border disabled:cursor-default" disabled={current === 0} onClick={() => go(current - 1)}>←</button>
        <div className="flex gap-1.5 items-center overflow-x-auto max-w-[120px] px-1">
          {questions.map((_, i) => {
            let cls = 'w-1.5 h-1.5 rounded-full bg-exam-border shrink-0 cursor-pointer transition-all duration-300'
            if (i === current) cls = 'w-5 h-1.5 rounded-full bg-exam-accent shrink-0 cursor-pointer'
            else if (visited.has(i)) cls = 'w-1.5 h-1.5 rounded-full bg-exam-accent/40 shrink-0 cursor-pointer'
            return <span key={i} className={cls} onClick={() => go(i)} />
          })}
        </div>
        <button className="text-exam-accent text-sm font-medium px-3 py-2.5 rounded-lg active:bg-indigo-400/8 transition-colors disabled:text-exam-border disabled:cursor-default" disabled={current >= questions.length - 1} onClick={() => go(current + 1)}>→</button>
        <button className="text-exam-text-muted text-sm font-medium px-2 py-1" onClick={() => setOverlayOpen(true)}>
          第 <span className="text-exam-accent font-bold">{q.number}</span>/{questions.length}
        </button>
        <button
          className={`text-sm font-semibold px-5 py-2 rounded-full transition-all active:scale-95 ${
            tts.playing ? 'bg-purple-500 text-white shadow-purple-500/20' : 'bg-exam-accent text-white shadow-indigo-400/20'
          }`}
          onClick={speakCard}
        >
          {tts.playing ? '⏹ 停止' : '▶ 朗读'}
        </button>
      </div>

      {/* Overlay */}
      {overlayOpen && (
        <div className="fixed inset-0 bg-black/70 backdrop-blur-sm z-20 flex items-end justify-center" onClick={e => { if (e.target === e.currentTarget) setOverlayOpen(false) }}>
          <div className="w-full max-w-[480px] max-h-[70vh] bg-exam-surface rounded-t-2xl p-5 pb-[calc(1.25rem+env(safe-area-inset-bottom,16px))] overflow-y-auto animate-[slideUp_0.25s_ease]">
            <h3 className="text-sm font-semibold text-white mb-4">📋 题目列表</h3>
            {questions.map((q, i) => (
              <div key={i} className={`flex items-center gap-2.5 py-3 px-2.5 rounded-lg cursor-pointer transition-colors active:bg-exam-surface-hover ${i === current ? 'bg-indigo-400/8' : ''}`}
                onClick={() => { go(i); setOverlayOpen(false) }}>
                <span className="text-xs text-exam-text-muted font-semibold min-w-[20px]">{q.number}.</span>
                <span className="flex-1 text-sm text-exam-text leading-snug truncate">
                  {((q.modules['解析'] || q.modules['上下文'] || '').split('\n')[0] || '').replace(/\*\*/g, '').substring(0, 35)}
                </span>
                <span className={`text-xs ${visited.has(i) ? 'text-exam-success' : 'text-exam-text-muted'}`}>{visited.has(i) ? '✓' : ''}</span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
