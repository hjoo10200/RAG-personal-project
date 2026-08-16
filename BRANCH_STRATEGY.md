# 브랜치 전략

이 프로젝트는 개인 프로젝트에 맞춰 `main`과 `dev` 두 개의 상시 브랜치만 사용한다.

## 상시 브랜치

- `main`: 실행과 검증이 끝난 안정 버전만 유지한다.
- `dev`: 평소 개발과 커밋을 진행하는 기본 작업 브랜치다.

일반적인 작업 흐름은 다음과 같다.

```text
dev에서 구현·검증·커밋
→ 기능 단위가 완성되면 dev를 main으로 병합
→ main에 버전 태그 생성
→ 다음 작업은 다시 dev에서 진행
```

`main`에는 직접 기능을 개발하거나 미완성 코드를 커밋하지 않는다. 개인 프로젝트이므로 모든 작은 작업마다 Pull Request를 만들 필요는 없지만, 포트폴리오에서 변경 이력을 명확히 보여줄 중요한 기능은 `dev → main` Pull Request로 병합한다.

## feature 브랜치를 만드는 경우

현재는 만들지 않는다. 다음 조건 중 하나에 해당할 때만 `dev`에서 분기한다.

- 기존 검색·적재 흐름을 크게 변경하는 실험
- 여러 커밋이 필요하고 중간 상태가 `dev`의 실행을 깨뜨릴 수 있는 기능
- 다른 기능과 병렬로 개발해야 하는 작업

이때 이름은 `feature-01`, `feature-02`처럼 `feature-XX` 형식을 사용한다. 번호와 작업 내용은 이 문서나 이슈에 기록한다.

```powershell
git switch dev
git switch -c feature-01

# 구현과 검증 후
git switch dev
git merge --no-ff feature-01
git branch -d feature-01
```

feature 브랜치는 병합 후 삭제하며 장기간 유지하지 않는다.

## 현재 적용 상태

- 안정 브랜치: `main`
- 개발 브랜치: `dev`
- feature 브랜치: 없음

