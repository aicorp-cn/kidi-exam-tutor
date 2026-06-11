import { useState, useRef, useCallback } from 'react'

export function useTTS() {
  const [playing, setPlaying] = useState(false)
  const queueRef = useRef([])
  const supported = typeof speechSynthesis !== 'undefined' && !!speechSynthesis

  const split = (text) => {
    const segments = []
    let i = 0
    const clean = text.replace(/<[^>]+>/g, '').replace(/❌/g, '').replace(/\*\*/g, '').trim()
    while (i < clean.length) {
      if (clean[i] === '\uff0f') {
        let j = i + 1
        while (j < clean.length && clean[j] !== '\uff0f') j++
        if (j < clean.length) { i = j + 1; continue }
        i++; continue
      }
      if (/[a-zA-Z]/.test(clean[i])) {
        let j = i
        while (j < clean.length && /[a-zA-Z]/.test(clean[j])) j++
        segments.push({ text:clean.slice(i,j), lang:'en-US' })
        i = j; continue
      }
      if (/[\u4e00-\u9fff]/.test(clean[i])) {
        let j = i
        while (j < clean.length && /[\u4e00-\u9fff]/.test(clean[j])) j++
        segments.push({ text:clean.slice(i,j), lang:'zh-CN' })
        i = j; continue
      }
      let j = i
      while (j < clean.length && !/[a-zA-Z\u4e00-\u9fff]/.test(clean[j])) j++
      const punct = clean.slice(i,j).trim()
      if (punct) segments.push({ text:punct, lang:'zh-CN' })
      i = j
    }
    return segments
  }

  const speakQueue = useCallback(() => {
    if (queueRef.current.length === 0) { setPlaying(false); return }
    setPlaying(true)
    const seg = queueRef.current.shift()
    const u = new SpeechSynthesisUtterance(seg.text)
    u.lang = seg.lang; u.rate = 0.9
    u.onend = () => speakQueue()
    u.onerror = () => speakQueue()
    speechSynthesis.speak(u)
  }, [])

  const speak = useCallback((texts) => {
    stop()
    const all = []
    for (const t of texts) {
      if (!t) continue
      all.push(...split(t))
    }
    if (all.length === 0) return
    queueRef.current = all
    speakQueue()
  }, [speakQueue])

  const stop = useCallback(() => {
    speechSynthesis.cancel()
    queueRef.current = []
    setPlaying(false)
  }, [])

  return { playing, supported, speak, stop }
}
