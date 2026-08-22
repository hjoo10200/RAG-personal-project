# 증강 생성 1단계: OpenAI 종합 보고서 출력 확인

이번 단계는 PGVector 검색과 최종 시각화를 연결하기 전에 다음 경로만 검증한다.

```text
사용자 상황 JSON + 검색 근거 JSON
  -> LangChain ChatPromptTemplate
  -> LangChain ChatOpenAI / gpt-5.4-mini
  -> 제목과 하나의 Markdown 본문을 담은 NarrativeReport JSON
```

`examples/inputs/generation_smoke_input.json`의 `TEST_*.pdf` 내용은 API 연결과 구조 검증만을 위한 합성 데이터이며 실제 정책 정보가 아니다.

## 1. API 키 입력

프로젝트 루트의 `.env`에서 다음 항목에 OpenAI Platform에서 발급한 키를 입력한다.

```dotenv
OPENAI_API_KEY=sk-...
```

키는 `.gitignore`에 포함된 `.env`에만 저장하고 코드나 `.env.example`에는 입력하지 않는다.

## 2. API 호출 없는 검증

```powershell
cd D:\RAG-personal-project
.venv\Scripts\python.exe -m src.generation.generate_report `
  --input examples\inputs\generation_smoke_input.json `
  --validate-input
```

API 키를 입력한 뒤 모델 설정도 확인한다.

```powershell
.venv\Scripts\python.exe -m src.generation.generate_report --check-config
```

## 3. 실제 구조화 생성 시험

```powershell
.venv\Scripts\python.exe -m src.generation.generate_report `
  --input examples\inputs\generation_smoke_input.json `
  --output storage\generated_reports\smoke_report.json
```

성공하면 `storage/generated_reports/smoke_report.json`에 `report_title`과 `report_body_markdown`을 가진 JSON이 저장된다. 모델은 독립 판단, 개인별 실행 순서, 위험 대응, 적합 정책의 네 문단과 내부 근거 ID를 생성한다. 프로그램은 내부 근거가 실제 검색 결과인지 확인한 뒤 출처 표시를 제거하고 존댓말 Markdown 본문만 사용자 출력에 저장한다. 본문 강제 허용 범위는 800~3,700자이며, 프롬프트는 이 하한보다 자세하게 쓰도록 유도한다. 각 절은 한 문단으로 유지하되 확인 대상·비교 기준·결과에 따른 다음 행동을 구체적으로 설명한다. 이 디렉터리는 Git 추적에서 제외된다.

## 현재 포함하지 않은 범위

- 사용자 상황을 검색 질문으로 분해하는 기능
- PGVector에서 근거를 자동으로 가져오는 기능
- Markdown 보고서를 HTML/PDF로 렌더링하는 기능
- 최종 보고서 UI

다음 단계에서는 현재 검색 모듈의 결과를 `retrieved_context`에 자동으로 연결한다.

생성에는 `langchain-openai`의 `ChatOpenAI`와 `gpt-5.4-mini`를 사용한다. 프롬프트, 모델 호출, strict JSON Schema 구조화 출력까지 LangChain 파이프라인으로 실행한다.
