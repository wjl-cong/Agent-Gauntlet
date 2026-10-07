# AgentGauntlet

#### Description

AgentGauntlet is a red-team evaluation platform for LLM-based agents. Built around fault injection, adversarial attacks, and verdict scoring, it automates the evaluation of business agents across three dimensions: functional correctness, fault resilience, and adversarial defense. The default system under test is Yanshao, a forest fire risk business agent.

Key features:

- **Trajectory-driven verdicts**: five-level recovery verdicts (with recovery rate) and four-level defense verdicts (with defense score), all based on deterministic rules over execution trajectories — no generative model involved in judging, fully unit-testable and reproducible
- **Controlled fault injection**: declarative policy files configure service-exception and timeout faults with probability-based or nth-call triggering; injected exceptions are isomorphic to real faults so the target cannot distinguish evaluation traffic
- **Attack payload library**: three direct-injection families (role play, instruction override, goal hijacking) and two indirect-injection channels (knowledge-base honeypots, tool-return smuggling); every payload carries a globally unique canary string for leakage detection and evidence attribution
- **Input-echo false-positive elimination**: canary count comparison with whitespace normalization prevents template fallback answers from being misjudged as successful attacks
- **Single execution core**: the CLI, the REST service, and a four-phase streaming evaluation agent all reuse the same execution engine, guaranteeing consistent verdict semantics
- **Four-page web console**: agent evaluation chat (four-phase live streaming) / test center (11 task cards) / test history (verdict distributions and per-case evidence) / API test planning (three-tier coverage analysis)

Real-world evaluation results (2026-10-03, two-round comparison: initial test → hardening → retest): in the fault-injection round, all 6 actually injected cases achieved honest degradation with a 100% recovery rate; the initial attack round exposed 7 compromises, including a full system prompt leakage (LEAKED_PROMPT) as the most critical finding, with a defense score of 41.7%; after the target deployed four prompt anti-injection clauses and the platform fixed 8 verdict/execution defects, the retest showed zero prompt leakage (1 → 0), the knowledge-base honeypot channel improved from 0 testable cases to 3/3 defended, all 20 attack cases completed valid verdicts, and the defense score rose to 52.6%; an output-side deterministic guard has been developed and is expected to convert all remaining compromises into successful defenses.

#### Software Architecture

```
┌─────────────────────────────────────────────────────────────┐
│  Frontend (Vue3 + Element Plus, port 5174)                  │
│  Agent chat / Test center / Test history / API planning     │
└──────────────────────┬──────────────────────────────────────┘
                       │ REST / SSE (/api/v1/*)
┌──────────────────────▼──────────────────────────────────────┐
│  Backend presentation service (FastAPI, port 8100)          │
├─────────────────────────────────────────────────────────────┤
│  GauntletAgent (four-phase streaming orchestration)         │
├─────────────────────────────────────────────────────────────┤
│  Evaluation engine (runner + judge + attacks + chaos)       │
├─────────────────────────────────────────────────────────────┤
│  Target adapter (login / task creation / SSE capture / HITL)│
└───────────┬─────────────────────────────────┬───────────────┘
            │ HTTP / SSE                      │ SQL
┌───────────▼───────────┐      ┌──────────────▼──────────────┐
│  Target agent (:8000) │      │  PostgreSQL (gauntlet schema)│
└───────────────────────┘      └─────────────────────────────┘
```

Tech stack:

- Backend: Python 3.11 / FastAPI / Pydantic / Typer / asyncpg / httpx
- Frontend: Vue 3 / Vue Router / Element Plus / Vite / marked + DOMPurify
- Data: PostgreSQL (evaluation data stored in an isolated `gauntlet` schema)
- LLM: Qwen series via OpenAI-compatible API (streaming intent analysis and conclusion generation)

```
agent-gauntlet/
├── Backend/
│   ├── src/gauntlet/
│   │   ├── runner/        # evaluation engine (concurrency / budget cutoff / fault isolation)
│   │   ├── judge/         # recovery judge (five levels)
│   │   ├── attacks/       # payload library / defense judge / honeypot manager
│   │   ├── chaos/         # fault injection engine and policy loading
│   │   ├── targets/       # target adapter (login / SSE capture / approval resume)
│   │   ├── agent/         # four-phase streaming evaluation agent
│   │   ├── api/           # FastAPI service (REST + SSE)
│   │   ├── registry.py    # evaluation task registry (11 tasks)
│   │   └── config.py / models.py / db.py / cli.py
│   ├── suites/            # case suites (8 functional + 20 attack cases)
│   ├── faults/            # fault policies (baseline / tool smuggling)
│   └── tests/             # pytest suite
├── Frontend/
│   └── src/views/         # chat / test center / history / API plan pages
└── docs/                  # design docs, progress records, thesis diagrams
```

#### Installation

1. Requirements: Python 3.11, Node.js 18+, PostgreSQL 14+; the target agent must be deployed separately.

2. Backend installation and configuration

```bash
cd Backend
pip install -e .
cp .env.example .env
```

Edit `Backend/.env` with the key environment variables:

```ini
GAUNTLET_DSN=postgresql://postgres:postgres@localhost:5432/fire_agent
GAUNTLET_YANSHAO_BASE_URL=http://127.0.0.1:8000
GAUNTLET_YANSHAO_USER=evaluation-account
GAUNTLET_YANSHAO_PASSWORD=evaluation-password
GAUNTLET_TOKEN_BUDGET=2000000
GAUNTLET_JUDGE_MODEL=qwen-max
GAUNTLET_LLM_API_KEY=your-llm-api-key
GAUNTLET_LLM_MODEL=qwen3.7-flash
```

The isolated database schema (gauntlet) is created automatically on first run.

3. Frontend installation

```bash
cd Frontend
npm install
```

4. Start the services

```bash
# Backend (port 8100)
uvicorn gauntlet.api.main:app --host 0.0.0.0 --port 8100

# Frontend dev server (port 5174, proxies /api/v1 to the backend)
cd Frontend
npm run dev
```

#### Instructions

1. CLI evaluation

```bash
# W1 functional + fault-injection round
gauntlet run --faults faults/w1-baseline.yaml --label "w1-chaos"

# W2 adversarial round (honeypot seeding + attack suite; --delay staggering, --only partial rerun)
gauntlet run --suite suites/smoke-attacks.yaml --honeypot --label "w2-attack"

# Clean up honeypot documents after evaluation
gauntlet purge-honeypot
```

2. Web console: open `http://localhost:5174`

- **Agent chat**: launch evaluations in natural language with four-phase live streaming (intent analysis → test planning → autonomous execution → evaluation conclusion); chat history persisted locally
- **Test center**: 11 evaluation task cards with hover details, prerequisites, and one-click runs with live progress
- **Test history**: run list and detail drawers with verdict distributions, defense scores, and per-case evidence
- **API planning**: three-tier coverage analysis of the target's API inventory (direct / indirect / out of scope)

3. Run tests

```bash
cd Backend
pytest    # database-dependent cases are skipped automatically when PostgreSQL is unreachable
```

#### Contribution

1.  Fork the repository
2.  Create a Feat_xxx branch
3.  Commit your code
4.  Create a Pull Request
