import React from 'react'
import ReactDOM from 'react-dom/client'
import App from './App'
import './index.css'
import './theme.css'
import { applyTheme, currentTheme } from './theme'

// Before first paint, so the page never flashes light and then correct.
applyTheme(currentTheme())

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
)