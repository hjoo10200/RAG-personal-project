# RAGAS 평가 실패 기록 — 품질 평가로 사용 금지

> 이 실행은 네 지표가 모두 실패했으므로 유효한 RAGAS 평가 결과가 아닙니다. RAGAS 0.3.9가 `gpt-5.4`에 지원되지 않는 `temperature=0.3`을 전달한 것이 직접 원인이며, 예외를 숨기는 설정 때문에 아래 NaN 결과가 잘못 저장되었습니다. 수정 후 정상 검증 결과는 `evaluation/ragas/results/20260823_fix_verification/`에 있습니다.

## 실행 설정

- 평가 시각(UTC): 2026-08-22T15:10:54.283443+00:00
- 입력 파일: `D:\RAG-personal-project\evaluation\ragas\ragas_response_dataset.jsonl`
- 보고서 생성 모델: `['gpt-5.4-mini']`
- 판정 모델: `gpt-5.4`
- 임베딩 모델: `text-embedding-3-small`
- 평가 문항: 4개
- 평가 상태: `failed`
- 낮은 점수 기준: 0.7

## 지표 요약

| 지표 | 평균 | 중앙값 | 최솟값 | 최댓값 | 성공 | 실패 |
|---|---:|---:|---:|---:|---:|---:|
| answer_relevancy | - | - | - | - | 0 | 4 |
| faithfulness | - | - | - | - | 0 | 4 |
| context_recall | - | - | - | - | 0 | 4 |
| context_precision | - | - | - | - | 0 | 4 |

## 낮은 점수 및 오류 사례

| sample_id | 최저 점수 | 진단 | 평가 초점 |
|---|---:|---|---|
| scenario_employed_suwon_to_seoul | - | 평가 호출 오류 또는 결측 점수 확인 | 개인화, 실행 순서, 계약 안전, 서울 정책 근거성 |
| scenario_jobseeker_low_cash_urgent_move | - | 평가 호출 오류 또는 결측 점수 확인 | 독립 연기·조건 조정 판단, 불확실성 표현, 환각 방지 |
| scenario_graduate_student_to_seoul | - | 평가 호출 오류 또는 결측 점수 확인 | 소득 변동 반영, 대안 비교, 학생 정책 자격의 정확성 |
| scenario_incomplete_cost_inputs | - | 평가 호출 오류 또는 결측 점수 확인 | 결측 입력 처리, 숫자 환각 방지, 정책 자격 불확실성 |

## 해석 기준

- `context_recall`과 `context_precision`이 낮으면 검색 질의, 청킹, 코퍼스 구성과 RRF 결합 결과를 먼저 확인합니다.
- `answer_relevancy`와 `faithfulness`가 낮으면 생성 프롬프트, 검색 근거 사용 방식과 근거 없는 단정을 먼저 확인합니다.
- 점수가 `NaN`이면 품질 점수가 낮다는 뜻이 아니라 해당 평가 호출이 실패했다는 뜻이므로 오류와 재실행 여부를 먼저 확인합니다.
- 자동 점수는 보고서 실용성에 대한 사람 평가를 대체하지 않습니다.
