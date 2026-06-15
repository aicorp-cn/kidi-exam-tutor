// Layer 2: Client-side fingerprint collection
// Canvas, WebGL, AudioContext, Screen → SHA-256 device_hash
//
// P1: exact hash matching on server
// P2: fuzzy matching (added server-side later)

async function sha256(data) {
  const buf = typeof data === 'string'
    ? new TextEncoder().encode(data)
    : data
  const hash = await crypto.subtle.digest('SHA-256', buf)
  return Array.from(new Uint8Array(hash))
    .map(b => b.toString(16).padStart(2, '0'))
    .join('')
}

/**
 * Collect browser fingerprint signals.
 * Returns { device_hash, canvas_hash, webgl_renderer, audio_hash, screen_sig }
 * or null if fingerprinting is completely unavailable.
 */
export async function generateFingerprint() {
  const signals = {}

  // ── Canvas fingerprint ──
  try {
    const canvas = document.createElement('canvas')
    canvas.width = 240
    canvas.height = 60
    const ctx = canvas.getContext('2d')
    ctx.textBaseline = 'alphabetic'
    ctx.fillStyle = '#f60'
    ctx.fillRect(100, 1, 62, 20)
    ctx.fillStyle = '#069'
    ctx.font = '11pt "Times New Roman"'
    ctx.fillText('Cwm fjordbank glyphs vext quiz', 2, 15)
    signals.canvas_hash = await sha256(canvas.toDataURL())
  } catch {
    signals.canvas_hash = 'canvas_error'
  }

  // ── WebGL Renderer ──
  try {
    const gl = document.createElement('canvas').getContext('webgl')
      || document.createElement('canvas').getContext('experimental-webgl')
    if (gl) {
      const ext = gl.getExtension('WEBGL_debug_renderer_info')
      signals.webgl_renderer = ext
        ? gl.getParameter(ext.UNMASKED_RENDERER_WEBGL)
        : 'no_debug_info'
    } else {
      signals.webgl_renderer = 'no_webgl'
    }
  } catch {
    signals.webgl_renderer = 'webgl_error'
  }

  // ── AudioContext fingerprint ──
  try {
    const AudioCtx = window.AudioContext || window.webkitAudioContext
    if (AudioCtx) {
      const ac = new AudioCtx()
      const osc = ac.createOscillator()
      const ana = ac.createAnalyser()
      osc.connect(ana)
      ana.connect(ac.destination)
      const samples = new Float32Array(ana.frequencyBinCount)
      ana.getFloatTimeDomainData(samples)
      signals.audio_hash = await sha256(samples.buffer)
      await ac.close()
    } else {
      signals.audio_hash = 'no_audio_context'
    }
  } catch {
    signals.audio_hash = 'audio_error'
  }

  // ── Screen signature ──
  try {
    signals.screen_sig = `${screen.width}x${screen.height}x${devicePixelRatio}`
  } catch {
    signals.screen_sig = 'screen_error'
  }

  // ── Composite device_hash ──
  const raw = [
    signals.canvas_hash,
    signals.webgl_renderer,
    signals.audio_hash,
    signals.screen_sig,
  ].join('|')
  signals.device_hash = await sha256(raw)

  return signals
}
