## 🛠 개발 환경 설정

### 요구 사항
- Python 3.11
- Conda (또는 venv)

### 설치 방법

```bash
# 1. 가상환경 생성 및 활성화
conda create -n gamgyul python=3.11 -y
conda activate gamgyul

# 2. 패키지 설치
pip install -r requirements.txt

# 3. 환경변수 설정
cp .env.example .env
# .env 파일에 GEMINI_API_KEY 입력
```

### 사용 패키지

| 패키지 | 용도 |
|---|---|
| `langgraph` | Agent Workflow 엔진 (노드/상태/분기 제어) |
| `langchain-core` | LangGraph 의존성, 메시지 타입 |
| `langchain-google-genai` | Gemini API 연동 |
| `python-dotenv` | 환경변수(.env) 로드 |
| `pydantic` | 구조화된 출력(Structured Output) 스키마 정의 |
| `streamlit` | 사용자 인터페이스 |
| `requests` | 외부 API 호출 |

### 실행 방법

```bash
python -m agent.graph      # 그래프 단독 테스트
streamlit run app.py       # 전체 앱 실행
```
