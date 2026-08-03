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

## Quick start

Prerequisites: Node.js 24, pnpm 11, Python 3.12+,
[uv](https://docs.astral.sh/uv/), Docker, and an API key from OpenAI or
OpenRouter.

```bash
cp .env.example .env
pnpm install
uv sync --project apps/api --all-groups
docker compose up -d postgres
pnpm dev
```

Add your provider credentials to `.env`. OpenAI is the default:

```dotenv
MAAS_LLM_PROVIDER=openai
OPENAI_API_KEY=your-key
```

To use OpenRouter instead, select it and use an OpenRouter model ID:

```dotenv
MAAS_LLM_PROVIDER=openrouter
MAAS_LLM_MODEL=deepseek/deepseek-v4-flash
OPENROUTER_API_KEY=your-key
```

The web app runs at <http://localhost:3000> and the API at
<http://localhost:8000>. See [`.env.example`](.env.example) for the available
local configuration.

## Create your own profile

The repository includes several agent skills for building a custom knowledge
base for the conversational AI. Start by putting a Markdown copy of your résumé
at `instances/<your-name>/knowledge/resume.md`. Review it first and remove any
private or sensitive information. Copy
[`examples/fictional-profile/instance.yaml`](examples/fictional-profile/instance.yaml)
into the same directory and replace the example profile details with your own.

Once the résumé is in place, use these skills for your instance:

- [`$bootstrap-personal-knowledge`](.agents/skills/bootstrap-personal-knowledge/SKILL.md)
  asks interview-style questions based on your résumé and turns your answers
  into knowledge documents. Building a detailed knowledge base can take several
  sessions, so voice input may be more comfortable than typing.
- [`$bootstrap-public-knowledge`](.agents/skills/bootstrap-public-knowledge/SKILL.md)
  finds public sources connected to your work and records them in a research
  ledger.
- [`$curate-public-knowledge`](.agents/skills/curate-public-knowledge/SKILL.md)
  lets you review the research ledger and turns accepted material into
  knowledge documents.
- [`$generate-resume-bridges`](.agents/skills/generate-resume-bridges/SKILL.md)
  creates compact résumé-based summaries that improve retrieval when an
  answer draws on information from several sections.

Once you are happy with the knowledge base, set
`MAAS_INSTANCE_DIR=instances/<your-name>` in `.env` and run `pnpm dev`.
Enable LangSmith tracing to inspect and tune retrieval performance.

To deploy your instance, We recommend a VPS with at least 2 GB of RAM.
You will need a domain name, an OpenAI or OpenRouter API key, and
production secrets kept outside Git. See the
[AWS Lightsail deployment guide](doc/DEPLOYMENT_LIGHTSAIL.md) for an example deployment.

## Contribution

Contributions are welcome. See [CONTRIBUTING.md](CONTRIBUTING.md) for the
development workflow and contribution guidelines.

## License

Apache-2.0. See [LICENSE](LICENSE).
