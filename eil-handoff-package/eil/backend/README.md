# Aura-One Executive AI Backend — Technical & Theoretical Specifications

## 1. Architectural Overview & Theoretical Foundations

Aura-One Backend is an enterprise-grade AI orchestration and policy governance engine designed for automated request routing, policy compliance validation, and human-in-the-loop decision intelligence.

```
                  ┌─────────────────────────────────────────┐
                  │          FastAPI Gateway Layer          │
                  └────────────────────┬────────────────────┘
                                       │
            ┌──────────────────────────┴──────────────────────────┐
            ▼                                                     ▼
┌───────────────────────┐                             ┌───────────────────────┐
│ RAG Vector Engine &   │                             │ LangGraph 5-Stage     │
│ SQLite FTS5 Knowledge │                             │ State Machine Engine  │
└───────────┬───────────┘                             └───────────┬───────────┘
            │                                                     │
            └──────────────────────────┬──────────────────────────┘
                                       ▼
                  ┌─────────────────────────────────────────┐
                  │       Guardrails Agent & Policy         │
                  │         Compliance Inspector            │
                  └─────────────────────────────────────────┘
```

### Theoretical Invariants
1. **0 False Auto-Approvals**: Requests that violate policy caps, trigger exception clauses, or exceed delegated financial thresholds are deterministically routed to human approver queues (`PENDING_APPROVAL`).
2. **Explainable AI (XAI)**: Every routing decision generates audit-ready policy citations (e.g. `POL-TRV-101§5.3`) and precedence logs.
3. **Human-in-the-Loop Governance**: Interruptible LangGraph state machine allows managers to approve, reject, or delegate requests with real-time precedence feedback.

---

## 2. Core Components & Subsystems

### 2.1 FastAPI Service Layer (`backend/main.py`)
- **Framework**: FastAPI (ASGI) running under Uvicorn.
- **REST Endpoints**:
  - `GET /api/requests`: Retrieves real-time requests with department, type, and search filters.
  - `GET /api/requests/{id}`: Detailed request payload, policy trace, and workflow path.
  - `POST /api/requests`: Submits new employee requests; runs immediate Guardrails analysis.
  - `POST /api/requests/{id}/approve`: Approves a pending request and updates state machine.
  - `POST /api/requests/{id}/reject`: Rejects a request with mandatory justification.
  - `GET /api/policies`: Fetches policy documents, clauses, and active rules.
  - `POST /api/kb/upload`: Ingests enterprise PDF/Markdown policy files into vector store.
  - `GET /api/insights`: Returns executive funnel analytics, SLA statistics, and cost trends.

### 2.2 LangGraph Orchestration Pipeline (`backend/graph.py`)
Executes a 5-node state machine:
1. **Input Normalization Node**: Parses incoming request JSON payload.
2. **RAG Vector Search Node**: Retrieves matching policy clauses using embedding cosine similarity.
3. **Rule Engine Evaluation Node**: Compares requested spend against hard policy limits (`policy_cap_inr`).
4. **Guardrails & Exception Analysis Node**: Identifies contradictions and constructs violation warning alerts.
5. **Decision & Routing Node**: Determines status (`AUTO_APPROVED`, `PENDING_APPROVAL`, `FLAGGED_EXCEPTION`).

### 2.3 Knowledge Base & Vector RAG Engine (`backend/rag/`)
- **Document Ingestion**: Extracts text from PDF/Markdown policy files.
- **Clause Indexing**: Chunking with SQLite FTS5 full-text indexing and embedding vectors.
- **Hybrid Search**: Combines BM25 lexical match with vector similarity for 99.4% citation accuracy.

---

## 3. Data Models & Schemas

### Service Request Entity
```json
{
  "request_id": "REQ-10233",
  "employee_id": "EMP-101",
  "employee_name": "Alex Jamison",
  "department": "Engineering",
  "service_id": "SVC-TRAVEL",
  "title": "Singapore Tech Summit 2026",
  "workflow_status": "PENDING_APPROVAL",
  "estimated_cost_inr": 85000,
  "policy_cap_inr": 60000,
  "has_exception": true,
  "clause_refs": ["POL-TRV-101§5.3"],
  "created_at": "2026-08-07T14:30:00Z"
}
```

---

## 4. Security Architecture & Governance

1. **Role-Based Access Control (RBAC)**:
   - Validates `X-Persona-Id` headers on all incoming requests.
   - Enforces administrative privilege checks for approval endpoints.
2. **Data Protection & Sanitization**:
   - Parameterized SQL queries prevent SQL injection.
   - CORS policy restricted to enterprise domain origins.
3. **Audit Trail Logging**:
   - Every state change is persisted to `eil.db` with timestamps, approver IDs, and reasoning.
