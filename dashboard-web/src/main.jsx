import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import './tokens.css'
import App from './App.jsx'
import StyleGuide from './StyleGuide.jsx'

// Phase 0: /styleguide 에서만 스타일가이드를 렌더한다(해시 경로도 허용 — 정적 서빙 대비).
// 그 외 경로는 기존 App 그대로 — 기존 화면 회귀 0.
// Phase 2: ★기본 테마 = 라이트(KPH 확정). 다크는 토글 옵션으로 유지한다.
//   토큰이 두 테마를 다 정의하므로 이 속성 하나가 전 화면에 먹는다.
document.documentElement.setAttribute('data-theme', localStorage.getItem('atlas-theme') || 'light');

const isStyleGuide =
  window.location.pathname.replace(/\/+$/, '') === '/styleguide' ||
  window.location.hash === '#/styleguide';

createRoot(document.getElementById('root')).render(
  <StrictMode>
    {isStyleGuide ? <StyleGuide /> : <App />}
  </StrictMode>,
)
