import { useApp } from './store'
import { LoginScreen } from './screens/LoginScreen'
import { HomeScreen } from './screens/HomeScreen'
import { HistoryScreen } from './screens/HistoryScreen'
import { ProcessingScreen } from './screens/ProcessingScreen'
import { ReviewScreen } from './screens/ReviewScreen'
import { ProfileScreen } from './screens/ProfileScreen'
import { TopBar } from './components/TopBar'

export function App() {
  const { screen, pendingFiles, authReady, PROTECTED } = useApp()

  // On refresh, protected screens must not render until auth restore completes.
  // This prevents: (a) Profile showing empty user data, (b) History flash of
  // "no records" before async fetch, (c) Review rendering without data loaded.
  // login/processing are transient — they don't need this guard.
  if (PROTECTED.has(screen) && !authReady) {
    return (
      <div className="h-dvh flex items-center justify-center">
        <div className="text-exam-text-muted text-sm">加载中…</div>
      </div>
    )
  }

  return (
    <div className="h-dvh flex flex-col max-w-[480px] mx-auto overflow-hidden">
      {screen !== 'login' && screen !== 'processing' && <TopBar />}
      {screen === 'login' && <LoginScreen />}
      {screen === 'home' && <HomeScreen />}
      {screen === 'history' && <HistoryScreen />}
      {screen === 'processing' && <ProcessingScreen files={pendingFiles} />}
      {screen === 'review' && <ReviewScreen />}
      {screen === 'profile' && <ProfileScreen />}
    </div>
  )
}
