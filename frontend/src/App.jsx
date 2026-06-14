import { useApp } from './store'
import { LoginScreen } from './screens/LoginScreen'
import { HomeScreen } from './screens/HomeScreen'
import { HistoryScreen } from './screens/HistoryScreen'
import { ProcessingScreen } from './screens/ProcessingScreen'
import { ReviewScreen } from './screens/ReviewScreen'
import { ProfileScreen } from './screens/ProfileScreen'
import { TopBar } from './components/TopBar'

export function App() {
  const { screen, pendingFiles } = useApp()
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
