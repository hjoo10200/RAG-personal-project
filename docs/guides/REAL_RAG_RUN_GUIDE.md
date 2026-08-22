# 실제 Hybrid RAG 실행

이 명령은 합성 `TEST_*` 문서를 사용하지 않는다. 사용자 상황만 입력받아 실제 `guides`, `cases`, `policies` PGVector 컬렉션과 Elasticsearch 인덱스를 함께 검색한다. 두 검색 순위는 Weighted RRF로 결합되며, 최종 PDF 청크만 OpenAI `gpt-5.4-mini` 보고서 생성에 전달된다.

실행 전 PostgreSQL·PGVector와 Elasticsearch가 모두 실행 중이고 각 코퍼스가 양쪽 저장소에 적재되어 있어야 한다.

```powershell
docker compose up -d
docker compose ps
```

## 검색만 검증

```powershell
cd D:\RAG-personal-project

.venv\Scripts\python.exe -m src.run_rag `
  --input examples\inputs\real_rag_input.json `
  --output storage\generated_reports\hybrid_rag_report.json `
  --evidence-output storage\generated_reports\hybrid_rag_evidence.json `
  --retrieve-only
```

## 검색부터 보고서 생성까지 실행

```powershell
.venv\Scripts\python.exe -m src.run_rag `
  --input examples\inputs\real_rag_input.json `
  --output storage\generated_reports\hybrid_rag_report.json `
  --evidence-output storage\generated_reports\hybrid_rag_evidence.json
```

- `hybrid_rag_evidence.json`: 실제 결합 청크, 원본 PDF·페이지, 검색 채널, RRF 점수와 하위 질의
- `hybrid_rag_report.json`: 실제 검색 근거로 생성한 최종 서술형 보고서

근거 JSON의 `retrieval_methods`가 `["keyword", "vector"]`이면 두 검색기에서 모두 발견한 청크다. 하나의 값만 있으면 해당 검색기에서만 발견했지만 결합 순위에 포함된 청크다. `hybrid_score`는 서로 다른 원시 점수를 직접 더한 값이 아니라 순위를 결합한 값이다.
