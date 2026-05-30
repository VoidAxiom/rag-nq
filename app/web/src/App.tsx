import { Link, Route, Routes } from 'react-router'

import { HomePage } from '@/pages/HomePage'
import { AskPage } from '@/pages/AskPage'
import { ScoreboardPage } from '@/pages/ScoreboardPage'
import { ThemeProvider } from '@/theme/ThemeProvider'
import { ThemePicker } from '@/theme/ThemePicker'
import '@/theme/themes.css'

function App() {
  return (
    <ThemeProvider>
      <div className="theme-app">
        <header className="theme-page theme-page--header">
          <div className="theme-header">
            <div>
              <span className="theme-header__title">RAG · NQ Showcase</span>
            </div>
            <nav className="theme-header__nav" aria-label="Primary">
              <Link to="/">Home</Link>
              <Link to="/ask">Ask</Link>
              <Link to="/scoreboard">Scoreboard</Link>
              <ThemePicker />
            </nav>
          </div>
        </header>
        <Routes>
          <Route path="/" element={<HomePage />} />
          <Route path="/ask" element={<AskPage />} />
          <Route path="/scoreboard" element={<ScoreboardPage />} />
        </Routes>
      </div>
    </ThemeProvider>
  )
}

export default App
