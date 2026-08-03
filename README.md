<div align="center">
  <img src="doc/assets/mark.svg" width="80" alt="Me-as-a-Service mark">
  <h1>Me-as-a-Service</h1>
  <p><em>Because my résumé doesn’t answer follow-up questions.</em></p>
  <p>
    <a href="https://chat.danjia.me/"><img src="https://img.shields.io/website?url=https%3A%2F%2Fchat.danjia.me%2F&amp;up_message=online&amp;up_color=149477&amp;down_message=offline&amp;down_color=critical&amp;label=live%20instance" alt="Live instance status"></a>
    <a href="https://github.com/danjia21/me-as-a-service/actions/workflows/ci.yml"><img src="https://github.com/danjia21/me-as-a-service/actions/workflows/ci.yml/badge.svg?branch=main" alt="CI status"></a>
    <a href="LICENSE"><img src="https://img.shields.io/badge/license-Apache_2.0-4c566a" alt="Apache 2.0 license"></a>
    <img src="https://img.shields.io/badge/Next.js-16.2.10-000000?logo=nextdotjs" alt="Next.js 16.2.10">
    <img src="https://img.shields.io/badge/FastAPI-0.139.2-009688?logo=fastapi" alt="FastAPI 0.139.2">
  </p>
</div>

Me-as-a-Service is a human-like, evidence-grounded conversational AI
representation that lets visitors explore a person’s professional experience
through a natural, multi-turn interview. It speaks in a first-person
conversational style, remembers context within the current session, and uses a
curated knowledge base to support personal claims. Evidence provenance remains
server-side for evaluation and debugging.

Retrieval is one capability inside the chatbot, not the entire product. The
assistant can handle greetings, clarification, and contextual follow-ups, but
it is deliberately not a general-purpose expert-answer service. It redirects
substantive questions unrelated to the represented person instead of browsing
the web for an answer. For public contextual facts directly connected to
documented experience, it can perform one bounded web search after curated
retrieval is insufficient; cited URLs are exposed as clickable links.

> [!IMPORTANT]
> The assistant represents a person; it is not the person. Never add private or
> sensitive material to the public knowledge base.

## Repository layout

```text
apps/
  api/                 FastAPI API and retrieval domain
  web/                 Next.js web application
examples/
  fictional-profile/   Default instance and public test fixture
.agents/skills/        Reusable knowledge workflows
deploy/                Provider-neutral deployment assets
infra/aws/             Optional AWS infrastructure automation
scripts/aws-host/      Idempotent Ubuntu host operations
doc/                   Product and engineering documentation
```

An instance bundles `instance.yaml`, approved Markdown under `knowledge/`, and
optional `inputs/`, `workspace/`, and `evaluations/` directories. Select one
instance for the API, web app, evaluator, and containers with
`MAAS_INSTANCE_DIR`. Only `knowledge/` enters runtime retrieval.

Runtime ingestion indexes coherent Markdown sections in an in-memory Tantivy
index. Résumé roles and education entries remain complete records, while
publication bibliography entries remain separate. Approved personal accounts
use `Interview question`, `Approved account`, and `Evidence boundaries`
sections: the question is a retrieval-only hint, and the approved account and
its boundaries are returned together as evidence.

Files under `inputs/` and `workspace/` are curation material and never enter
runtime retrieval. In particular, research ledgers under
`workspace/research/*.yaml` may contain candidates, inferences, limitations,
and review state. Reviewed material must first be converted into curated
Markdown with explicit provenance under `knowledge/public/`.

## Quick start

Prerequisites: Node.js 24, pnpm 11, Python 3.12+,
[uv](https://docs.astral.sh/uv/), and Docker.

```bash
cp .env.example .env
pnpm install
uv sync --project apps/api --all-groups
docker compose up -d postgres
pnpm dev
```

The web app runs at <http://localhost:3000>, the API at
<http://localhost:8000>, and API documentation at <http://localhost:8000/docs>.
`pnpm dev` starts both applications; they can also be run independently with
`pnpm dev:web` and `pnpm dev:api`. The root `.env` file is optional; without
one, set `OPENAI_API_KEY` in the process environment. OpenAI is the only hosted
model provider; `MAAS_CONVERSATION_STORE=memory` keeps local persistence
database-free.

The sample configuration persists session-scoped conversations in PostgreSQL
for 24 hours. The complete session remains stored, while only the six newest
complete turns are supplied as model context. A separate `daily_model_usage`
table stores only atomic per-day token totals. Optional execution traces and
ranked evidence provenance are exported to LangSmith, not stored in the
application database. Set `MAAS_CONVERSATION_STORE=memory` when running without
Docker. PostgreSQL tables are initialized on API startup, and expired
conversations are removed on subsequent startups.

The sample configuration limits each conversation to 20 completed turns,
hosted generation to 300 output tokens per turn, and generation usage to
100,000 tokens per UTC day. Configure these with
`MAAS_MAX_TURNS_PER_CONVERSATION`, `MAAS_MAX_OUTPUT_TOKENS`, and
`MAAS_DAILY_TOKEN_BUDGET`. These application limits complement rather than
replace a provider-side monthly hard spend limit.

The API also defaults to 30 requests per IP and 12 requests per conversation
per 60 seconds. It runs at most four chat turns concurrently, queues up to
eight more for 15 seconds, and rejects excess work with a retryable response.
The corresponding `MAAS_IP_RATE_LIMIT_REQUESTS`,
`MAAS_SESSION_RATE_LIMIT_REQUESTS`, `MAAS_RATE_LIMIT_WINDOW_SECONDS`,
`MAAS_MAX_CONCURRENT_TURNS`, `MAAS_MAX_QUEUED_TURNS`, and
`MAAS_QUEUE_TIMEOUT_SECONDS` settings are documented in `.env.example`.

The `/api/v1/chat` endpoint uses one native OpenAI client for multi-turn
streaming, contextual query rewriting, the structured evidence-sufficiency
decision, and bounded public-context web search. Provide `OPENAI_API_KEY`;
`MAAS_LLM_MODEL` defaults to the reviewed
`gpt-5.4-mini-2026-03-17` snapshot and can override it. The semantic
judge rejects evidence that is merely related to the question, including
practical project rationale presented as personal motivation. This happens
before response streaming, so accepted answers still stream normally. Visitors
never provide model credentials; if the judge fails, the request safely falls
back to an insufficient-evidence response.

Production prompts are version-controlled files under
`apps/api/src/me_as_a_service/prompts`. Their content hash is attached to
traces; the request path never downloads prompts from LangSmith.

LangSmith tracing is disabled by default. Set `LANGSMITH_TRACING=true`,
`LANGSMITH_API_KEY`, and optionally `LANGSMITH_PROJECT`, `LANGSMITH_ENDPOINT`,
or `LANGSMITH_WORKSPACE_ID` to export complete nested traces. A trace contains
visitor messages, system prompts, generated answers, and retrieved evidence.
LangSmith is outbound-only: readiness does not query it, and trace transport
failures do not fail chat turns.

## Useful commands

```bash
pnpm check          # frontend lint/type-check + backend lint/type-check/tests
pnpm test           # all tests
pnpm eval:routing   # optional live turn-analysis evaluation (requires OpenAI)
pnpm format         # format supported files
docker compose down
```

## Optional turn-analysis evaluation

Personal evaluation questions are not distributed with a public release. If
you want to measure turn-analysis behavior, use
[`$evaluation-question-bootstrap`](.agents/skills/evaluation-question-bootstrap/SKILL.md)
to create `<instance>/evaluations/questions.yaml` from your own curated public
knowledge. Review the generated evidence expectations before treating them as
test cases, then run:

```bash
pnpm eval:routing --output routing-baseline.json
```

The command uses the production structured analysis and sufficiency calls, so
it requires `OPENAI_API_KEY` and incurs model usage. Evaluation is optional;
the application does not require this personal fixture at runtime.

If common interview questions require facts split across several résumé
passages, or an approved professional contact link is buried in a broader
résumé passage, use
[`$generate-resume-bridges`](.agents/skills/generate-resume-bridges/SKILL.md)
to create compact, résumé-derived aggregate or targeted documents without
changing runtime retrieval limits.

## Configuration

Configuration is read from environment variables prefixed with `MAAS_`. See
[`.env.example`](.env.example) for local defaults. Secrets belong in `.env`,
which is ignored by Git; safe defaults belong in `.env.example`.

## Production traffic controls and monitoring

Set the same high-entropy `MAAS_PROXY_SHARED_SECRET` in the Next.js and FastAPI
services. The web route uses it to authenticate the visitor address it forwards
to the API. Keep FastAPI private behind that proxy, and configure the public
CDN or reverse proxy to replace untrusted forwarding headers.

Rate-limit keys are process-local keyed hashes. Raw client addresses are not
stored. The approximate daily chat-client count is also process-local, resets
on restart and at midnight UTC, and is intended for aggregate traffic
monitoring, not visitor recognition.

FastAPI exposes Prometheus-compatible aggregate metrics at `/metrics`,
including:

- HTTP request counts, statuses, active requests, and duration histograms
- Completed, failed, cancelled, rate-limited, budget-limited, and
  queue-saturated chat outcomes
- Conversations created and approximate daily visitors
- Active and queued chat turns
- Completed generation tokens today and the configured daily budget

Set `MAAS_METRICS_BEARER_TOKEN` or its `_FILE` variant in production, scrape
the endpoint with `Authorization: Bearer <token>`, and alert on downtime,
elevated 5xx or failed chat rates, queue saturation, rate-limit spikes, and
daily token usage nearing the configured budget.

These controls are intentionally in-memory for the initial single-process
deployment. A multi-worker or multi-instance deployment must replace them with
a shared rate-limit and concurrency backend before it can enforce global
limits.

The repository includes a vendor-neutral single-VPS deployment with non-root
production images, Traefik TLS and edge controls, optional provisioned
Prometheus/Grafana/Alertmanager monitoring, privacy-safe structured logs, and
encrypted S3-compatible PostgreSQL backups. See the
[production runbook](doc/PRODUCTION_DEPLOYMENT.md) and
[threat model](doc/THREAT_MODEL.md). Optional AWS infrastructure lives under
[`infra/aws`](infra/aws/README.md), and guarded host operations live under
[`scripts/aws-host`](scripts/aws-host/). Production secrets and Alertmanager
receiver credentials remain outside Git.

The public/private release boundary is documented in the
[disclosure policy](doc/DISCLOSURE_POLICY.md). Unclassified paths are private
by default.

## Project status

The grounded text MVP includes streaming conversation, deterministic routing,
lexical retrieval, and an evaluation harness. See the
[architecture](doc/ARCHITECTURE.md) and
[contributing guide](CONTRIBUTING.md).

## License

Apache-2.0. See [LICENSE](LICENSE).
