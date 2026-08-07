import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import './tokens.css'
import App from './App.jsx'
import StyleGuide from './StyleGuide.jsx'

// Phase 0: /styleguide 에서만 스타일가이드를 렌더한다(해시 경로도 허용 — 정적 서빙 대비).
// 그 외 경로는 기존 App 그대로 — 기존 화면 회귀 0.
const isStyleGuide =
  window.location.pathname.replace(/\/+$/, '') === '/styleguide' ||
  window.location.hash === '#/styleguide';

createRoot(document.getElementById('root')).render(
  <StrictMode>
    {isStyleGuide ? <StyleGuide /> : <App />}
  </StrictMode>,
)
