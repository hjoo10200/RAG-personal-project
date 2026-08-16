# 청년 자취 독립 플래너 PDF 지식베이스

## RAG 로딩 경로

활성 문서는 아래 PDF만 사용한다.

```text
knowledge_base/pdfs/**/*.pdf
```

```text
knowledge_base/
├─ pdfs/                     # RAG 적재 대상
│  ├─ cases/                 # 실제 청년 경험과 실태
│  ├─ guides/                # 계약·이사·예산 실행 지식
│  └─ policies/              # 공식 지원정책 공고·시행계획
├─ metadata/                 # 활성 PDF 목록과 품질 검수 결과
└─ archive/                  # RAG 적재 제외
   ├─ source_originals/      # 발췌 전 전체 보고서와 비PDF 원문
   ├─ legacy_text_documents/ # 이전 TXT 변환본
   └─ legacy_metadata/       # 이전 구조의 메타데이터
```

## 현재 규모

- 사례 PDF 6개
- 실행 안내 PDF 4개
- 정책 PDF 7개
- 총 17개

대형 연구보고서는 자취 독립과 직접 관련된 장만 별도 PDF로 발췌했다. 화면은 정상이어도 텍스트 추출이 깨지는 문서는 활성 경로에 넣지 않았다.

## 청킹 원칙

- 사례: 참여자 또는 하나의 경험·문제 단위
- 안내서: 하나의 행동 단계나 법적 쟁점 단위
- 정책: 사업 개요, 신청자격, 지원내용, 제외대상, 제출서류, 신청방법 단위
- 표의 행을 무작정 분리하지 않고 표 제목과 머리글을 청크에 포함
- 원문 페이지 번호와 파일명을 모든 청크 메타데이터에 저장

품질 판정과 제외 사유는 [pdf_quality_audit.md](metadata/pdf_quality_audit.md), 기계 판독용 목록은 [active_pdf_manifest.json](metadata/active_pdf_manifest.json)을 사용한다.
