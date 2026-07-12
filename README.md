# AI Factory — Internal POC

A minimal, end-to-end **Tracer Bullet** implementation of the AI Factory story workflow.

## Stack
| Layer | Technology |
|---|---|
| Backend API | FastAPI 0.115 |
| GraphQL | Strawberry GraphQL |
| Database | SQLite via SQLAlchemy 2.0 (async / aiosqlite) |
| Workflow | LangGraph 3-agent state graph |
| Frontend | Streamlit |

## Quick Start

### 1. Install dependencies
```bash
cd c:\Program1\AiFactory
pip install -r requirements.txt
```

### 2. Start the backend (terminal 1)
```bash
uvicorn backend.main:app --reload --port 8000
```
GraphiQL playground: http://localhost:8000/graphql

### 3. Start the Streamlit dashboard (terminal 2)
```bash
streamlit run frontend/app.py
```
Dashboard: http://localhost:8501

---

## Data Model

```
Story
  id          UUID string
  title       str
  description str
  status      Draft | Clarifying | Green_Light | Accepted

Comment
  id          UUID string
  story_id    FK → Story.id
  author      PM | Agent
  text        str
  created_at  datetime (UTC)
```

## LangGraph Pipeline

```
createStory → (Draft)
     │
     ▼ runWorkflow
  [PM Agent]
     │
     ├─ needs_clarification=True  → [Clarifier Agent] → status: Clarifying
     │                                   ↓
     │                           runWorkflow again
     │                           (status=Clarifying → skip clarification)
     │
     └─ needs_clarification=False → [PRD Writer Agent] → status: Green_Light
```

## Upgrading to a Real LLM

Replace stub logic in `backend/workflow/graph.py` with LangChain LLM calls:

```python
from langchain_openai import ChatOpenAI
llm = ChatOpenAI(model="gpt-4o-mini")
# Use llm.invoke(...) inside each agent node
```

Set `OPENAI_API_KEY` in your environment or a `.env` file.
