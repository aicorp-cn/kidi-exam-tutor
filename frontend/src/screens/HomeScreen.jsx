import { useState, useRef, useEffect, useCallback } from 'react'
import { useApp } from '../store'

const MAX_SIDE = 1920
const JPEG_QUALITY = 0.8
const MAX_RAW_SIZE = 50 * 1024 * 1024

export function HomeScreen() {
  const { goProcessing, config, history, setHistory, loadReviewFromHistory, TYPE_LABEL, VARIANT_LABEL } = useApp()
  const [dragOver, setDragOver] = useState(false)
  const [histLoading, setHistLoading] = useState(false)
  const camRef = useRef(null)
  const fileRef = useRef(null)

  const preprocess = async (file) => {
    if (file.size >= MAX_RAW_SIZE) throw new Error('图片过大')
    try {
      const bmp = await createImageBitmap(file)
      if (bmp.width <= MAX_SIDE && bmp.height <= MAX_SIDE) { bmp.close(); return file }
      const scale = Math.min(MAX_SIDE / Math.max(bmp.width, bmp.height), 1.0)
      const c = document.createElement('canvas')
      c.width = Math.round(bmp.width * scale)
      c.height = Math.round(bmp.height * scale)
      c.getContext('2d').drawImage(bmp, 0, 0, c.width, c.height)
      bmp.close()
      return new Promise((resolve, reject) => {
        c.toBlob(blob => {
          if (blob) { resolve(new File([blob], file.name, { type:'image/jpeg' })); return }
          reject(new Error('处理失败'))
        }, 'image/jpeg', JPEG_QUALITY)
      })
    } catch { throw new Error('格式不支持') }
  }

  const handleFiles = useCallback(async (files) => {
    if (!files.length) return
    const processed = []
    for (const f of files) {
      try { processed.push(await preprocess(f)) } catch {}
    }
    if (processed.length) goProcessing(processed)
  }, [goProcessing])

  // Load initial history only
  useEffect(() => {
    setHistLoading(true)
    fetch(config.apiBase + '/exams?page=1')
      .then(r => r.json())
      .then(({ items }) => { if (items?.length) setHistory(items) })
      .catch(() => {})
      .finally(() => setHistLoading(false))
  }, [])

  const relDate = (iso) => {
    const d = new Date(iso + 'Z'), now = new Date(), diff = now - d, DAY = 86400000
    if (diff < DAY) return '今天'
    if (diff < DAY*2) return '昨天'
    if (diff < DAY*7) return Math.floor(diff/DAY) + '天前'
    return d.toLocaleDateString('zh-CN', { month:'short', day:'numeric' })
  }

  useEffect(() => {
    const onPaste = (e) => {
      const items = e.clipboardData?.items; if (!items) return
      const fs = []
      for (const it of items) { if (it.type.startsWith('image/')) { const f = it.getAsFile(); if (f) fs.push(f) } }
      if (fs.length) { e.preventDefault(); handleFiles(fs) }
    }
    document.addEventListener('paste', onPaste)
    return () => document.removeEventListener('paste', onPaste)
  }, [handleFiles])

  return (
    <div className="flex-1 overflow-y-auto flex flex-col">
      {/* Hero */}
      <div className="text-center pt-6 pb-2 px-6 shrink-0">
        <div className="w-14 h-14 mx-auto mb-3 rounded-2xl bg-gradient-to-br from-indigo-400 to-purple-400 flex items-center justify-center text-2xl shadow-lg shadow-indigo-400/20">📝</div>
        <h1 className="text-[1.35rem] font-bold text-white tracking-tight mb-1">Exam Tutor</h1>
        <p className="text-sm text-exam-text-muted">拍照上传 · 逐题精讲 · 初中英语</p>
      </div>

      {/* Upload zone */}
      <div
        className={`mx-4 p-7 border-2 border-dashed rounded-xl text-center cursor-pointer transition-all shrink-0 bg-exam-surface ${
          dragOver ? 'border-exam-accent bg-indigo-400/5 shadow-[0_0_0_4px_var(--color-exam-accent-glow)]' : 'border-exam-border'
        }`}
        onDragOver={e => { e.preventDefault(); setDragOver(true) }}
        onDragLeave={() => setDragOver(false)}
        onDrop={e => { e.preventDefault(); setDragOver(false); handleFiles([...e.dataTransfer.files].filter(f => f.type.startsWith('image/'))) }}
        onClick={() => fileRef.current?.click()}
      >
        <span className="block text-2xl mb-2">📤</span>
        <div className="text-sm font-semibold text-white mb-1">点击上传试卷</div>
        <div className="text-xs text-exam-text-muted">JPG / PNG / WebP · 多页自动拼接 · 支持 Ctrl+V 粘贴</div>
      </div>

      {/* Buttons */}
      <div className="flex gap-3 mx-4 mt-3 shrink-0">
        <label className="flex-1 py-3.5 bg-exam-accent text-white rounded-xl text-sm font-semibold text-center cursor-pointer shadow-lg shadow-indigo-400/20 active:scale-[0.97] transition-transform" onClick={() => camRef.current?.click()}>
          <span className="block text-lg">📷</span>拍照
        </label>
        <label className="flex-1 py-3.5 bg-exam-surface border border-exam-border text-exam-text rounded-xl text-sm font-semibold text-center cursor-pointer active:bg-exam-surface-hover transition-colors" onClick={() => fileRef.current?.click()}>
          <span className="block text-lg">🖼️</span>相册
        </label>
        <input ref={camRef} type="file" accept="image/*" capture="environment" className="hidden" onChange={e => { handleFiles([...e.target.files]); e.target.value = '' }} />
        <input ref={fileRef} type="file" accept="image/*" multiple className="hidden" onChange={e => { handleFiles([...e.target.files]); e.target.value = '' }} />
      </div>

      {/* History — preview only, no pagination */}
      <div className="border-t border-exam-border-light mt-5 flex-1 min-h-0 overflow-y-auto px-4">
        <div className="sticky top-0 z-10 bg-exam-bg pt-4 pb-2 -mx-4 px-4 shadow-[0_2px_8px_rgba(9,9,11,0.95)]">
          <h3 className="text-[0.72rem] text-exam-text-muted font-medium uppercase tracking-wider">最近</h3>
        </div>
        {history.length === 0 && !histLoading && (
          <div className="text-center py-10">
            <div className="text-3xl mb-3 opacity-40">📚</div>
            <p className="text-sm text-exam-text-muted">还没有批改记录<br />上传第一张试卷开始吧</p>
          </div>
        )}
        {history.map(item => (
          <div key={item.id} className="bg-exam-surface rounded-lg p-3.5 mb-2 cursor-pointer border border-transparent active:border-exam-accent active:bg-exam-surface-hover transition-all"
            onClick={() => loadReviewFromHistory(item.id, config.apiBase)}>
            <div className="flex items-center gap-2 mb-1.5 flex-wrap">
              <span className="text-[0.7rem] text-exam-text-muted tabular-nums min-w-[30px]">{relDate(item.created_at)}</span>
              <span className="text-[0.68rem] px-2 py-0.5 rounded-full font-medium text-exam-accent bg-indigo-400/8">{TYPE_LABEL[item.exam_type] || item.exam_type}</span>
              {item.variant && item.variant !== 'multiple_choice' && <span className="text-[0.68rem] px-2 py-0.5 rounded-full font-medium text-exam-warn bg-yellow-400/8">{VARIANT_LABEL[item.variant]}</span>}
              {item.question_count > 0 && <span className="text-[0.68rem] px-2 py-0.5 rounded-full font-medium text-exam-text-secondary bg-white/5">{item.question_count}题</span>}
            </div>
            {item.passage && <div className="text-xs text-exam-text-muted truncate">{item.passage.replace(/\n/g, ' ').substring(0, 60)}</div>}
          </div>
        ))}
        <div className="pb-4" />
      </div>
    </div>
  )
}
