# 실제 PGVector RAG 실행

이 명령은 합성 `TEST_*` 문서를 사용하지 않는다. 사용자 상황만 입력받아 실제 `guides`, `cases`, `policies` PGVector 컬렉션을 검색하고, 검색된 PDF 청크만 Groq 보고서 생성에 전달한다.

## 검색만 검증

```powershell
cd D:\RAG-personal-project

.venv\Scripts\python.exe -m src.run_rag `
  --input examples\inputs\real_rag_input.json `
  --output storage\generated_reports\real_rag_report.json `
  --evidence-output storage\generated_reports\real_rag_evidence.json `
  --retrieve-only
```

## 검색부터 보고서 생성까지 실행

```powershell
.venv\Scripts\python.exe -m src.run_rag `
  --input examples\inputs\real_rag_input.json `
  --output storage\generated_reports\real_rag_report.json `
  --evidence-output storage\generated_reports\real_rag_evidence.json
```

- `real_rag_evidence.json`: 실제 PGVector 검색 청크와 원본 PDF 파일명·페이지
- `real_rag_report.json`: 실제 검색 근거로 생성한 최종 서술형 보고서
