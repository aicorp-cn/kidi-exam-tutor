import { useApp } from './store'
import { HomeScreen } from './screens/HomeScreen'
import { HistoryScreen } from './screens/HistoryScreen'
import { ProcessingScreen } from './screens/ProcessingScreen'
import { ReviewScreen } from './screens/ReviewScreen'
import { TopBar } from './components/TopBar'

export function App() {
  const { screen, pendingFiles } = useApp()
  return (
    <div className="h-dvh flex flex-col max-w-[480px] mx-auto overflow-hidden">
      <TopBar />
      {screen === 'home' && <HomeScreen />}
      {screen === 'history' && <HistoryScreen />}
      {screen === 'processing' && <ProcessingScreen files={pendingFiles} />}
      {screen === 'review' && <ReviewScreen />}
    </div>
  )
}
