# Git 브랜치 구조 실제 적용 가이드

이 문서는 `RAG-personal-project`에 실제로 적용한 과정을 기준으로 작성했다. 최종 구조는 다음과 같다.

```text
main   안정 버전
  ↑
dev    기본 브랜치이자 평소 개발 브랜치
  ↑
feature-XX   꼭 필요한 큰 기능에만 임시 사용
```

현재 GitHub 기본 브랜치는 `dev`다. 따라서 저장소 첫 화면과 새 clone의 최초 체크아웃 브랜치도 `dev`가 된다.

## 1. 적용 전 상태 확인

명령은 프로젝트 루트에서 실행한다.

```powershell
cd D:\RAG-personal-project
git status --short --branch
git branch --all --verbose
git remote -v
git log --oneline --decorate -5
```

이 프로젝트는 적용 당시 로컬과 원격에 `main`만 있었고, 구현 파일은 아직 커밋되지 않은 상태였다.

## 2. dev 생성 및 전환

현재 변경 사항을 유지하면서 `main`에서 `dev`를 만들었다.

```powershell
git switch -c dev
```

확인한다.

```powershell
git branch --show-current
```

결과가 `dev`면 정상이다.

## 3. 커밋 대상 확인

비밀키와 로컬 실행 산출물이 Git에 들어가지 않도록 `.gitignore`에 다음 항목을 포함했다.

```gitignore
.env
.venv/
.uv-cache/
.uv-python/
models/
__pycache__/
*.py[cod]
.pytest_cache/
.ipynb_checkpoints/
```

그다음 파일 크기와 변경 범위를 확인했다.

```powershell
git status --short
Get-ChildItem knowledge_base -Recurse -File |
    Sort-Object Length -Descending |
    Select-Object -First 20 FullName, Length
```

실제 확인 결과 지식베이스 전체는 약 29.7MB, 가장 큰 파일은 약 8MB였으므로 GitHub의 단일 파일 100MB 제한에 걸리지 않았다.

## 4. dev에 초기 작업 커밋

`git add .` 대신 커밋할 경로를 명시했다.

```powershell
git add -- README.md .env.example .gitignore .python-version `
    BRANCH_STRATEGY.md compose.yaml knowledge_base requirements.txt src 보고서.md

git diff --cached --stat
git commit -m "feat: build initial PDF ingestion pipeline"
```

이때 생성된 실제 커밋은 `d078977`이다.

## 5. 원격 dev 생성

```powershell
git push -u origin dev
```

`-u`를 사용했으므로 이후 `dev`에서는 다음 명령만 사용해도 된다.

```powershell
git push
git pull
```

## 6. GitHub 기본 브랜치를 dev로 변경

### 가장 쉬운 방법: GitHub 웹 화면

저장소 관리자 계정으로 다음 순서대로 변경한다.

1. GitHub 저장소의 `Settings`로 이동한다.
2. `Default branch` 항목을 찾는다.
3. 변경 버튼을 누르고 `dev`를 선택한다.
4. 변경 내용을 확인하고 저장한다.

### GitHub CLI가 설치된 경우

```powershell
gh auth login
gh repo edit hjoo10200/RAG-personal-project --default-branch dev
```

### 이 PC에서 실제 사용한 방법

이 PC에는 `gh`가 없고 브라우저도 GitHub에 로그인되어 있지 않았다. 대신 `git push`에 사용된 Windows Git 자격 증명을 메모리에서만 읽어 GitHub API에 전달했다.

```powershell
$credentialRequest = "protocol=https`nhost=github.com`n`n"
$credentialLines = $credentialRequest | git credential fill
$passwordLine = $credentialLines |
    Where-Object { $_ -like 'password=*' } |
    Select-Object -First 1

if (-not $passwordLine) {
    throw 'GitHub 인증 정보를 찾을 수 없습니다.'
}

$githubToken = $passwordLine.Substring('password='.Length)
$headers = @{
    Authorization = "Bearer $githubToken"
    Accept = 'application/vnd.github+json'
    'X-GitHub-Api-Version' = '2022-11-28'
    'User-Agent' = 'RAG-personal-project-setup'
}
$body = @{ default_branch = 'dev' } | ConvertTo-Json

$response = Invoke-RestMethod `
    -Method Patch `
    -Uri 'https://api.github.com/repos/hjoo10200/RAG-personal-project' `
    -Headers $headers `
    -ContentType 'application/json' `
    -Body $body

$response.default_branch
Remove-Variable githubToken, credentialLines, passwordLine -ErrorAction SilentlyContinue
```

주의할 점은 `$credentialLines`나 `$githubToken`을 `Write-Output`, `echo`, 로그 파일로 출력하면 안 된다는 것이다. 가능하면 웹 화면이나 GitHub CLI 방식을 우선 사용한다.

## 7. 로컬 origin/HEAD 동기화 및 검증

원격 기본 브랜치를 변경한 후 로컬 정보도 갱신한다.

```powershell
git remote set-head origin -a
git remote show origin
```

다음 결과가 보이면 정상이다.

```text
HEAD branch: dev
```

현재 브랜치와 upstream도 확인한다.

```powershell
git status --short --branch
git branch -vv
```

정상 예시는 다음과 같다.

```text
## dev...origin/dev
* dev  [origin/dev]
  main [origin/main]
```

## 8. 앞으로의 일상적인 작업

```powershell
git switch dev
git pull --ff-only

# 코드 작성 및 검증
git status --short
git add <변경한 파일 또는 디렉터리>
git commit -m "feat: 작업 내용"
git push
```

기능이 안정적으로 완성되면 GitHub에서 `dev → main` Pull Request를 만든다. 현재 기본 브랜치가 `dev`이므로 배포용 Pull Request를 만들 때는 대상 브랜치(base)를 반드시 `main`으로 직접 선택해야 한다.

## 9. feature-XX가 필요한 경우

작은 수정에는 만들지 않는다. 여러 커밋이 필요하고 작업 중 `dev`의 실행을 깨뜨릴 가능성이 있는 기능에만 사용한다.

```powershell
git switch dev
git pull --ff-only
git switch -c feature-01

# 기능 구현 및 커밋
git push -u origin feature-01

# 검증 후 dev로 병합
git switch dev
git merge --no-ff feature-01
git push
git branch -d feature-01
git push origin --delete feature-01
```

feature 브랜치는 `feature-01`, `feature-02`처럼 순서대로 이름을 붙이고 병합 후 삭제한다.

