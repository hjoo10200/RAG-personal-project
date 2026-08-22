# RAGAS 평가 결과

## 실행 설정

- 평가 시각(UTC): 2026-08-22T15:25:17.111820+00:00
- 입력 파일: `D:\RAG-personal-project\evaluation\ragas\ragas_response_dataset.jsonl`
- 보고서 생성 모델: `['gpt-5.4-mini']`
- 판정 모델: `gpt-5.4`
- 임베딩 모델: `text-embedding-3-small`
- 평가 문항: 1개
- 평가 상태: `completed`
- 낮은 점수 기준: 0.7

## 지표 요약

| 지표 | 평균 | 중앙값 | 최솟값 | 최댓값 | 성공 | 실패 |
|---|---:|---:|---:|---:|---:|---:|
| answer_relevancy | 0.585 | 0.585 | 0.585 | 0.585 | 1 | 0 |
| faithfulness | 0.171 | 0.171 | 0.171 | 0.171 | 1 | 0 |
| context_recall | 0.000 | 0.000 | 0.000 | 0.000 | 1 | 0 |
| context_precision | 0.785 | 0.785 | 0.785 | 0.785 | 1 | 0 |

## 낮은 점수 및 오류 사례

| sample_id | 최저 점수 | 진단 | 평가 초점 |
|---|---:|---|---|
| scenario_employed_suwon_to_seoul | 0.000 | 검색과 생성 모두 점검 | 개인화, 실행 순서, 계약 안전, 서울 정책 근거성 |

## 해석 기준

- `context_recall`과 `context_precision`이 낮으면 검색 질의, 청킹, 코퍼스 구성과 RRF 결합 결과를 먼저 확인합니다.
- `answer_relevancy`와 `faithfulness`가 낮으면 생성 프롬프트, 검색 근거 사용 방식과 근거 없는 단정을 먼저 확인합니다.
- 점수가 `NaN`이면 품질 점수가 낮다는 뜻이 아니라 해당 평가 호출이 실패했다는 뜻이므로 오류와 재실행 여부를 먼저 확인합니다.
- 자동 점수는 보고서 실용성에 대한 사람 평가를 대체하지 않습니다.
