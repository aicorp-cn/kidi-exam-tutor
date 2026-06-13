import { useState, useRef, useEffect, useCallback } from 'react'

export function useSSE() {
  const [stage, setStage] = useState('idle') // idle | uploading | ocr | stage1 | stage2 | error | done | cancelled
  const [statusText, setStatusText] = useState('')
  const [detail, setDetail] = useState('')
  const [error, setError] = useState(null)
  const [result, setResult] = useState(null)
  const esRef = useRef(null)
  const abortedRef = useRef(false)

  const cancel = useCallback(() => {
    abortedRef.current = true
    if (esRef.current) {
      esRef.current.close()
      esRef.current = null
    }
    setStage('cancelled')
  }, [])

  const start = useCallback(async (files, apiBase) => {
    abortedRef.current = false
    setStage('uploading')
    setStatusText('正在上传…')
    setDetail('')
    setError(null)
    setResult(null)

    const fd = new FormData()
    files.forEach(f => fd.append('images', f))

    try {
      const r = await fetch(apiBase + '/exams', { method:'POST', body:fd })
      const body = await r.json().catch(() => ({}))
      if (body.error) { setError({ message:body.error, recoverable:true }); setStage('error'); return }
      if (!body.session_id) { setError({ message:'服务响应异常', recoverable:true }); setStage('error'); return }

      const sessionId = body.session_id
      setStage('ocr')
      setStatusText('正在识别试卷文字…')

      const es = new EventSource(apiBase + '/sse/ui?session=' + sessionId)
      esRef.current = es
      let sseErrors = 0

      es.onmessage = (e) => {
        if (abortedRef.current) return
        const d = JSON.parse(e.data)
        switch (d.stage) {
          case 'connected': break
          case 'ocr':
            if (d.status === 'start') { setStage('ocr'); setStatusText('正在识别…') }
            else if (d.status === 'done') { setStage('stage1'); setStatusText('正在分析结构…'); setDetail('识别完成，'+d.chars+'字符') }
            break
          case 'stage1':
            if (d.status === 'done') {
              setStage('stage2')
              setStatusText('正在生成精讲…')
              setDetail('共'+d.question_count+'题 · '+(d.exam_type||''))
            }
            break
          case 'stage2':
            if (d.status === 'progress') setDetail('AI 正在深度分析中…')
            else if (d.status === 'done') {
              setStage('done')
              setResult(d)
              es.close(); esRef.current = null
            }
            break
          case 'error':
            setError({ message:d.message, recoverable:d.recoverable })
            setStage('error')
            es.close(); esRef.current = null
            break
        }
      }

      es.onerror = () => {
        if (es.readyState === EventSource.CLOSED) return
        if (++sseErrors >= 3) {
          es.close(); esRef.current = null
          if (!abortedRef.current) setError({ message:'连接多次中断，请重试', recoverable:true })
          setStage('error')
        }
      }
      es.onopen = () => { sseErrors = 0 }
    } catch (err) {
      if (!abortedRef.current) setError({ message:'网络错误，请重试', recoverable:true })
      setStage('error')
    }
  }, [])

  useEffect(() => {
    return () => {
      if (esRef.current) esRef.current.close()
    }
  }, [])

  return { stage, statusText, detail, error, result, start, cancel, setError }
}
