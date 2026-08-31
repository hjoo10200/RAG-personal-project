# 프로젝트 문서

문서는 목적에 따라 실행 가이드, Git 작업 가이드, 구현 보고서로 분리되어 있다.

## 전체 구현 설명

- [계산 선행·보고서/정책 분리 최신 구현](reports/RAG_REFACTOR_IMPLEMENTATION.md): 숫자 직접 입력, 공식 비용 기준, 테스트 페이지와 실행 명령
- [비용 기준 수집 및 적용](reports/COST_REFERENCE_RESEARCH_20260831.md): 채택한 수치·공식 출처·계산식·적용 한계
- [현재 구현 상세 설명서](IMPLEMENTATION_OVERVIEW.md): 전체 흐름, 입력·출력, 적재·검색·생성 방식과 미구현 범위

## 개편 계획

- [청년 독립 RAG 개편 실행계획](reports/RAG_REFACTOR_EXECUTION_PLAN.md): 선택형 입력, 검색 전 계산·재정 판단, 보고서와 정책 검색 분리, 단계별 검증
- [청년 자취 독립 자금 계획 계산식](reports/INDEPENDENCE_COST_FORMULAS.md): 초기 자금·월 잔액·주거비 역산과 구간 처리
- [개편 전 실제 RAG 플로우차트](reports/CURRENT_RAG_FLOWCHART.md): 현재 코드 기준 적재·검색·생성 경로

## 실행 가이드

- [PDF 적재 가이드](guides/CORPUS_INGESTION_GUIDE.md)
- [생성 단계 검증 가이드](guides/GENERATION_STEP_1.md)
- [실제 RAG 실행 가이드](guides/REAL_RAG_RUN_GUIDE.md)
- [Elasticsearch 키워드 검색 가이드](guides/ELASTICSEARCH_KEYWORD_SEARCH.md)

## Git 가이드

- [브랜치 전략](git/BRANCH_STRATEGY.md)
- [브랜치 설정 절차](git/GIT_BRANCH_SETUP_GUIDE.md)

## 구현 보고서

- [적재 파이프라인 개선 보고서](reports/INGESTION_PIPELINE_REPORT.md)
- [Elasticsearch 키워드 검색 구현 흐름 설명서](reports/ELASTICSEARCH_KEYWORD_PIPELINE.md)
- [Hybrid RAG 구현 흐름 설명서](reports/HYBRID_RAG_PIPELINE.md)
