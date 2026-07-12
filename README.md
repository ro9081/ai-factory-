# AI Factory — Proof of Concept (POC)

## Overview
AI Factory is an end-to-end "Tracer Bullet" application designed to automate and augment the Product Management workflow. It takes a raw, underspecified user story and employs a multi-agent AI pipeline to interactively interview the human Product Manager, clarify ambiguities, and ultimately generate a structured, ready-to-execute Product Requirements Document (PRD).

The application is built as a complete vertical slice—featuring an interactive dashboard, role-based access control, real-time analytics, an asynchronous backend, and a deterministic AI state machine.

---

## Architecture & Technology Stack

The project adopts a modern, decoupled architecture designed for rapid iteration and strict data contracts.

### 1. Frontend: Streamlit
- **Why?** Allows for lightning-fast UI development purely in Python without managing complex React/NPM toolchains. 
- **Features:** 
  - Glassmorphic CSS styling for a premium feel.
  - Interactive filtering and live metrics without full-page re-renders.
  - Manages JWT session state locally and injects it into API requests.

### 2. API Layer: FastAPI + Strawberry GraphQL
- **Why?** GraphQL provides strict typing and a flexible query language, preventing over-fetching and under-fetching. FastAPI provides a lightning-fast, asynchronous foundation.
- **Features:**
  - Exposes a single `/graphql` endpoint.
  - Context injection: Extracts the JWT from HTTP headers and injects the resolved `User` object into the Strawberry context for downstream resolvers.

### 3. AI Orchestration: LangGraph + Groq
- **Why?** Traditional LLM chains are linear and fragile. LangGraph allows us to define the AI workflow as a deterministic State Machine (Graphs) with cyclic behaviors. Groq provides ultra-low latency inference (using Llama 3 models), which is critical for synchronous API workflows.
- **Features:**
  - Explicit state transitions (`Draft` → `Clarifying` → `Green_Light`).
  - Context window management and conversation thread reconstruction.

### 4. Database: SQLite + SQLAlchemy (Async)
- **Why?** Zero-config relational database perfect for POCs, mapped via SQLAlchemy's asynchronous sessions to avoid blocking the FastAPI event loop.

---

## The AI Workflow & State Machine

The core of the application is a LangGraph state machine (`backend/workflow/graph.py`) that governs the story lifecycle.

1. **Evaluation (PM Agent):** When a story is submitted, an internal PM Agent evaluates the description. It checks for missing personas, success metrics, and constraints.
2. **Clarification Loop (Clarifier):** If information is missing, the workflow halts in the `Clarifying` state and the Clarifier agent asks targeted questions. 
   - *Constraint:* To prevent infinite loops, the system enforces a hard limit of 3 clarification rounds.
3. **Generation (PRD Writer):** Once the human PM provides satisfactory answers (or the 3-round limit is hit), the PRD Writer agent compiles the entire Q&A thread and generates a structured PRD. The story transitions to `Green_Light`.
4. **Human Review:** The PM can either Accept the PRD (`Accepted`) or submit Revisions, which kicks the story back into the `Clarifying` state for the AI to rewrite.

---

## Core Entities & Data Schemas

The database schema is strictly normalized and accessed via GraphQL Types:

### 1. User
Handles Authentication and Role-Based Access Control (RBAC).
- `id` (UUID)
- `username` (String, Unique)
- `password_hash` (String, bcrypt)
- `role` (String: `PM`, `Engineer`, `Admin`)

### 2. Story
The central artifact being tracked through the pipeline.
- `id` (UUID)
- `title` (String)
- `description` (Text)
- `status` (Enum: `Draft`, `Clarifying`, `Green_Light`, `Accepted`)

### 3. Comment
Represents the communication thread between the Human PM and the AI Agents. Also used to store the generated PRD content.
- `id` (UUID)
- `story_id` (UUID, Foreign Key)
- `author` (String: `PM`, `Clarifier`, `PRD Writer`)
- `text` (Text)
- `createdAt` (Datetime)

---

## Feature Implementation Details

### Role-Based Access Control (RBAC)
Security is implemented natively at the GraphQL schema layer. We utilize `strawberry.BasePermission` classes (`IsPM`, `IsAdminOrPM`). 
- If an `Engineer` attempts to invoke the `createStory` mutation, the GraphQL router rejects the request before it ever hits the business logic. 
- Passwords are securely hashed using raw `bcrypt` and truncated at 72 bytes.

### Dynamic Filtering & Analytics
The sidebar features a KPI analytics widget tracking the number of stories in each state. 
- Clicking a KPI metric writes a `status_filter` to the Streamlit session state, which reactively filters the main dashboard grid. 
- The widget logic queries the GraphQL endpoint efficiently using a minimal query (`{ stories { status } }`).

### PDF Generation
To enable offline sharing, the application uses `fpdf2` to convert the Markdown-formatted PRD into a styled, downloadable PDF directly in memory, entirely within the Streamlit frontend.
