import { useState, useEffect, useCallback, useRef } from 'react'
import { useApp } from '../store'

export function HistoryScreen() {
  const { config, loadReviewFromHistory, TYPE_LABEL, VARIANT_LABEL } = useApp()
  const [items, setItems] = useState([])
  const [search, setSearch] = useState('')
  const [typeFilter, setTypeFilter] = useState('')
  const [page, setPage] = useState(1)
  const [loading, setLoading] = useState(false)
  const [done, setDone] = useState(false)
  const [typeCounts, setTypeCounts] = useState({})
  const [totalCount, setTotalCount] = useState(null)
  const listRef = useRef(null)
  const debounceRef = useRef(null)

  const fetchPage = useCallback(async (pg, reset, s, t) => {
    setLoading(true)
    try {
      let url = config.apiBase + '/exams?page=' + pg
      if (s) url += '&search=' + encodeURIComponent(s)
      if (t) url += '&type=' + encodeURIComponent(t)
      const r = await fetch(url)
      const data = await r.json()
      if (!data.items || data.items.length === 0) {
        setDone(true)
        if (reset) setItems([])
      } else {
        setItems(prev => reset ? data.items : [...prev, ...data.items])
        setPage(pg + 1)
        if ((pg * config.pageSize + data.items.length) >= (data.total || 0)) setDone(true)
      }
      setTotalCount(data.total ?? (reset ? 0 : totalCount))
      if (data.types) setTypeCounts(data.types)
    } catch { setDone(true) }
    setLoading(false)
  }, [config])

  // Reset on search/filter change (debounced for search)
  useEffect(() => {
    if (debounceRef.current) clearTimeout(debounceRef.current)
    debounceRef.current = setTimeout(() => {
      setItems([])
      setPage(1)
      setDone(false)
      fetchPage(1, true, search, typeFilter)
    }, search ? 300 : 0)
    return () => { if (debounceRef.current) clearTimeout(debounceRef.current) }
  }, [search, typeFilter])

  const loadMore = () => {
    if (done || loading) return
    fetchPage(page, false, search, typeFilter)
  }

  useEffect(() => {
    const el = listRef.current
    if (!el) return
    const onScroll = () => {
      if (el.scrollHeight - el.scrollTop - el.clientHeight < 100) loadMore()
    }
    el.addEventListener('scroll', onScroll, { passive: true })
    return () => el.removeEventListener('scroll', onScroll)
  }, [page, done, loading, search, typeFilter])

  const relDate = (iso) => {
    const d = new Date(iso + 'Z'), now = new Date(), diff = now - d, DAY = 86400000
    if (diff < DAY) return '今天'
    if (diff < DAY*2) return '昨天'
    if (diff < DAY*7) return Math.floor(diff/DAY) + '天前'
    return d.toLocaleDateString('zh-CN', { month:'short', day:'numeric' })
  }

  const typeTabs = [
    { key: '', label: '全部' },
    { key: 'grammar_cloze', label: '语法选择' },
    { key: 'cloze', label: '完形填空' },
    { key: 'reading_comp', label: '阅读理解' },
    { key: 'true_false', label: '正误判断' },
  ]

  return (
    <div className="flex-1 flex flex-col overflow-hidden">
      {/* Search */}
      <div className="px-4 pt-3 pb-2 shrink-0">
        <div className="relative">
          <input
            type="text"
            placeholder="搜索试卷内容…"
            value={search}
            onChange={e => setSearch(e.target.value)}
            className="w-full bg-exam-surface border border-exam-border rounded-lg px-3.5 py-2.5 text-sm text-exam-text placeholder:text-exam-text-muted outline-none focus:border-exam-accent transition-colors"
          />
          {search && (
            <button className="absolute right-3 top-1/2 -translate-y-1/2 text-exam-text-muted text-sm" onClick={() => setSearch('')}>✕</button>
          )}
        </div>
        {/* Type filter */}
        <div className="flex gap-2 mt-2.5 overflow-x-auto pb-1 [&::-webkit-scrollbar]:hidden">
          {typeTabs.map(t => (
            <button
              key={t.key}
              className={`shrink-0 text-xs px-3 py-1.5 rounded-full font-medium transition-colors ${
                typeFilter === t.key
                  ? 'bg-exam-accent text-white'
                  : 'bg-exam-surface border border-exam-border text-exam-text-muted hover:text-exam-text'
              }`}
              onClick={() => setTypeFilter(t.key)}
            >
              {t.label}{t.key && typeCounts[t.key] ? ` ${typeCounts[t.key]}` : ''}
            </button>
          ))}
        </div>
      </div>

      {/* Summary bar */}
      <div className="px-4 py-1.5 shrink-0 text-xs text-exam-text-muted border-b border-exam-border-light/50">
        {totalCount !== null
          ? `共 ${totalCount} 条记录`
          : '加载中…'}
        {search && ` · 搜索「${search}」`}
      </div>

      {/* List */}
      <div ref={listRef} className="flex-1 overflow-y-auto px-4">
        {items.length === 0 && !loading && (
          <div className="text-center py-12">
            <div className="text-3xl mb-3 opacity-40">🔍</div>
            <p className="text-sm text-exam-text-muted">
              {search || typeFilter ? '没有匹配的记录' : '暂无批改记录'}
            </p>
          </div>
        )}
        {items.map(item => (
          <div key={item.id}
            className="bg-exam-surface rounded-lg p-3.5 mb-2 cursor-pointer border border-transparent active:border-exam-accent active:bg-exam-surface-hover transition-all"
            onClick={() => loadReviewFromHistory(item.id, config.apiBase)}
          >
            <div className="flex items-center gap-2 mb-1.5 flex-wrap">
              <span className="text-[0.7rem] text-exam-text-muted tabular-nums min-w-[30px]">{relDate(item.created_at)}</span>
              <span className="text-[0.68rem] px-2 py-0.5 rounded-full font-medium text-exam-accent bg-indigo-400/8">{TYPE_LABEL[item.exam_type] || item.exam_type}</span>
              {item.variant && item.variant !== 'multiple_choice' && <span className="text-[0.68rem] px-2 py-0.5 rounded-full font-medium text-exam-warn bg-yellow-400/8">{VARIANT_LABEL[item.variant]}</span>}
              {item.question_count > 0 && <span className="text-[0.68rem] px-2 py-0.5 rounded-full font-medium text-exam-text-secondary bg-white/5">{item.question_count}题</span>}
            </div>
            {item.passage && <div className="text-xs text-exam-text-muted truncate">{item.passage.replace(/\n/g, ' ').substring(0, 80)}</div>}
          </div>
        ))}
        {loading && (
          <div className="text-center py-4 text-exam-text-muted text-sm">加载中…</div>
        )}
        <div className="pb-6" />
      </div>
    </div>
  )
}
