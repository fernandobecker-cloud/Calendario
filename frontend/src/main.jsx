import React from 'react'
import ReactDOM from 'react-dom/client'
import AppRouter from './AppRouter'
import FilasPage from './components/FilasPage'
import './index.css'

// /filas/<chave>: painel das filas por link, sem login (para os gerentes).
const filas = window.location.pathname.match(/^\/filas\/([^/]+)\/?$/)

ReactDOM.createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    {filas ? <FilasPage chave={decodeURIComponent(filas[1])} /> : <AppRouter />}
  </React.StrictMode>
)
