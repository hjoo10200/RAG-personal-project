# Vector 검색 기준선 평가 보고서

평가일: 2026-08-17  
임베딩 모델: `intfloat/multilingual-e5-small`  
벡터 차원: 384  
검색 방식: PGVector cosine distance, Top 3

## DB 사전 검증

| 컬렉션 | 청크 | PDF | 최소 차원 | 최대 차원 |
|---|---:|---:|---:|---:|
| `youth_independence_guides` | 272 | 4 | 384 | 384 |
| `youth_independence_cases` | 305 | 6 | 384 | 384 |
| `youth_independence_policies` | 402 | 7 | 384 | 384 |

세 컬렉션 모두 적재 문서 수와 벡터 차원이 기대값과 일치했다.

## 자동 평가 결과

| 구분 | 질문 | 통과 | Source Hit@3 | 기대 문서 평균 회수율 | MRR |
|---|---:|---:|---:|---:|---:|
| guides | 5 | 5 | 100% | 90% | 1.0000 |
| cases | 5 | 5 | 100% | 90% | 0.9000 |
| policies | 5 | 3 | 60% | 80% | 0.8667 |
| 전체 | 15 | 13 | **86.7%** | **86.7%** | **0.9222** |

초기 목표인 `Source Hit@3 80% 이상`을 충족했다. 다만 이 질문들은 현재 문서 내용을 바탕으로 만든 기준선이므로 실제 사용자 질문보다 점수가 높게 나올 수 있다. 이후 표현이 다른 질문과 오답 유도 질문을 추가해야 한다.

## 질문별 결과

| ID | 판정 | 첫 기대 문서 순위 | 기대 문서 회수율 | Top 1 문서 |
|---|---|---:|---:|---|
| G01 | PASS | 1 | 100% | `standard_housing_lease_contract_2023.pdf` |
| G02 | PASS | 1 | 100% | `standard_housing_lease_contract_2023.pdf` |
| G03 | PASS | 1 | 100% | `easylaw_moving_guide_2026.pdf` |
| G04 | PASS | 1 | 100% | `financial_life_guide_young_adults_2026.pdf` |
| G05 | PASS | 1 | 50% | `housing_lease_protection_guide_2020.pdf` |
| C01 | PASS | 1 | 100% | `busan_youth_regional_migration_cases_2021.pdf` |
| C02 | PASS | 2 | 100% | `youth_housing_job_access_interviews_2023.pdf` |
| C03 | PASS | 1 | 50% | `youth_one_person_household_living_cost_2022.pdf` |
| C04 | PASS | 1 | 100% | `youth_housing_job_access_interviews_2023.pdf` |
| C05 | PASS | 1 | 100% | `youth_policy_access_interviews_2026.pdf` |
| P01 | FAIL | 1 | 50% | `seoul_youth_monthly_rent_faq_2026.pdf` |
| P02 | PASS | 1 | 100% | `seoul_youth_moving_brokerage_support_2026.pdf` |
| P03 | PASS | 1 | 100% | `lh_seoul_youth_purchase_rental_notice_2026_2nd.pdf` |
| P04 | FAIL | 3 | 50% | `kosaf_housing_stability_scholarship_plan_2026.pdf` |
| P05 | PASS | 1 | 100% | `kosaf_housing_stability_scholarship_plan_2026.pdf` |

## 실패 분석

### P01: 월세지원 공고문과 FAQ 동시 검색

기대 문서는 월세지원 공고문과 FAQ 두 개였지만 Top 3가 모두 FAQ에서 반환됐다. 질문의 `피부양자`, `소득`, `임차 조건` 표현이 FAQ와 강하게 일치해 동일 문서 청크가 상위 결과를 독점했다.

이는 관련 정보가 검색되지 않은 문제가 아니라 출처 다양성이 부족한 문제다. 구조화 리포트에서 자격 기준과 세부 예외를 모두 쓰려면 공고문과 FAQ를 별도 하위 질의로 검색하거나, 동일 파일의 결과 수를 제한해야 한다.

### P04: 청년수당과 희망두배 청년통장 비교

희망두배 청년통장은 3위에 검색됐지만 청년수당 공고문은 Top 3에 포함되지 않았다. 대신 주거안정장학금과 월세지원 FAQ가 검색됐다. 질문에 포함된 `지원`, `중복참여`, `조건`은 여러 정책 공고에 반복되는 표현이어서 단일 벡터 검색만으로 두 정책을 동시에 회수하기 어렵다.

정책 비교 질문은 다음처럼 분해해야 한다.

```text
하위 질의 1: 서울 청년수당 신청자격과 지원 방식
하위 질의 2: 희망두배 청년통장 신청자격과 매칭 방식
하위 질의 3: 두 사업의 중복참여 제한
```

## 현재 판단

현재 384차원 임베딩 모델은 안내서와 사례 검색의 초기 기준선으로 충분하다. 지금 단계에서 더 큰 임베딩 모델로 교체할 근거는 부족하다. 우선 해결할 문제는 차원이 아니라 복합 질문 분해와 동일 출처 편중이다.

다음 개선 우선순위는 다음과 같다.

1. 복합 정책 질문을 단일 정책 단위의 하위 질의로 분해한다.
2. 정책 검색에서 동일 PDF가 Top-K를 독점하지 않도록 출처 다양화 또는 MMR을 검토한다.
3. Vector 검색과 정책명·사업명 기반 키워드 검색을 결합한다.
4. 검색 후보를 넓힌 뒤 reranker로 최종 근거를 고른다.
5. CSV의 청크 미리보기를 읽고 근거 충분성을 0~2점으로 수동 평가한다.

## 생성 파일

- `retrieval_questions.jsonl`: 평가 질문과 기대 문서
- `retrieval_results.csv`: 질문별 Top 3 원문 결과
- `retrieval_summary.json`: 자동 집계 지표
- `retrieval_evaluation_report.md`: 결과 해석과 개선 방향
