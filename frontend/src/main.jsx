import React from 'react'
import ReactDOM from 'react-dom/client'
import { App } from './App'
import { AppProvider } from './store'
import './index.css'

// PWA install prompt — capture deferred event
let deferredPrompt = null
window.addEventListener('beforeinstallprompt', (e) => {
  e.preventDefault()
  deferredPrompt = e
  // Expose for debugging: window.__pwaInstallPrompt = 'available'
  window.__pwaInstallPrompt = 'available'
  console.log('[PWA] beforeinstallprompt fired — installable')
})

// Expose manual install trigger
window.__installPWA = async () => {
  if (!deferredPrompt) {
    alert('PWA 尚未可安装。请确保已接受 HTTPS 证书，刷新页面后重试。')
    return
  }
  deferredPrompt.prompt()
  const { outcome } = await deferredPrompt.userChoice
  console.log('[PWA] Install outcome:', outcome)
  deferredPrompt = null
  window.__pwaInstallPrompt = outcome === 'accepted' ? 'installed' : 'dismissed'
}

window.addEventListener('appinstalled', () => {
  console.log('[PWA] App installed successfully')
  window.__pwaInstallPrompt = 'installed'
  deferredPrompt = null
})

// PWA Service Worker — offline caching + install prompt eligibility
if ('serviceWorker' in navigator) {
  navigator.serviceWorker.register('/sw.js', { scope: '/' })
    .then(reg => console.log('[PWA] SW registered:', reg.scope))
    .catch(err => console.error('[PWA] SW registration failed:', err))
}

ReactDOM.createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <AppProvider>
      <App />
    </AppProvider>
  </React.StrictMode>
)
