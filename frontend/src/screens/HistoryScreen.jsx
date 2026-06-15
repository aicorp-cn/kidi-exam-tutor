import { useState, useEffect, useCallback, useRef } from 'react'
import { useApp } from '../store'

export function HistoryScreen() {
  const { config, loadReviewFromHistory, TYPE_LABEL, VARIANT_LABEL, authToken } = useApp()
  const [items, setItems] = useState([])
  const [search, setSearch] = useState('')
  const [typeFilter, setTypeFilter] = useState('')
  const [page, setPage] = useState(1)
  const [loading, setLoading] = useState(false)
  const [done, setDone] = useState(false)
  const [typeCounts, setTypeCounts] = useState({})
  const [totalCount, setTotalCount] = useState(null)
  const [manageMode, setManageMode] = useState(false)
  const [selected, setSelected] = useState(new Set())
  const [deleteConfirm, setDeleteConfirm] = useState(false)
  const listRef = useRef(null)
  const debounceRef = useRef(null)

  const authHeaders = authToken ? { 'Authorization': 'Bearer ' + authToken } : {}

  const toggleStar = async (examId, e) => {
    e.stopPropagation()
    try {
      const r = await fetch(config.apiBase + '/exams/' + examId + '/star', { method: 'POST', headers: authHeaders })
      const d = await r.json()
      setItems(prev => prev.map(item =>
        item.id === examId ? { ...item, starred: d.starred ? 1 : 0 } : item))
    } catch {}
  }

  const fetchRef = useRef(0)
  const fetchPage = useCallback(async (pg, reset, s, t) => {
    const fid = ++fetchRef.current; setLoading(true)
    try {
      let url = config.apiBase + '/exams?page=' + pg
      if (s) url += '&search=' + encodeURIComponent(s)
      if (t) url += '&type=' + encodeURIComponent(t)
      const r = await fetch(url, { headers: authHeaders })
      const data = await r.json()
      if (fid !== fetchRef.current) return
      if (!data.items?.length) { setDone(true); if (reset) setItems([]) }
      else {
        setItems(prev => reset ? data.items : [...prev, ...data.items])
        setPage(pg + 1)
        if ((pg * config.pageSize + data.items.length) >= (data.total || 0)) setDone(true)
      }
      setTotalCount(data.total ?? (reset ? 0 : totalCount))
      if (data.types) setTypeCounts(data.types)
    } catch { setDone(true) }
    setLoading(false)
  }, [config, authToken])

  // Gate fetch on authToken — avoids 401 on mount before auth restore
  useEffect(() => {
    if (!authToken) return
    if (debounceRef.current) clearTimeout(debounceRef.current)
    debounceRef.current = setTimeout(() => { setItems([]); setPage(1); setDone(false); fetchPage(1, true, search, typeFilter) }, search ? 300 : 0)
    return () => { if (debounceRef.current) clearTimeout(debounceRef.current) }
  }, [search, typeFilter, authToken])

  const loadMore = () => { if (!done && !loading) fetchPage(page, false, search, typeFilter) }

  useEffect(() => {
    const el = listRef.current; if (!el) return
    const onScroll = () => { if (el.scrollHeight - el.scrollTop - el.clientHeight < 100) loadMore() }
    el.addEventListener('scroll', onScroll, { passive: true })
    return () => el.removeEventListener('scroll', onScroll)
  }, [page, done, loading, search, typeFilter])

  const toggleSelect = (id) => setSelected(prev => { const next = new Set(prev); next.has(id) ? next.delete(id) : next.add(id); return next })
  const batchDelete = async () => {
    const ids = [...selected]; if (!ids.length) return
    await fetch(config.apiBase + '/exams/batch-delete', {
      method: 'POST', headers: { 'Content-Type': 'application/json', ...authHeaders },
      body: JSON.stringify({ ids }),
    })
    setItems(prev => prev.filter(item => !selected.has(item.id)))
    setSelected(new Set()); setDeleteConfirm(false); setManageMode(false)
    setTotalCount(prev => prev !== null ? prev - ids.length : null)
  }

  const relDate = (iso) => {
    const d = new Date(iso + 'Z'), now = new Date(), diff = now - d, DAY = 86400000
    if (diff < DAY) return '今天'
    if (diff < DAY * 2) return '昨天'
    if (diff < DAY * 7) return Math.floor(diff / DAY) + '天前'
    return d.toLocaleDateString('zh-CN', { month: 'short', day: 'numeric' })
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
      <div className="flex items-center justify-between px-4 pt-3 pb-2 shrink-0">
        <div className="flex-1 relative mr-3">
          <input type="text" placeholder="搜索试卷内容…" value={search}
            onChange={e => setSearch(e.target.value)}
            className="w-full bg-exam-surface border border-exam-border rounded-lg px-3.5 py-2.5 text-sm text-exam-text placeholder:text-exam-text-muted outline-none focus:border-exam-accent transition-colors" />
          {search && <button className="absolute right-3 top-1/2 -translate-y-1/2 text-exam-text-muted text-sm" onClick={() => setSearch('')}>✕</button>}
        </div>
        <button onClick={() => { setManageMode(!manageMode); setSelected(new Set()); setDeleteConfirm(false) }}
          className={`shrink-0 text-xs px-3 py-2 rounded-lg font-medium transition-colors ${manageMode ? 'bg-exam-accent/15 text-exam-accent' : 'bg-exam-surface border border-exam-border text-exam-text-muted hover:text-exam-text'}`}>
          {manageMode ? '完成' : '批量删除'}</button>
      </div>
      <div className="flex gap-2 mt-0 px-4 pb-2 shrink-0 overflow-x-auto [&::-webkit-scrollbar]:hidden">
        {typeTabs.map(t => (
          <button key={t.key} className={`shrink-0 text-xs px-3 py-1.5 rounded-full font-medium transition-colors ${typeFilter === t.key ? 'bg-exam-accent text-white' : 'bg-exam-surface border border-exam-border text-exam-text-muted hover:text-exam-text'}`}
            onClick={() => setTypeFilter(t.key)}>
            {t.label}{t.key && typeCounts[t.key] ? ` ${typeCounts[t.key]}` : ''}</button>))}
      </div>
      <div className="px-4 py-1.5 shrink-0 text-xs text-exam-text-muted border-b border-exam-border-light/50">
        {totalCount !== null ? `共 ${totalCount} 条记录` : '加载中…'}
        {search && ` · 搜索「${search}」`}
        {manageMode && selected.size > 0 && ` · 已选 ${selected.size} 条`}
      </div>
      <div ref={listRef} className="flex-1 overflow-y-auto px-4">
        {items.length === 0 && !loading && (
          <div className="text-center py-12"><div className="text-3xl mb-3 opacity-40">🔍</div>
            <p className="text-sm text-exam-text-muted">{search || typeFilter ? '没有匹配的记录' : '暂无批改记录'}</p></div>)}
        {items.map(item => (
          <div key={item.id}
            className={`bg-exam-surface rounded-lg p-3.5 mb-2 border transition-all ${manageMode ? selected.has(item.id) ? 'border-exam-accent bg-indigo-400/5 cursor-pointer' : 'border-transparent cursor-pointer' : 'border-transparent cursor-pointer active:border-exam-accent active:bg-exam-surface-hover'}`}
            onClick={() => manageMode ? toggleSelect(item.id) : loadReviewFromHistory(item.id, config.apiBase)}>
            <div className="flex items-center gap-2">
              {manageMode && <div className={`w-5 h-5 rounded-md border-2 flex items-center justify-center shrink-0 transition-colors ${selected.has(item.id) ? 'bg-exam-accent border-exam-accent text-white' : 'border-exam-border'}`}>
                {selected.has(item.id) && <span className="text-xs">✓</span>}</div>}
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2 mb-1.5 flex-wrap">
                  <span className="text-[0.7rem] text-exam-text-muted tabular-nums min-w-[30px]">{relDate(item.created_at)}</span>
                  <span className="text-[0.68rem] px-2 py-0.5 rounded-full font-medium text-exam-accent bg-indigo-400/8">{TYPE_LABEL[item.exam_type] || item.exam_type}</span>
                  {item.variant && item.variant !== 'multiple_choice' && <span className="text-[0.68rem] px-2 py-0.5 rounded-full font-medium text-exam-warn bg-yellow-400/8">{VARIANT_LABEL[item.variant]}</span>}
                  {item.question_count > 0 && <span className="text-[0.68rem] px-2 py-0.5 rounded-full font-medium text-exam-text-secondary bg-white/5">{item.question_count}题</span>}
                </div>
                {item.passage && <div className="text-xs text-exam-text-muted truncate">{item.passage.replace(/\n/g, ' ').substring(0, 80)}</div>}
              </div>
              {!manageMode && <button onClick={(e) => toggleStar(item.id, e)}
                className={`shrink-0 text-lg transition-colors ${item.starred ? 'text-yellow-400' : 'text-exam-border hover:text-yellow-400/60'}`}>
                {item.starred ? '⭐' : '☆'}</button>}
            </div>
          </div>))}
        {loading && <div className="text-center py-4 text-exam-text-muted text-sm">加载中…</div>}
        <div className="pb-24" />
      </div>
      {manageMode && selected.size > 0 && (
        <div className="fixed bottom-0 left-0 right-0 max-w-[480px] mx-auto px-4 py-3 bg-exam-bg border-t border-exam-border-light">
          {deleteConfirm ? (
            <div className="text-center">
              <p className="text-sm text-exam-text-muted mb-3">将删除 <span className="text-exam-error font-semibold">{selected.size}</span> 条记录。此操作不可撤销。</p>
              <div className="flex gap-3 justify-center">
                <button onClick={() => setDeleteConfirm(false)} className="px-6 py-2 rounded-full text-sm border border-exam-border text-exam-text-muted hover:text-exam-text transition-colors">取消</button>
                <button onClick={batchDelete} className="px-6 py-2 rounded-full text-sm bg-exam-error text-white font-semibold active:scale-95 transition-transform">确认删除</button>
              </div></div>) : (
            <button onClick={() => setDeleteConfirm(true)} className="w-full py-2.5 bg-exam-error text-white rounded-full text-sm font-semibold active:scale-95 transition-transform">
              删除所选 ({selected.size})</button>)}
        </div>)}
    </div>
  )
}
