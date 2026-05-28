import { Route, Routes } from 'react-router'

import { HomePage } from '@/pages/HomePage'
import { AskPage } from '@/pages/AskPage'
import { ScoreboardPage } from '@/pages/ScoreboardPage'

function App() {
  return (
    <Routes>
      <Route path="/" element={<HomePage />} />
      <Route path="/ask" element={<AskPage />} />
      <Route path="/scoreboard" element={<ScoreboardPage />} />
    </Routes>
  )
}

export default App
