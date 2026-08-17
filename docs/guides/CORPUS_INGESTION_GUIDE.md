# PDF 코퍼스별 PGVector 적재 가이드

이 프로젝트는 하나의 PostgreSQL 데이터베이스 안에서 PDF를 다음 세 PGVector 컬렉션으로 분리한다.

| corpus | PDF 위치 | PGVector 컬렉션 | 청킹 |
|---|---|---|---:|
| `guides` | `knowledge_base/pdfs/guides` | `youth_independence_guides` | 800/120 |
| `cases` | `knowledge_base/pdfs/cases` | `youth_independence_cases` | 1000/150 |
| `policies` | `knowledge_base/pdfs/policies` | `youth_independence_policies` | 900/150 |

청킹 값은 `청크 최대 문자 수/앞뒤 중첩 문자 수`다. 세 컬렉션은 모두 같은 `intfloat/multilingual-e5-small` 임베딩 모델과 384차원 벡터를 사용한다.

## 실행 위치

모든 명령은 PowerShell에서 프로젝트 루트로 이동한 뒤 실행한다.

```powershell
cd D:\RAG-personal-project
```

프로젝트 루트에는 다음 파일과 디렉터리가 보여야 한다.

```text
compose.yaml
src/
knowledge_base/
.venv/
```

## 1. PostgreSQL과 pgvector 시작

```powershell
docker compose up -d
docker compose ps
```

`docker compose ps` 결과에서 `youth-rag-pgvector`가 `healthy`면 다음 단계로 진행한다.

## 2. 적재 전 PDF 로딩과 청킹만 확인

이 단계는 선택 사항이지만 먼저 실행하는 것을 권장한다. `--dry-run`은 임베딩 모델을 로드하지 않고 DB도 변경하지 않는다.

전체 PDF를 확인하려면 다음 명령을 실행한다.

```powershell
.venv\Scripts\python.exe -m src.ingestion.ingest --corpus all --dry-run
```

각 그룹을 따로 확인할 수도 있다.

```powershell
.venv\Scripts\python.exe -m src.ingestion.ingest --corpus guides --dry-run
.venv\Scripts\python.exe -m src.ingestion.ingest --corpus cases --dry-run
.venv\Scripts\python.exe -m src.ingestion.ingest --corpus policies --dry-run
```

## 3. PDF 전체 적재

세 컬렉션을 한 번에 순차 적재하려면 다음 명령을 실행한다.

```powershell
.venv\Scripts\python.exe -m src.ingestion.ingest --corpus all
```

처리 순서는 `guides → cases → policies`다. 임베딩 모델은 처음에 한 번만 메모리에 로드하고 세 컬렉션에서 재사용한다.

개별 컬렉션만 다시 만들고 싶다면 다음 중 하나만 실행한다.

```powershell
.venv\Scripts\python.exe -m src.ingestion.ingest --corpus guides
.venv\Scripts\python.exe -m src.ingestion.ingest --corpus cases
.venv\Scripts\python.exe -m src.ingestion.ingest --corpus policies
```

적재 명령은 선택한 컬렉션을 삭제한 뒤 새로 만든다. 예를 들어 `--corpus cases`는 `youth_independence_cases`만 재구축하며 `guides`와 `policies` 컬렉션에는 영향을 주지 않는다.

완료 시 각 코퍼스에 대해 다음 형태의 검증 로그가 출력되어야 한다.

```text
[verify] corpus=cases, collection=youth_independence_cases, stored_chunks=...
```

생성된 청크 수와 DB에 저장된 행 수가 다르면 프로그램이 오류로 종료된다.

## 4. 컬렉션별 검색 확인

가이드 검색:

```powershell
.venv\Scripts\python.exe -m src.retrieval.search "전세계약 전에 확인할 사항" --corpus guides -k 3
```

사례 검색:

```powershell
.venv\Scripts\python.exe -m src.retrieval.search "취업 때문에 서울로 이사한 청년의 자취 사례" --corpus cases -k 3
```

정책 검색:

```powershell
.venv\Scripts\python.exe -m src.retrieval.search "서울 청년 월세 지원 신청 조건" --corpus policies -k 3
```

세 컬렉션을 같은 질의로 각각 검색:

```powershell
.venv\Scripts\python.exe -m src.retrieval.search "취업을 위해 서울에서 처음 독립하려면 무엇을 준비해야 하나요?" --corpus all -k 3
```

`--corpus all -k 3`은 결과를 합쳐서 3개만 반환하는 것이 아니라 각 컬렉션에서 최대 3개씩 반환한다.

## 환경변수로 설정 변경

기본값을 바꾸려면 `.env.example`을 참고해 프로젝트 루트의 `.env`에 필요한 항목만 추가한다.

```dotenv
GUIDES_COLLECTION=youth_independence_guides
GUIDES_CHUNK_SIZE=800
GUIDES_CHUNK_OVERLAP=120

CASES_COLLECTION=youth_independence_cases
CASES_CHUNK_SIZE=1000
CASES_CHUNK_OVERLAP=150

POLICIES_COLLECTION=youth_independence_policies
POLICIES_CHUNK_SIZE=900
POLICIES_CHUNK_OVERLAP=150
```

기존 `CHUNK_SIZE`, `CHUNK_OVERLAP`, `GUIDES_COLLECTION` 환경변수는 `guides` 설정에 한해 계속 호환된다.

## 저장되는 공통 메타데이터

모든 청크에는 다음 값이 저장된다.

- `corpus`: `guides`, `cases`, `policies` 중 하나
- `knowledge_role`: corpus와 동일한 역할
- `source`: 프로젝트 루트 기준 PDF 경로
- `source_file`: 원본 PDF 파일명
- `page_number`: 원본 페이지 번호
- `document_sha256`: 원본 파일 해시
- `chunk_index`: 페이지 안에서의 청크 순번
- `chunk_id`: corpus, 파일 해시, 페이지, 순번, 본문으로 만든 고유 ID
- `character_count`: 정규화된 청크 문자 수

## 실행 시 주의사항

- 첫 실행은 모델 로딩과 CPU 임베딩 때문에 시간이 걸릴 수 있다.
- 실행 중 강제 종료하면 이미 완료된 앞쪽 컬렉션은 새 데이터로 바뀌고, 아직 처리하지 않은 컬렉션은 기존 상태로 남을 수 있다.
- `models/`와 `.env`는 `.gitignore`에 포함되어 있으므로 Git에 올리지 않는다.
- 이 문서를 작성한 시점에는 사용자 요청에 따라 새 적재 명령을 실행하지 않았다.

## PostgreSQL NUL 문자 오류

일부 PDF는 화면에는 정상적으로 보여도 텍스트 추출 결과에 NUL 문자(`0x00`)를 포함한다. PostgreSQL의 `text`, `varchar`, `jsonb` 필드는 이 문자를 저장할 수 없어 다음 오류가 발생할 수 있다.

```text
PostgreSQL text fields cannot contain NUL (0x00) bytes
```

현재 파이프라인은 PDF 페이지 본문과 메타데이터를 읽은 직후 NUL 문자를 공백으로 치환하고, 청크를 생성한 뒤에도 다시 검사한다. 치환이 발생하면 다음 형태의 로그가 출력된다.

```text
[sanitize] example.pdf: NUL 문자 12개를 공백으로 치환
```

이 오류로 적재가 중단됐다면 실패한 corpus만 다시 실행하면 된다. 예를 들어 `cases` 적재 중 실패했다면 다음 명령을 사용한다.

```powershell
.venv\Scripts\python.exe -m src.ingestion.ingest --corpus cases
```

선택한 컬렉션은 실행 시 새로 구축되므로 실패 당시의 불완전한 `cases` 데이터를 별도로 삭제할 필요는 없다.
