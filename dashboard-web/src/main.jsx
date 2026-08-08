import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import './tokens.css'
import App from './App.jsx'
import StyleGuide from './StyleGuide.jsx'

// Phase 0: /styleguide 에서만 스타일가이드를 렌더한다(해시 경로도 허용 — 정적 서빙 대비).
// 그 외 경로는 기존 App 그대로 — 기존 화면 회귀 0.
// Phase 1: 기준 테마 = 다크. Phase 1 범위는 셸+색 전환이라 스위치 UI는 아직 붙이지 않는다
// (토큰은 [data-theme="light"]로 이미 준비돼 있어 스위치만 추가하면 동작한다).
document.documentElement.setAttribute('data-theme', 'dark');

const isStyleGuide =
  window.location.pathname.replace(/\/+$/, '') === '/styleguide' ||
  window.location.hash === '#/styleguide';

createRoot(document.getElementById('root')).render(
  <StrictMode>
    {isStyleGuide ? <StyleGuide /> : <App />}
  </StrictMode>,
)
