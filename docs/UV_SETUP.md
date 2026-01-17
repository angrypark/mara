# UV Setup Guide

이 프로젝트는 `uv`를 사용하여 Python 버전 및 의존성을 관리합니다.

## UV 설치

```bash
# macOS/Linux
curl -LsSf https://astral.sh/uv/install.sh | sh

# 또는 Homebrew
brew install uv
```

## 프로젝트 설정

### 1. Python 버전 설치 및 가상환경 생성

```bash
# 프로젝트 디렉토리로 이동
cd /Users/marv/mara

# Python 3.11 설치 (uv가 자동으로 관리)
uv python install 3.11

# 가상환경 생성
uv venv

# 가상환경 활성화
source .venv/bin/activate  # macOS/Linux
# .venv\Scripts\activate   # Windows
```

### 2. 의존성 설치

```bash
# 기본 의존성 설치
uv pip install -e .

# 개발 의존성 포함 설치
uv pip install -e ".[dev]"

# 선택적: Redis 캐싱 사용 시
uv pip install -e ".[cache]"
```

### 3. 환경 변수 설정

```bash
# .env 파일 생성
cp .env.example .env

# .env 파일 편집
vim .env
```

`.env` 내용:
```bash
ANTHROPIC_API_KEY=sk-ant-your-api-key-here
```

## UV 주요 명령어

### 의존성 관리

```bash
# 새로운 패키지 추가
uv pip install package-name

# pyproject.toml에 추가 후 설치
uv pip install -e .

# 의존성 업데이트
uv pip install --upgrade package-name

# 모든 의존성 업데이트
uv pip install --upgrade -e .
```

### Python 버전 관리

```bash
# 사용 가능한 Python 버전 확인
uv python list

# 특정 버전 설치
uv python install 3.11.7

# 현재 프로젝트의 Python 버전 확인
uv python pin

# Python 버전 변경
uv python pin 3.11.8
```

### 가상환경 관리

```bash
# 가상환경 재생성
uv venv --force

# 특정 Python 버전으로 가상환경 생성
uv venv --python 3.11

# 가상환경 삭제
rm -rf .venv
```

## 개발 워크플로우

### 1. 새로운 기능 개발 시작

```bash
# 최신 의존성 설치
uv pip install -e ".[dev]"

# 코드 포맷팅
black src/ tests/
ruff check src/ tests/ --fix

# 타입 체크
mypy src/
```

### 2. 테스트 실행

```bash
# 전체 테스트
pytest

# 특정 테스트 파일
pytest tests/test_macro_agents.py

# 커버리지 포함
pytest --cov=src --cov-report=html
```

### 3. 코드 품질 체크

```bash
# Ruff로 린팅
ruff check src/

# Black으로 포맷팅 체크
black --check src/

# 자동 수정
ruff check src/ --fix
black src/
```

## pyproject.toml vs requirements.txt

이 프로젝트는 `pyproject.toml`을 사용합니다. 하지만 호환성을 위해 `requirements.txt`도 유지합니다.

**pyproject.toml의 장점**:
- 최신 Python 표준 (PEP 518, 621)
- 메타데이터와 의존성을 한 곳에서 관리
- optional dependencies 지원 (`[dev]`, `[cache]`)
- 빌드 시스템 설정 포함

**requirements.txt 생성** (필요 시):
```bash
uv pip freeze > requirements.txt
```

## 문제 해결

### uv가 느린 경우

```bash
# 캐시 위치 확인
uv cache dir

# 캐시 정리
uv cache clean
```

### Python 버전 충돌

```bash
# 현재 사용 중인 Python 확인
uv python list

# .python-version 파일 확인
cat .python-version

# 강제로 재설치
uv venv --force --python 3.11
```

### 의존성 설치 실패

```bash
# 로그 확인
uv pip install -e . -vv

# 캐시 없이 재설치
uv pip install -e . --refresh
```

## VS Code 통합

`.vscode/settings.json`:
```json
{
    "python.defaultInterpreterPath": "${workspaceFolder}/.venv/bin/python",
    "python.terminal.activateEnvironment": true,
    "python.linting.enabled": true,
    "python.linting.ruffEnabled": true,
    "python.formatting.provider": "black",
    "editor.formatOnSave": true,
    "[python]": {
        "editor.codeActionsOnSave": {
            "source.organizeImports": true
        }
    }
}
```

## CI/CD에서 UV 사용

`.github/workflows/test.yml`:
```yaml
name: Test

on: [push, pull_request]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Install uv
        run: curl -LsSf https://astral.sh/uv/install.sh | sh

      - name: Set up Python
        run: uv python install 3.11

      - name: Install dependencies
        run: uv pip install -e ".[dev]"

      - name: Run tests
        run: pytest
```

## 참고 자료

- [UV Documentation](https://github.com/astral-sh/uv)
- [PEP 621 - Storing project metadata in pyproject.toml](https://peps.python.org/pep-0621/)
