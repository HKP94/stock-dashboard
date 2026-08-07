# 정리 라운드 S1 — 트랙 재고조사

- **작성**: 2026-08-08 · Claude Code · base main `61fcb96`
- **상태**: 브랜치 삭제는 **PM 승인 대기**(이 문서는 근거 제출)

---

## 1. 원격 브랜치 분류 (46개 = main + 45개)

### 1-1. 판정 방법 (기계적, 추정 금지)

4단계로 좁혔다. 각 단계의 **한계도 함께 적는다** — 어디까지가 결정적이고 어디부터가 판단인지 구분하기 위해서다.

| 단계 | 방법 | 결정력 |
|---|---|---|
| ① 조상 검사 | `git merge-base --is-ancestor branch main` | **결정적** — 참이면 완전 머지 |
| ② 머지 no-op | `git merge-tree --write-tree main branch` 결과 트리 == main 트리 | **결정적** — 브랜치가 main에 더할 게 없음 |
| ③ 패치 역적용 | `git diff mb..branch \| git apply -R --check` | **한계 있음** — main이 그 파일을 이후 수정하면 문맥 불일치로 실패. 실패가 미머지 증거는 **아니다** |
| ④ 신규 파일 존재 | 브랜치가 추가한 파일이 `main`에 있는가 | **강한 증거** — 없으면 그 작업은 랜딩 안 됨 |

③이 squash 워크플로에서 대량 실패하는 것(24건)은 **정상**이다. squash는 원본 커밋을 main에 남기지 않고, `CLAUDE.md`·`PRD.md`는 모든 PR이 append하므로 항상 상이하다. 그래서 ③ 실패분은 ④로 재판정했다.

### 1-2. 결과

| 판정 | 수 | 근거 |
|---|---|---|
| **삭제 가능** | **43** | ①·② 결정적 통과, 또는 ④에서 신규 파일 전부 main 존재 |
| **★생존(보존)** | **2** | ④에서 main에 없는 산출물 확인 |
| 판단 필요 | 0 | — |

### 1-3. ★생존 2건 (삭제 금지)

**`feat/kb-portfolio-sync`** (9c1866e)
- `src/collect_kb_portfolio.py`·`tests/test_kb_portfolio.py`가 **main에 없다**.
- KB 계좌 연결 보류로 대기 중(PM 지시: 절대 삭제 금지).
- base가 main보다 **5커밋 뒤처짐** — 재개 시 rebase + `kb_client.py` 중복 해소 필요.

**`feat/backfill-prices`** (894dd22) ← **재고조사에서 새로 드러난 건**
- `src/backfill.py`(기능)는 main에 랜딩됐다.
- 그런데 **`tests/test_backfill.py`의 테스트 12개 중 11개가 main 어디에도 없다**:
  `test_routes_kr_and_us`, `test_failure_isolated`, `test_market_kr/us`,
  `test_suffix_fallback_ks/us`, `test_market_overrides_suffix`,
  `test_computes_and_upserts`, `test_empty_rows_not_upserted`,
  `test_one_ticker_failure_isolated`, `test_sleep_called_per_ticker`
- 즉 **기능만 머지되고 테스트는 유실된 브랜치**다. 백필의 KR/US 라우팅·종목 단위 격리·
  접미사 폴백이 현재 **무방비**다.
- **제안**: 삭제하지 말고 테스트를 살려오는 별도 소PR 후 삭제. (이 라운드는 문서 중심이므로
  코드 착수는 PM 판단.)

### 1-4. 삭제 대상 43개

<details><summary>전체 목록</summary>

`claude/access-github-stock-analysis-22xYb`(레거시 `main.py`의 폐기된 DDGS 경로 수정 — 현행 미사용),
`claude/improve-stock-news-fetching-zdoxQ`, `codex/wave1-t1-portfolio-total`(추가 8파일 전부 main 존재),
`codex/wave5a-action-advice`, `docs/data-reliability-diag-findings`,
`docs/legacy-ticker-correction-design`, `docs/newf-signal-accuracy-tracking-design`, `docs/sync-v1.1`,
`feat/discovery-screen`, `feat/dual-score`, `feat/freshness-monitor`, `feat/judgment-notes`,
`feat/kb-supply-integration`, `feat/kb-supply-pilot`, `feat/local-refresh-automation`,
`feat/r7-earnings-calendar`, `feat/sector-relative`, `feat/shareholder-yield`,
`feat/strategy-tab-regime`, `feat/valuation-xcheck`, `fix/assemble-bulk-query`,
`fix/db-individual-params`, `fix/factor-winsorize`, `fix/financial-quality`, `fix/fnguide-kr-roe`,
`fix/gemini-free-tier-models`, `fix/installer-shell-portability`, `fix/krx-secrets-wiring`,
`fix/legacy-ticker-rename`, `fix/persist-indicators-quant`, `fix/portfolio-value`,
`fix/r4-kosdaq-r6-fx`, `fix/signal-track-index-daily-cols`, `hotfix/apply-migrations-syspath`,
`hotfix/gemini-cost-flash-circuit`, `phase1/data-backbone-scaffold`, `phase1/ingest-modules`,
`phase1/news-market`, `phase2/compute-quant`, `phase2/enrich-gemini`, `phase2/rules-engine`,
`phase3/assemble`, `phase3/pipeline-actions`

</details>

**정정**: 직전 보고에서 "미머지 81개"라 했으나 그건 `--prune` 전 **로컬 추적 잔여물**이 섞인 수치였다(원격에 이미 없는 브랜치). 실제 원격은 46개다.

---

## 2. 백로그 전수 재고 (실DB 검증)

### 2-1. 종결 처리 대상 (해결 확인)

| 항목 | 검증 | 판정 |
|---|---|---|
| `atr14` 전량 NULL | 최근 7일 318행 중 **non-null 318** | ✅ 종결 |
| `composite` NULL 20종목 | 최신 asof **NULL 0건** | ✅ 종결 |
| `index_daily` 정지(6월 중순) | `^KS11` 최신 **2026-08-06** | ✅ 종결 |
| investor_flow 수집 정지 | 최신 **2026-08-07** | ✅ 종결 |
| 140610 유니버스 제외 | `active=false`, 데이터 512행 보존 | ✅ 종결 |
| 레거시 티커 정정 | 6건 rename 완료(s1) | ✅ 종결 |
| KB 수급 통합 | auto 폴백 머지(04dc5d8) | ✅ 종결 |

### 2-2. 살아 있는 백로그 (유지)

| 항목 | 현황 | 비고 |
|---|---|---|
| **`signal_grade_track.hit_excess` 부분 결측** | 5,715행 중 non-null **404행(7%)** | 과거분은 `index_daily` 스테일 시기라 구조적 결측. 신규분은 채워지는지 추적 필요 |
| **[근본] 로컬 직접 KR 종가 수집** | CI 지연(20:17~22:04)에 22:30 export가 인질 | PM 결정 대기(아키텍처 변경). 18:30 슬롯 신설로 **수급은 해소**됐으나 **종가는 여전히 CI 의존** |
| 포트폴리오 표시 라이브계산 | 심각도 낮음(자동 보정) | 18:30/22:30 분리 후 재평가 필요 |
| SIGALRM-backoff 구조 리팩터 | flash 전환으로 위험 낮음 | 유지 |
| 배치 API·컨텍스트 캐싱 | 미검토 | 유지 |
| pro 복귀 판단 | flash 안정성 확인 후 | 유지 |
| Node.js 20 deprecation | actions 버전 bump | 유지 |
| RLS 보안 | KPH 우선순위 낮춤 | 유지 |
| **KB 12분류 상세 저장** | 파일럿에서 실충전 확인, 활용처 미정 | 유지(보류) |
| **KB 수급 소형주 반올림** | 백만원 단위 반올림(미코 2.9%) | 수급 '금액'을 직접 쓰는 로직 생기면 pykrx 고정 검토 |
| **`feat/backfill-prices` 테스트 11개 유실** | §1-3 | **신규 등록** |

### 2-3. 대기(외부 의존)

| 항목 | 막힌 지점 |
|---|---|
| R1 잔고 자동화 / R10 체결·배당 자동채점 | KB 실계좌 연결 불가(오픈베타 제약) |
| KB CI 이관 | 도달성 실증 완료·PM이 보류 결정(CI 크론 지연이 적시성 목적에 역행) |

---

## 3. PM 결정 요청

1. **브랜치 43개 일괄 삭제 승인** — 생존 2건(`feat/kb-portfolio-sync`·`feat/backfill-prices`) 보존.
2. **`feat/backfill-prices` 테스트 11개 복원**을 별도 소PR로 진행할지 — 이 라운드에 포함할지, 별건으로 둘지.
