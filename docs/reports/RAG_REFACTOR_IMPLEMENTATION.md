# 계산 선행·보고서와 정책 검색 분리 구현 설명서

작성일: 2026-08-31. 최신 입력 계약은 **범주 선택 + 숫자 직접 입력**입니다. 이전 실행계획의 금액 구간 셀렉트는 기존 입력 호환용으로만 남습니다.

## 1. 바뀐 흐름

기존에는 사용자 상황으로 guides·cases·policies를 함께 검색하고, 생성기 내부에서 일부 비용을 계산한 뒤 정책을 포함한 4문단 보고서를 만들었습니다. 보고서를 생성하려면 정책용 저장소도 함께 준비되어 있어야 했습니다.

개편한 보고서 실행 순서는 다음과 같습니다.

```text
혼합 입력 JSON
→ 입력 정규화
→ 공식 비용 기준 선택 + 숫자 계산
→ 초기 자금·월 수지 판단 및 검색용 힌트
→ 상황 + 판단에 따른 guides/cases 질의
→ pgvector 벡터 검색 + Elasticsearch BM25
→ Weighted RRF 순위 결합·중복 정리
→ 계산 결과 + 실제 검색 근거를 LangChain LLM에 전달
→ 존댓말 서술형 3문단 보고서(JSON)
```

정책은 별도 경로입니다.

```text
동일 입력의 지역·연령·고용·학업·주거 조건
→ policies 전용 하이브리드 검색
→ 문서별 결과 묶기
→ 공고 제목·근거 발췌·원문 링크·접수정보
```

정책 검색은 계산기나 보고서 LLM을 호출하지 않습니다. 단, 벡터 질의 임베딩에는 API 호출이 발생할 수 있습니다. 자격을 통과/탈락으로 분류하거나 현재 모집 중임을 보장하지 않습니다. 접수정보·원문 URL이 저장된 메타데이터에 없으면 미확인으로 표시합니다.

pgvector는 PostgreSQL에서 벡터를 저장하고 의미상 가까운 문서를 찾는 확장 기능입니다. Elasticsearch는 단어 기반 검색을 담당하고, BM25는 단어의 희소성·등장 빈도·문서 길이 등을 고려해 관련성을 계산합니다. RRF는 서로 다른 점수의 절댓값 대신 순위를 결합합니다. 이번 개편은 기존 검색 방식을 재사용하고 검색 대상과 입력 연결을 바꾼 것입니다.

## 2. 입력

새 예제: `examples/inputs/mixed_rag_input.json`.

```json
{
  "schema_version": "3",
  "selections": {
    "purpose": "work",
    "employment": "employed",
    "target_region": "seoul",
    "housing": "monthly",
    "income_status": "current",
    "priorities": ["commute", "safety"]
  },
  "numbers": {
    "age": 27,
    "household_size": 1,
    "available_cash_krw": 10000000,
    "monthly_income_krw": 2200000,
    "existing_fixed_cost_krw": 100000
  }
}
```

- `selections`: 목적·고용·학업·지역·시기·주거·수입 상태·주택 보유·경험·건물 유형·우선순위의 코드. 숫자 금액은 넣지 않습니다.
- `numbers`: 나이·가구원 수·보유자금·실수령 수입·별도 필수지출을 직접 적습니다. 금액 단위는 원입니다.
- 매물·견적을 이미 알면 보증금·월세·관리비·공과금·이사비·중개보수·구입비 등을 선택적으로 더 적을 수 있습니다. 상세 예산 입력은 필수가 아닙니다.
- 금액의 `null`은 미확인, `0`은 실제 없음입니다. 음수·소수·문자열·불리언은 v3 숫자 입력으로 받지 않습니다.
- 수입 `planned`는 예정이므로 확정 수입에서 제외합니다. `none`은 0원, `unknown`은 미확인입니다.
- 기존 `{"situation": ...}` 정수 입력과 v2 구간 입력도 읽을 수 있습니다. 새 페이지는 v3만 만듭니다.
- 예제 숫자는 사용법 설명용 사용자 상황이며 실제 사용자 데이터나 모델 실행 결과가 아닙니다.

## 3. 계산과 판단

자세한 자료·근거·한계는 [비용 기준 수집 및 적용](COST_REFERENCE_RESEARCH_20260831.md)에 있습니다. 비용 기준표는 이제 비어 있지 않습니다.

전국 1인가구의 과거 소비 통계로 주거·수도·광열 외 참고 생활비를 적용합니다. 사용자가 실제 생활비 합계를 입력하면 대체합니다. 지역별 현재 비용을 만들어내지는 않습니다. 2인 이상에게 1인가구 통계를 곱해서 사용하지도 않습니다.

초기 계산: 보증금 + 이사 + 중개보수 + 초기 구입비를 합산하고 보유자금에서 뺍니다. 월 계산: 월세 + 관리비 + 생활비 + 별도 필수지출 + 필요한 경우 별도 공과금을 합산하고 확정 수입에서 뺍니다. 관리비 포함 공과금은 다시 더하지 않습니다.

모르는 비용은 0으로 넣지 않습니다. `scope`는 `complete`, `partial`, `unavailable` 중 하나이며, 완전한 계산도 **입력·가정 범위에서 필요한 항목이 채워졌다는 뜻**이지 현실의 모든 비용을 보장한다는 뜻은 아닙니다.

잔액이 음수이면 부족, 비음수이면 가정 범위에서 비음수 잔액, 기존 구간 입력에서 경계가 걸치면 구간별 상이로 표시합니다. 누락 항목이 있으면 전체 계획 판단은 정보 부족입니다. 금액을 검색문에 모두 나열하지 않고 초기자금 부족·월 적자·견적 확인 등 의미 있는 검색 힌트로 바꿉니다.

보증금 상한은 준비비와 예비금이 있어야 역산합니다. 예비금을 임의로 0원으로 가정하지 않습니다. 월 주거·공과금 탐색 잔여액은 실제 월세를 몰라도 참고 생활비와 확정 수입·기존 지출로 계산할 수 있습니다. 목표 저축액을 적지 않으면 저축 전 값임을 표시합니다.

## 4. 출력과 저장

### 보고서

`report_title`, `report_body_markdown` 두 필드의 JSON입니다. 본문은 다음 세 소제목과 서술 문단으로 구성합니다.

1. 지금 독립해도 되는지.
2. 나에게 맞는 집 찾기·계약·이사 순서.
3. 내 상황에서 조심할 점.

정책 문단은 없습니다. 내부 근거 ID와 PDF 파일명은 사용자 본문에 표시하지 않지만 실제 검색 근거는 별도 JSON에 보존합니다. 생성은 기존 LangChain `ChatOpenAI` 및 프로젝트의 생성 모델 설정을 사용합니다.

### 실행 기록

테스트 페이지와 서비스의 보고서는 `storage/generated_reports/v2/<UTC시각_랜덤ID>/`에 새 디렉터리를 만듭니다. **저장 폴더의 v2는 개편 파이프라인 버전이고 입력 JSON 버전 3과 별개입니다.**

- `input.json`: 원본 입력.
- `finance.json`: 계산·판단·가정·누락·출처.
- `evidence.json`: 검색 문서·페이지·검색 방식·RRF 점수와 계산 결과.
- `report.json`: 사용자용 보고서.
- `trace.json`: 처리 단계·상태·생성용 payload·가능한 경우 초안과 검증 상태. 실패하면 예외 종류를 기록합니다.

정책 서비스는 별도의 실행 폴더에 `input.json`, `evidence.json`, `policies.json`을 저장합니다. 계산 버튼만 누르면 결과를 응답하며 별도 파일은 만들지 않습니다. 계산 CLI는 지정 파일에 저장합니다.

입력과 실행 기록에는 개인정보·금융 상황이 포함될 수 있으므로 공개 Git에 올리지 마세요. API 키는 저장하지 않습니다. 기존 산출물을 삭제하지 않았습니다.

## 5. 파일별 역할

| 파일 | 역할 |
| --- | --- |
| `src/common/selection_input.py` | 범주 코드·직접 숫자 입력, 구버전 호환 |
| `src/finance/schema.py` | 금액·계산 결과 모델 |
| `src/finance/calculator.py` | 참고 비용 로딩, 산술, 판단·검색 힌트 |
| `src/finance/brokerage.py` | 서울 일반 주택 임대차 상한 계산 |
| `knowledge_base/metadata/cost_references.json` | 공식 통계 기반 생활비 기준 |
| `knowledge_base/metadata/brokerage_reference.json` | 수집한 중개보수 요율 |
| `src/retrieval/hybrid_pipeline.py` | 지정 코퍼스만 검색하는 공통 함수, 보고서 전용 진입점 |
| `src/retrieval/rag_pipeline.py` | 의미 검색 질의 구성 |
| `src/retrieval/keyword_query_builder.py` | 구조화 입력 기반 키워드 질의 |
| `src/generation/report_schema.py` | 정규화 상황·초안·3문단 보고서 모델 |
| `src/generation/report_generator.py` | 계산과 근거를 이용한 생성, 정책 의존 제거 |
| `src/services.py` | 계산·보고서·정책의 프레임워크 독립 진입점 |
| `src/run_rag.py` | 계산 전용/검색 전용/보고서 CLI |
| `src/run_policy_search.py` | 정책 검색 CLI |
| `src/test_page.py`, `src/web/` | 로컬 테스트 서버와 폼 |

## 6. 직접 실행하는 방법

프로젝트 루트 `D:\RAG-personal-project`에서 PowerShell로 실행합니다. 아래 명령은 안내이며 작성자가 실행한 결과가 아닙니다.

### 서비스 프로토타입 실행

```powershell
.\.venv\Scripts\python.exe -m src.test_page
```

브라우저에서 `http://127.0.0.1:8765/`에 접속합니다. 사용자가 범주를 선택하고 자금 숫자를 입력한 뒤 `내 독립 계획 만들기`를 누르면 guides/cases 기반 보고서와 policies 기반 관련 정책을 함께 요청합니다. 실제 DB 검색과 LLM 호출이므로 API 사용료가 발생할 수 있습니다.

제출 후에는 회전하는 진행 원과 `보고서 문서 검색 중`, `보고서 작성 중`, `정책 문서 검색 중`, `완료/실패` 상태가 표시됩니다. 이는 브라우저에서 임의로 시간을 재는 애니메이션이 아니라 서버 작업의 실제 단계입니다. 페이지는 생성 작업 ID로 상태를 주기적으로 조회하고, 보고서와 정책을 각각 표시합니다.

### 화면만 확인하는 오프라인 모드

```powershell
.\.venv\Scripts\python.exe -m src.test_page --offline
```

오프라인 모드는 폼과 화면 확인용이며 제출 버튼이 비활성화됩니다. 실제 모드에는 DB와 Elasticsearch가 실행 중이고 기존 컬렉션/인덱스가 준비되어 있어야 합니다. `.env`의 OpenAI 설정도 필요합니다. 페이지를 여는 것만으로 보고서가 생성되지는 않습니다. 서버 종료는 `Ctrl+C`; 변경 후에는 재시작하고 페이지를 새로고침합니다.

### CLI: 계산만 저장

```powershell
.\.venv\Scripts\python.exe -m src.run_rag `
  --input examples\inputs\mixed_rag_input.json `
  --calculate-only `
  --output storage\generated_reports\mixed_finance.json
```

### CLI: 실제 보고서

```powershell
.\.venv\Scripts\python.exe -m src.run_rag `
  --input examples\inputs\mixed_rag_input.json `
  --evidence-output storage\generated_reports\mixed_evidence.json `
  --output storage\generated_reports\mixed_report.json
```

검색까지만 보려면 `--retrieve-only`를 추가합니다. CLI의 명시적 출력 경로는 **같은 파일명을 쓰면 덮어씁니다.** 서비스의 실행별 새 디렉터리 방식과 다릅니다.

### CLI: 정책만 검색

```powershell
.\.venv\Scripts\python.exe -m src.run_policy_search --input examples\inputs\mixed_rag_input.json
```

### 사용자가 원할 때 실행할 테스트

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -p test_numeric_cost_inputs.py -v
.\.venv\Scripts\python.exe -m unittest discover -s tests -p test_refactor_v2.py -v
.\.venv\Scripts\python.exe -m unittest discover -s tests -p test_report_generation.py -v
```

최신 숫자 입력·비용 기준 적용 후 테스트는 사용자 요청에 따라 실행하지 않았습니다. 실제 DB 검색·유료 생성·RAGAS도 실행하지 않았습니다.

## 7. Django 연결과 남은 범위

이번에는 로컬 테스트 페이지까지만 추가했습니다. Django를 설치하거나 프로젝트를 새로 만들지 않았습니다. 이후 Django view에서 JSON을 받아 `src.services.calculate`, `create_report`, `search_policies`를 호출할 수 있도록 HTTP 코드를 계산·검색 로직과 분리했습니다.

테스트 서버는 127.0.0.1 전용이며 운영 배포용이 아닙니다. 운영 연결 시 인증·사용량 제한·개인정보 보관·긴 작업 처리 등을 별도로 구현해야 합니다.

보고서와 정책은 **코퍼스와 실행 기능**을 분리한 것이지 서로 다른 DB 서버를 둔 것은 아닙니다. pgvector 서버나 Elasticsearch 서버 자체가 중단되면 두 기능 모두 영향을 받을 수 있습니다. 채널 장애 시 자동 대체 검색도 이번에 구현하지 않았습니다.

비용 기준 자동 최신화·지역별 실제 매물 가격 수집·전국 중개보수 적용·정책 자격 판정은 구현하지 않았습니다. 기존 RAGAS 데이터는 정책 포함 보고서용일 수 있으므로 새 3문단 보고서에 그대로 점수를 매겨 비교하지 마세요. 답변 데이터의 파이프라인 표시는 새 경로로 바꾸고 계산 결과를 기록하도록 했지만 평가셋 재설계·재평가는 별도 작업입니다.
