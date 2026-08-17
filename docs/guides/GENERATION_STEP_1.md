# 증강 생성 1단계: Groq 종합 보고서 출력 확인

이번 단계는 PGVector 검색과 최종 시각화를 연결하기 전에 다음 경로만 검증한다.

```text
사용자 상황 JSON + 검색 근거 JSON
  -> LangChain ChatPromptTemplate
  -> LangChain ChatGroq / openai/gpt-oss-120b
  -> 제목과 하나의 Markdown 본문을 담은 NarrativeReport JSON
```

`examples/inputs/generation_smoke_input.json`의 `TEST_*.pdf` 내용은 API 연결과 구조 검증만을 위한 합성 데이터이며 실제 정책 정보가 아니다.

## 1. API 키 입력

프로젝트 루트의 `.env`에서 다음 항목에 Groq Console에서 발급한 키를 입력한다.

```dotenv
GROQ_API_KEY=gsk_...
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

성공하면 `storage/generated_reports/smoke_report.json`에 `report_title`과 `report_body_markdown`을 가진 JSON이 저장된다. 모델은 내부적으로 일곱 주제의 분석 문단과 실행 문단을 각각 생성하고, 프로그램이 이를 하나의 Markdown 본문으로 합친다. 최종 본문은 목록이나 표가 아닌 자세한 서술형 문단이며 각 소제목에는 정확히 두 문단이 들어가고 전체 본문은 3,000자 이상이어야 한다. 이 디렉터리는 Git 추적에서 제외된다.

## 현재 포함하지 않은 범위

- 사용자 상황을 검색 질문으로 분해하는 기능
- PGVector에서 근거를 자동으로 가져오는 기능
- Markdown 보고서를 HTML/PDF로 렌더링하는 기능
- 최종 보고서 UI

다음 단계에서는 현재 검색 모듈의 결과를 `retrieved_context`에 자동으로 연결한다.

생성에는 `langchain-groq`의 `ChatGroq`를 사용한다. 프롬프트, 모델 호출, strict JSON Schema 구조화 출력까지 LangChain 파이프라인으로 실행한다.
