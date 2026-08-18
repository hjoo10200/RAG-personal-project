# Vector-only 검색 기준선

2026-08-17에 PGVector 코사인 유사도 검색으로 실행한 결과를 변경되지 않는 비교 기준으로 보존한다.

## 기준선

- 평가 질문: 15개
- Source Hit@3: 86.67% (13/15)
- 기대 문서 평균 회수율: 86.67%
- MRR: 0.9222
- 임베딩: `intfloat/multilingual-e5-small`, 384차원

이 디렉터리의 파일은 Elasticsearch 또는 Hybrid 검색 평가를 실행할 때 덮어쓰지 않는다. 새로운 결과는 별도 디렉터리나 기본 `evaluation/retrieval_*` 출력에 저장한 뒤 이 기준선과 비교한다.
