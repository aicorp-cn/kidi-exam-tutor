import { useState, useRef, useEffect } from 'react'
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

const MODULE_STYLES = {
  '上下文':    'text-sky-400 border-sky-400/30',
  '题干定位':  'text-sky-400 border-sky-400/30',
  '原句/题干': 'text-sky-400 border-sky-400/30',
  '生词洞察':  'text-teal-400 border-teal-400/30',
  '选项词义':  'text-teal-400 border-teal-400/30',
  '考点':      'text-amber-400 border-amber-400/30',
  '解析':      'text-purple-400 border-purple-400/30',
  '排除法':    'text-purple-400 border-purple-400/30',
  '推断思路':  'text-purple-400 border-purple-400/30',
  '原文依据':  'text-slate-300 border-slate-400/30',
}

// Parse vocab lines: "word ／phonetic／ meaning"
function parseVocab(text) {
  if (!text) return []
  return text.split('\n').filter(Boolean).map(line => {
    const idx = line.indexOf('／')
    if (idx === -1) return { word: line.trim(), phonetic: '', meaning: '' }
    const word = line.substring(0, idx).trim()
    const rest = line.substring(idx + 1)
    const idx2 = rest.indexOf('／')
    const phonetic = idx2 !== -1 ? rest.substring(0, idx2).trim() : ''
    const meaning = idx2 !== -1 ? rest.substring(idx2 + 1).trim() : rest.trim()
    return { word, phonetic, meaning }
  })
}

// Parse option vocab: "A. word ／phonetic／ meaning"
function parseOptionVocab(text) {
  if (!text) return []
  return text.split('\n').filter(Boolean).map(line => {
    const m = line.match(/^([A-D])\.\s+(.+)/)
    if (!m) return null
    const label = m[1]
    const rest = m[2]
    const idx = rest.indexOf('／')
    if (idx === -1) return { label, word: rest.trim(), phonetic: '', meaning: '' }
    const word = rest.substring(0, idx).trim()
    const after = rest.substring(idx + 1)
    const idx2 = after.indexOf('／')
    const phonetic = idx2 !== -1 ? after.substring(0, idx2).trim() : ''
    const meaning = idx2 !== -1 ? after.substring(idx2 + 1).trim() : after.trim()
    return { label, word, phonetic, meaning }
  }).filter(Boolean)
}

export function ReviewScreen() {
  const { goHome, examData, ttsAutoSeq, questions, variant, passageText = examData?.passage || '' } = useApp()
  const [current, setCurrent] = useState(0)
  const [visited, setVisited] = useState(new Set([0]))
  const [passageOpen, setPassageOpen] = useState(false)
  const [overlayOpen, setOverlayOpen] = useState(false)
  const [dismissBanner, setDismissBanner] = useState(false)
  const [openModules, setOpenModules] = useState(() => {
    const map = {}
    questions.forEach((_, i) => { map[i] = new Set(DEFAULTS_OPEN) })
    return map
  })

  // Re-init modules when examData restores after refresh
  useEffect(() => {
    if (questions.length > 0 && Object.keys(openModules).length === 0) {
      const map = {}
      questions.forEach((_, i) => { map[i] = new Set(DEFAULTS_OPEN) })
      setOpenModules(map)
    }
  }, [questions.length, openModules])
  const ctRef = useRef(null)
  const touchX = useRef(0)

  const tts = useTTS()
  const warnings = examData?.warnings || []

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
    tts.stop()
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
    if (!text) return
    // Vocab modules: speak only the words, not the full explanation
    if (name === '生词洞察') {
      const items = parseVocab(text)
      const words = items.map(i => i.word).filter(Boolean)
      if (words.length) { tts.speak(words); return }
    }
    if (name === '选项词义') {
      const items = parseOptionVocab(text)
      const words = items.map(i => i.word).filter(Boolean)
      if (words.length) { tts.speak(words); return }
    }
    tts.speak([text])
  }

  const speakPassage = () => {
    if (passageText) tts.speak([passageText])
  }

  const speakWord = (word) => {
    if (word) tts.speak([word])
  }

  const onTouchStart = (e) => { touchX.current = e.touches[0].clientX }
  const onTouchEnd = (e) => {
    const dx = e.changedTouches[0].clientX - touchX.current
    if (Math.abs(dx) > 50) {
      if (dx < 0 && current < questions.length - 1) go(current + 1)
      else if (dx > 0 && current > 0) go(current - 1)
    }
  }

  const onKeyDown = (e) => {
    if (e.key === 'ArrowRight' && current < questions.length - 1) go(current + 1)
    if (e.key === 'ArrowLeft' && current > 0) go(current - 1)
    if (e.key === 'Escape') setOverlayOpen(false)
  }

  const formatText = (t) => {
    return t ? t
      .replace(/<u>(.+?)<\/u>/g, '<u class="text-yellow-400 underline underline-offset-[3px]">$1</u>')
      .replace(/\*\*(.+?)\*\*/g, '<strong class="text-white font-semibold">$1</strong>')
      .replace(/\n/g, '<br>') : ''
  }

  const totalQ = questions.length
  const visitedCount = questions.filter((_, i) => visited.has(i)).length

  const questionSummary = (q) => {
    if (q.answer) return q.answer
    if (variant === 'open_ended') return '开放'
    return '—'
  }

  const typeDisplay = variant === 'open_ended' ? '开放型' : '选'

  return (
    <div className="flex-1 flex flex-col overflow-hidden" onKeyDown={onKeyDown} tabIndex={-1}>
      {/* Warning banner */}
      {warnings.length > 0 && !dismissBanner && (
        <div className="mx-4 mt-2 bg-exam-warn/10 border border-exam-warn/20 text-exam-warn px-3.5 py-2.5 rounded-lg text-xs flex items-center gap-2 shrink-0">
          <span className="shrink-0">⚠️</span>
          <span className="flex-1 leading-relaxed">{warnings[0]}</span>
          <button onClick={() => setDismissBanner(true)} className="shrink-0 text-exam-warn/60 hover:text-exam-warn text-sm leading-none px-1">✕</button>
        </div>
      )}

      {/* Passage block */}
      {passageText && (
        <div className="mx-4 mt-2.5 bg-exam-surface rounded-lg border border-exam-border-light overflow-hidden shrink-0">
          <div className="flex items-center justify-between px-3.5 py-3 cursor-pointer select-none" onClick={() => setPassageOpen(!passageOpen)}>
            <span className="text-sm text-exam-text-secondary font-medium">📄 原文</span>
            <div className="flex items-center gap-2">
              <span className="text-sm opacity-40 hover:opacity-100 transition-opacity cursor-pointer" onClick={e => { e.stopPropagation(); speakPassage() }}>🔊</span>
              <span className={`text-xs text-exam-text-muted transition-transform duration-200 ${passageOpen ? 'rotate-180' : ''}`}>▼</span>
            </div>
          </div>
          <div className={`overflow-hidden transition-all duration-300 ${passageOpen ? 'max-h-[40vh]' : 'max-h-0'}`}>
            <div className="px-3.5 pb-3 text-sm leading-relaxed text-exam-text font-mono whitespace-pre-wrap break-words overflow-y-auto max-h-[40vh]">{passageText}</div>
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
            <div key={i} className="flex-[0_0_100%] h-full overflow-y-auto overflow-x-hidden px-4 pb-14">
              {/* Card header: 第 N 题 ▶  type [answer] */}
              <div className="flex items-center gap-1.5 py-4">
                <span className="text-base font-bold text-exam-accent">第 {q.number} 题</span>
                <button
                  className={`w-6 h-6 flex items-center justify-center rounded-full text-xs transition-all ${
                    tts.playing ? 'bg-purple-500/20 text-purple-400' : 'text-exam-accent hover:bg-indigo-400/10'
                  }`}
                  onClick={speakCard}
                  aria-label={tts.playing ? '停止朗读' : '朗读'}
                >
                  {tts.playing ? '⏹' : '▶'}
                </button>
                <span className="flex-1" />
                <span className="text-[0.68rem] text-exam-text-muted">{typeDisplay}</span>
                {q.answer && <span className="text-xs font-semibold text-exam-success bg-emerald-400/10 px-2 py-0.5 rounded-full">{q.answer}</span>}
              </div>

              {moduleOrder.map(name => {
                if (!q.modules[name]) return null
                const isOpen = openModules[i]?.has(name)
                const canTTS = ttsAutoSeq.includes(name) || name === '生词洞察'
                const style = MODULE_STYLES[name] || 'text-exam-accent border-exam-accent/30'
                const isVocabModule = name === '选项词义' || name === '生词洞察'

                return (
                  <div key={name} className="mb-0.5">
                    {/* Module header */}
                    <div className="flex items-center justify-between py-3 min-h-[44px] cursor-pointer select-none" onClick={() => toggleModule(i, name)}>
                      <span className={`text-sm font-semibold tracking-tight ${style.split(' ')[0]}`}>{name}</span>
                      <div className="flex items-center gap-2">
                        {canTTS && <span className="text-sm opacity-40 hover:opacity-100 transition-opacity px-1" onClick={e => { e.stopPropagation(); speakModule(name) }}>🔊</span>}
                        <span className={`text-xs text-exam-text-muted transition-transform duration-200 ${isOpen ? 'rotate-180' : ''}`}>▼</span>
                      </div>
                    </div>

                    {/* Module body */}
                    <div className={`grid transition-all duration-300 ${isOpen ? 'grid-rows-[1fr]' : 'grid-rows-[0fr]'}`}>
                      <div className="overflow-hidden">
                        {isVocabModule ? (
                          /* Vocab: per-word rendering with individual 🔊 */
                          name === '选项词义' ? (
                            <div className={`pb-3 ${isOpen ? 'pl-3 border-l-2 ' + style.split(' ').slice(1).join(' ') : ''}`}>
                              {parseOptionVocab(q.modules[name]).map((item, idx) => (
                                <div key={idx} className="flex items-center gap-2 py-1.5 text-sm">
                                  <span className="text-exam-accent font-semibold min-w-[22px] tabular-nums">{item.label}.</span>
                                  <span className="text-white font-semibold">{item.word}</span>
                                  {item.phonetic && <span className="text-exam-text-muted/50 text-[0.65rem]">/{item.phonetic}/</span>}
                                  {item.meaning && <span className="text-exam-text-muted text-xs ml-1">{item.meaning}</span>}
                                  <button
                                    className="shrink-0 text-xs ml-auto px-1.5 py-0.5 rounded opacity-50 active:opacity-100 transition-opacity"
                                    onClick={e => { e.stopPropagation(); speakWord(item.word) }}
                                  >
                                    🔊
                                  </button>
                                </div>
                              ))}
                            </div>
                          ) : (
                            /* 生词洞察 */
                            <div className={`pb-3 ${isOpen ? 'pl-3 border-l-2 ' + style.split(' ').slice(1).join(' ') : ''}`}>
                              {parseVocab(q.modules[name]).map((item, idx) => (
                                <div key={idx} className="flex items-center gap-2 py-1.5 text-sm">
                                  <span className="text-white font-semibold">{item.word}</span>
                                  {item.phonetic && <span className="text-exam-text-muted/50 text-[0.65rem]">/{item.phonetic}/</span>}
                                  {item.meaning && <span className="text-exam-text-muted text-xs ml-1">{item.meaning}</span>}
                                  <button
                                    className="shrink-0 text-xs ml-auto px-1.5 py-0.5 rounded opacity-50 active:opacity-100 transition-opacity"
                                    onClick={e => { e.stopPropagation(); speakWord(item.word) }}
                                  >
                                    🔊
                                  </button>
                                </div>
                              ))}
                            </div>
                          )
                        ) : (
                          <div className={`pb-3 text-sm leading-[1.85] text-exam-text ${isOpen ? 'pl-3 border-l-2 ' + style.split(' ').slice(1).join(' ') : ''}`} dangerouslySetInnerHTML={{ __html: formatText(q.modules[name]) }} />
                        )}
                      </div>
                    </div>
                  </div>
                )
              })}
            </div>
          ))}
        </div>
      </div>

      {/* Bottom nav */}
      <div className="flex items-center justify-between py-2.5 px-4 border-t border-exam-border-light bg-exam-bg shrink-0 pb-[calc(0.375rem+env(safe-area-inset-bottom,16px))]">
        <div className="flex items-center gap-2">
          <button className="text-exam-accent text-lg font-medium w-10 h-10 flex items-center justify-center rounded-lg active:bg-indigo-400/8 transition-colors disabled:text-exam-border/40 disabled:cursor-default" disabled={current === 0} onClick={() => go(current - 1)}>←</button>
          <div className="flex gap-0.5 items-center max-w-[160px] overflow-x-auto px-0.5 [&::-webkit-scrollbar]:hidden">
            {questions.map((_, i) => {
              const isActive = i === current
              const isVisited = visited.has(i)
              return (
                <button
                  key={i}
                  className={`shrink-0 cursor-pointer rounded-full transition-all duration-300 ${
                    isActive
                      ? 'bg-exam-accent'
                      : isVisited ? 'bg-exam-accent/40' : 'bg-exam-border/40'
                  }`}
                  style={isActive ? { width: 12, height: 5 } : { width: 5, height: 5 }}
                  onClick={() => go(i)}
                  aria-label={`第 ${i+1} 题`}
                />
              )
            })}
          </div>
          <button className="text-exam-accent text-lg font-medium w-10 h-10 flex items-center justify-center rounded-lg active:bg-indigo-400/8 transition-colors disabled:text-exam-border/40 disabled:cursor-default" disabled={current >= questions.length - 1} onClick={() => go(current + 1)}>→</button>
        </div>

        <button className="flex items-center gap-1 text-xs text-exam-text-muted hover:text-exam-text transition-colors px-1.5 py-1" onClick={() => setOverlayOpen(true)}>
          <span className="opacity-60">📋</span>
          <span className="text-exam-accent font-bold tabular-nums">{q.number}</span>
          <span className="opacity-60">/</span>
          <span className="tabular-nums">{totalQ}</span>
          {visitedCount > 0 && (
            <span className="text-exam-success/60 ml-0.5 tabular-nums">{visitedCount}✓</span>
          )}
        </button>
      </div>

      {/* Overlay */}
      {overlayOpen && (
        <div className="fixed inset-0 bg-black/70 backdrop-blur-sm z-20 flex items-end justify-center" onClick={e => { if (e.target === e.currentTarget) setOverlayOpen(false) }}>
          <div className="w-full max-w-[480px] max-h-[70vh] bg-exam-surface rounded-t-2xl p-5 pb-[calc(1.25rem+env(safe-area-inset-bottom,16px))] overflow-y-auto animate-[slideUp_0.25s_ease]">
            <h3 className="text-sm font-semibold text-white mb-4">📋 题目列表</h3>
            {questions.map((q, i) => (
              <div key={i} className={`flex items-center gap-3 py-3 px-3 rounded-lg cursor-pointer transition-colors active:bg-exam-surface-hover ${i === current ? 'bg-indigo-400/8' : ''}`}
                onClick={() => { go(i); setOverlayOpen(false) }}>
                <span className="text-xs text-exam-text-muted font-semibold min-w-[22px] tabular-nums">{q.number}</span>
                <span className={`text-[0.65rem] font-semibold px-2 py-0.5 rounded-full shrink-0 ${
                  q.answer ? 'text-exam-success bg-emerald-400/10' :
                  variant === 'open_ended' ? 'text-exam-warn bg-yellow-400/10' :
                  'text-exam-text-muted bg-white/5'
                }`}>
                  {questionSummary(q)}
                </span>
                <span className="flex-1 text-xs text-exam-text-muted leading-snug truncate">
                  {(q.modules['解析'] || '').replace(/\*\*/g, '').replace(/\n/g, ' ').substring(0, 30)}
                </span>
                <span className={`text-xs shrink-0 ${visited.has(i) ? 'text-exam-success' : 'text-exam-text-muted/30'}`}>
                  {visited.has(i) ? '✓' : '○'}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
