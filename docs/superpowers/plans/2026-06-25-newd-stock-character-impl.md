# 신규-D 구현 계획 (설계 `2026-06-25-newd-stock-character-redesign.md` 승인본)

승인 + 2가지 반영(집중 관찰 톤 강화 / 보유성격 쏠림 방지 스모크)에 따른 구현 묶음.

## 묶음
1. **DDL + 스키마**: `stock_action_advice`에 `hold_character`/`hold_character_secondary`/`hold_character_basis`/`concentration_note` **ADD COLUMN**(멱등, 기존 컬럼·데이터 보존). `StockActionAdviceRow`에 동일 필드(optional). 라이브 DB에도 동일 ALTER 적용.
2. **결정론 엔진**(`stock_action_advice.py`): `derive_hold_character`(우선순위 장기→모멘텀→단기→정보부족, primary+secondary+근거), `derive_concentration_note`(트리거 `CONCENTRATION_OBSERVE_PCT`, 사실+영향 템플릿), `is_observation_clean`(금지어 가드: 줄이/축소/매도/과도/부담/적정/권장/바람직…), `finalize_concentration_note`(LLM 다듬기 가드: 금지어+수치 보존). `build_action_frame`에 편입. **비중 권고(target_weight/weight_action/direction) 계산은 그대로 유지**.
3. **LLM 서술**(`enrich_gemini`): 프롬프트에 ① 보유성격은 코드값(바꾸지 말고 설명만) ② `concentrationNote`는 **어휘만** 다듬기·구조/숫자 창작 금지·금지어 명시. 스키마에 `concentrationNote` optional 추가(파서는 model_validate라 자동 수용).
4. **저장**(`db.upsert_stock_action_advice`) + **파이프라인**(`run_pipeline`·`pipeline_synthesis`의 `_step_action_advice` 양쪽): 프레임의 새 필드 + `finalize_concentration_note` 적용해 row 구성.
5. **export**(`export_dashboard_data`): SELECT·grouping에 4필드 추가 → `actionAdviceLatest/History`에 `holdCharacter`/`holdCharacterSecondary`/`holdCharacterBasis`/`concentrationNote`.
6. **UI**(`tabsA.jsx` ActionAdviceCard): "종목 성격·액션"으로 재구성 — 보유성격 뱃지+근거 리드, 신뢰도/asof, 진입·이탈, 지지/반대+divergence, "관찰·집중 리스크" 회색 소섹션. **목표 비중·조정 방향 그리드 제거**(데이터는 DB 보존).
7. **테스트 + 스모크**: 분류 분기·우선순위·트리거·금지어 가드·finalize·비중 보존·**분포 스모크(쏠림 방지, CI-safe)**; FE 카드 가드(신규 타이틀·비중 그리드 제거). 라이브 DB 스모크는 운영 커맨드로 보고.

## 행위 보존 / 가드
- 결정론 숫자(진입구간·신뢰도·divergence·current_weight) 유지, 숫자=코드·LLM=서술, 3축 비합산.
- 비중 데이터 삭제 금지(표시만 제외), 종목별 최신 조회·§F7·시크릿 비저장.
- 집중 관찰: 결정론 템플릿 기본, LLM은 어휘만(가드 실패 시 결정론으로 폴백).

## 스모크 결과(라이브, 2026-06-25)
보유 7종목 분포: **단기 4 / 장기보유 3 / 모멘텀 0**(전부 장기보유 쏠림 아님 — 라벨 분화 확인).
효성중공업(298040.KS, 33.9%) = 단기 + 집중 관찰 노트("…변동성에 크게 기여합니다. 판단은 본인 몫") — **"줄여라" 없음**.
검토: 이 표본에서 모멘텀 미출현·단기 비중 높음(뉴스 이벤트 기반) → 임계값(MOM_FLOOR/단기 트리거) 후속 보정 후보(설계 §9).
