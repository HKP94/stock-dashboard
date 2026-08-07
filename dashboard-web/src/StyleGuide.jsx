// ATLAS 스타일가이드 — UI 리디자인 Phase 0 검수 화면
// 토큰만 렌더한다. 기존 탭·데이터·계산과 완전히 분리돼 있어 회귀 위험이 없다.
import { useEffect, useState } from 'react';

const BG = ['--bg-app', '--bg-card', '--bg-input', '--bg-elevated'];
const BORDER = ['--border', '--border-strong'];
const TEXT = ['--text-1', '--text-2', '--text-3'];
const PRICE = ['--price-up', '--price-down', '--price-flat'];
const STATE = ['--state-positive', '--state-warn', '--state-negative', '--state-neutral'];
const ACCENT = ['--accent', '--accent-hover', '--accent-tint', '--accent-ring'];
const TYPE = [
  ['--fs-display', '지수·총자산 대형 숫자', '8,268,126'],
  ['--fs-h1', '화면 제목', '포트폴리오'],
  ['--fs-h2', '패널 제목', '보유 종목'],
  ['--fs-h3', '카드 제목', '삼성전자'],
  ['--fs-body', '본문', '외국인 3거래일 순매수 합계가 플러스로 전환됐다.'],
  ['--fs-sm', '보조', '2026-08-08 기준'],
  ['--fs-caption', '캡션', 'KR 종가 기준 (22:30 갱신)'],
  ['--fs-micro', '라벨(MonoCaps)', 'SMA 200'],
];
const SPACE = ['--sp-1', '--sp-2', '--sp-3', '--sp-4', '--sp-5', '--sp-6', '--sp-8', '--sp-10'];
const RADIUS = ['--radius-sm', '--radius-md', '--radius-lg', '--radius-pill'];

function useVar(name) {
  const [v, setV] = useState('');
  useEffect(() => {
    const read = () => setV(getComputedStyle(document.documentElement).getPropertyValue(name).trim());
    read();
    const mo = new MutationObserver(read);
    mo.observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] });
    return () => mo.disconnect();
  }, [name]);
  return v;
}

function Swatch({ name, showBorder }) {
  const value = useVar(name);
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--sp-3)' }}>
      <div style={{
        width: 52, height: 52, borderRadius: 'var(--radius-sm)', background: `var(${name})`,
        border: showBorder ? '1px solid var(--border-strong)' : '1px solid var(--border)', flexShrink: 0,
      }} />
      <div style={{ minWidth: 0 }}>
        <div className="mono" style={{ fontSize: 'var(--fs-caption)', color: 'var(--text-1)' }}>{name}</div>
        <div className="mono tnum" style={{ fontSize: 'var(--fs-micro)', color: 'var(--text-3)' }}>{value || '—'}</div>
      </div>
    </div>
  );
}

function Section({ title, note, children }) {
  return (
    <section style={{
      background: 'var(--bg-card)', border: '1px solid var(--border)',
      borderRadius: 'var(--radius-md)', boxShadow: 'var(--shadow-sm)',
      padding: 'var(--card-pad)', marginBottom: 'var(--sp-5)',
    }}>
      <h2 style={{
        margin: 0, fontSize: 'var(--fs-h2)', fontWeight: 'var(--fw-bold)',
        color: 'var(--text-1)', letterSpacing: '-0.01em',
      }}>{title}</h2>
      {note && <p style={{ margin: 'var(--sp-2) 0 0', fontSize: 'var(--fs-sm)', color: 'var(--text-2)', lineHeight: 'var(--lh-normal)' }}>{note}</p>}
      <div style={{ marginTop: 'var(--sp-4)' }}>{children}</div>
    </section>
  );
}

const grid = (min) => ({ display: 'grid', gridTemplateColumns: `repeat(auto-fill, minmax(${min}px, 1fr))`, gap: 'var(--sp-4)' });

function PriceSample({ label, value, dir }) {
  const color = dir === 'up' ? 'var(--price-up)' : dir === 'down' ? 'var(--price-down)' : 'var(--price-flat)';
  const bg = dir === 'up' ? 'var(--price-up-bg)' : dir === 'down' ? 'var(--price-down-bg)' : 'transparent';
  const mark = dir === 'up' ? '▲' : dir === 'down' ? '▼' : '·';
  return (
    <div style={{ background: bg, borderRadius: 'var(--radius-sm)', padding: 'var(--sp-3)' }}>
      <div style={{ fontSize: 'var(--fs-caption)', color: 'var(--text-3)' }}>{label}</div>
      <div className="tnum" style={{ fontSize: 'var(--fs-h1)', fontWeight: 'var(--fw-black)', color, marginTop: 2 }}>
        {mark} {value}
      </div>
    </div>
  );
}

export default function StyleGuide() {
  const [theme, setTheme] = useState('dark');
  useEffect(() => {
    document.documentElement.setAttribute('data-theme', theme);
    document.body.style.background = 'var(--bg-app)';
    return () => { document.documentElement.removeAttribute('data-theme'); document.body.style.background = ''; };
  }, [theme]);

  return (
    <div style={{
      minHeight: '100vh', background: 'var(--bg-app)', color: 'var(--text-1)',
      fontFamily: 'var(--font-sans)', padding: 'var(--sp-6)',
    }}>
      <div style={{ maxWidth: 1180, margin: '0 auto' }}>
        <header style={{ display: 'flex', alignItems: 'baseline', justifyContent: 'space-between', gap: 'var(--sp-4)', marginBottom: 'var(--sp-5)', flexWrap: 'wrap' }}>
          <div>
            <h1 style={{ margin: 0, fontSize: 'var(--fs-h1)', fontWeight: 'var(--fw-black)', letterSpacing: '-0.02em' }}>
              ATLAS 디자인 토큰
            </h1>
            <p style={{ margin: '6px 0 0', fontSize: 'var(--fs-sm)', color: 'var(--text-2)' }}>
              Phase 0 — 정의만. 기존 화면은 아직 이 토큰을 쓰지 않는다(회귀 0).
            </p>
          </div>
          <button
            onClick={() => setTheme(t => (t === 'dark' ? 'light' : 'dark'))}
            style={{
              background: 'var(--bg-input)', color: 'var(--text-1)', border: '1px solid var(--border-strong)',
              borderRadius: 'var(--radius-pill)', padding: 'var(--sp-2) var(--sp-4)',
              fontSize: 'var(--fs-sm)', fontWeight: 'var(--fw-medium)', cursor: 'pointer',
            }}>
            {theme === 'dark' ? '☾ 다크 (기준)' : '☀ 라이트'} · 전환
          </button>
        </header>

        <Section title="등락색 — 한국 관례 (상승 = 빨강 / 하락 = 파랑)"
          note="⚠️ 현행 화면은 정반대다(상승=녹색 #15803D · 하락=빨강 #B91C1C, 미국 관례). Phase 0은 토큰 정의까지이며 실제 전환은 Phase 1에서 일괄 수행한다 — 화면마다 색 의미가 다르면 오독 사고가 나므로 부분 적용하지 않는다.">
          <div style={grid(190)}>
            <PriceSample label="상승" value="+2.34%" dir="up" />
            <PriceSample label="하락" value="-1.08%" dir="down" />
            <PriceSample label="보합" value="0.00%" dir="flat" />
          </div>
          <div style={{ ...grid(200), marginTop: 'var(--sp-4)' }}>
            {PRICE.map(n => <Swatch key={n} name={n} />)}
          </div>
        </Section>

        <Section title="상태색 — 등락과 분리된 축"
          note="현행은 C.ok/C.bad 두 색이 '등락'과 '심리·신호'를 겸했다(실측: 등락 19줄 + 상태 12줄). 등락을 한국 관례로 바꾸면 '긍정 심리'까지 빨강이 되므로 축을 갈랐다. Phase 1 전환은 각 사용처를 두 축 중 하나로 분류하는 작업이다.">
          <div style={grid(200)}>{STATE.map(n => <Swatch key={n} name={n} />)}</div>
          <div style={{ display: 'flex', gap: 'var(--sp-2)', marginTop: 'var(--sp-4)', flexWrap: 'wrap' }}>
            {[['긍정', '--state-positive'], ['관망', '--state-warn'], ['부정', '--state-negative'], ['중립', '--state-neutral']].map(([t, v]) => (
              <span key={t} style={{
                fontSize: 'var(--fs-caption)', fontWeight: 'var(--fw-bold)', color: `var(${v})`,
                background: v === '--state-neutral' ? 'var(--bg-input)' : `var(${v}-bg)`,
                padding: '4px 10px', borderRadius: 'var(--radius-pill)',
              }}>{t}</span>
            ))}
          </div>
        </Section>

        <Section title="배경 3단 · 보더 · 액센트">
          <div style={grid(200)}>
            {BG.map(n => <Swatch key={n} name={n} showBorder />)}
            {BORDER.map(n => <Swatch key={n} name={n} />)}
            {ACCENT.map(n => <Swatch key={n} name={n} />)}
          </div>
        </Section>

        <Section title="텍스트 3단">
          <div style={grid(200)}>{TEXT.map(n => <Swatch key={n} name={n} />)}</div>
          <div style={{ marginTop: 'var(--sp-4)' }}>
            {TEXT.map(n => (
              <p key={n} style={{ margin: '0 0 6px', color: `var(${n})`, fontSize: 'var(--fs-body)' }}>
                <span className="mono" style={{ fontSize: 'var(--fs-micro)' }}>{n}</span> — 외국인 순매수가 3거래일 연속 유입됐다.
              </p>
            ))}
          </div>
        </Section>

        <Section title="타이포 스케일" note="숫자는 tabular-nums 고정 — 표·시계열에서 자릿수가 흔들리지 않게.">
          {TYPE.map(([v, role, sample]) => (
            <div key={v} style={{ display: 'flex', alignItems: 'baseline', gap: 'var(--sp-4)', padding: 'var(--sp-2) 0', borderBottom: '1px solid var(--border)' }}>
              <span className="mono" style={{ fontSize: 'var(--fs-micro)', color: 'var(--text-3)', width: 108, flexShrink: 0 }}>{v}</span>
              <span style={{ fontSize: 'var(--fs-micro)', color: 'var(--text-2)', width: 130, flexShrink: 0 }}>{role}</span>
              <span className="tnum" style={{ fontSize: `var(${v})`, color: 'var(--text-1)', fontWeight: v === '--fs-display' ? 'var(--fw-black)' : 'var(--fw-medium)' }}>{sample}</span>
            </div>
          ))}
        </Section>

        <Section title="간격 (4px 배수) · 라운드">
          <div style={{ display: 'flex', gap: 'var(--sp-4)', flexWrap: 'wrap', alignItems: 'flex-end' }}>
            {SPACE.map(n => (
              <div key={n} style={{ textAlign: 'center' }}>
                <div style={{ width: `var(${n})`, height: 40, background: 'var(--accent)', borderRadius: 2, margin: '0 auto' }} />
                <div className="mono" style={{ fontSize: 'var(--fs-micro)', color: 'var(--text-3)', marginTop: 6 }}>{n.replace('--sp-', '')}</div>
              </div>
            ))}
          </div>
          <div style={{ display: 'flex', gap: 'var(--sp-4)', marginTop: 'var(--sp-5)', flexWrap: 'wrap' }}>
            {RADIUS.map(n => (
              <div key={n} style={{ textAlign: 'center' }}>
                <div style={{ width: 72, height: 52, background: 'var(--bg-input)', border: '1px solid var(--border-strong)', borderRadius: `var(${n})` }} />
                <div className="mono" style={{ fontSize: 'var(--fs-micro)', color: 'var(--text-3)', marginTop: 6 }}>{n.replace('--radius-', '')}</div>
              </div>
            ))}
          </div>
        </Section>

        <Section title="카드 규격" note="--card-pad(16/20) 본문 · --card-pad-tight(12/16) 밀집 목록 · --radius-md 기본.">
          <div style={grid(300)}>
            <div style={{ background: 'var(--bg-card)', border: '1px solid var(--border)', borderRadius: 'var(--radius-md)', boxShadow: 'var(--shadow-sm)', overflow: 'hidden' }}>
              <div style={{ padding: 'var(--card-head-pad)', borderBottom: '1px solid var(--border)' }}>
                <div className="mono" style={{ fontSize: 'var(--fs-micro)', color: 'var(--text-3)', letterSpacing: '0.06em' }}>보유 종목</div>
              </div>
              <div style={{ padding: 'var(--card-pad)' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline' }}>
                  <span style={{ fontSize: 'var(--fs-h3)', fontWeight: 'var(--fw-bold)' }}>삼성전자</span>
                  <span className="tnum" style={{ fontSize: 'var(--fs-h3)', fontWeight: 'var(--fw-bold)', color: 'var(--price-up)' }}>₩230,500</span>
                </div>
                <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: 'var(--sp-2)', fontSize: 'var(--fs-sm)', color: 'var(--text-2)' }}>
                  <span>6주 · 평단 ₩246,792</span>
                  <span className="tnum" style={{ color: 'var(--price-down)' }}>▼ 6.49%</span>
                </div>
              </div>
            </div>
            <div style={{ background: 'var(--bg-card)', border: '1px solid var(--border)', borderRadius: 'var(--radius-lg)', boxShadow: 'var(--shadow-md)', padding: 'var(--card-pad)' }}>
              <div className="mono" style={{ fontSize: 'var(--fs-micro)', color: 'var(--text-3)', letterSpacing: '0.06em' }}>총자산</div>
              <div className="tnum" style={{ fontSize: 'var(--fs-display)', fontWeight: 'var(--fw-black)', letterSpacing: '-0.02em', marginTop: 4 }}>₩8,768,126</div>
              <div style={{ fontSize: 'var(--fs-caption)', color: 'var(--text-3)', marginTop: 'var(--sp-1)' }}>KR 종가 기준 (22:30 갱신)</div>
            </div>
          </div>
        </Section>

        <p style={{ fontSize: 'var(--fs-caption)', color: 'var(--text-3)', textAlign: 'center', marginTop: 'var(--sp-8)' }}>
          토큰 정의: <span className="mono">dashboard-web/src/tokens.css</span> · 근거·전환계획: <span className="mono">docs/design/ui-tokens.md</span>
        </p>
      </div>
    </div>
  );
}
