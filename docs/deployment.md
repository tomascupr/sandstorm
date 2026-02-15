# Deployment Guide

Sandstorm is a stateless FastAPI app. Each request creates an independent E2B sandbox, runs the agent, and tears it down. No shared state, no sticky sessions, no coordination between requests. This means deploying for concurrent agent runs is trivial -- just add workers.

## Production Server

For development or simple deployments, use the built-in server:

```bash
ds serve --host 0.0.0.0 --port 8000
```

For production with multiple workers, use [Gunicorn](https://gunicorn.org/) with uvicorn workers. Each worker handles multiple concurrent requests via async I/O:

```bash
pip install gunicorn
gunicorn sandstorm.main:app \
  --worker-class uvicorn.workers.UvicornWorker \
  --workers 4 \
  --bind 0.0.0.0:8000 \
  --timeout 600
```

Set `--workers` based on your machine (2x CPU cores is a reasonable starting point). Set `--timeout` higher than your longest expected agent run.

## Running Many Agents Concurrently

Fire as many requests as you want. Each one gets its own sandbox:

```python
import asyncio
import httpx
from httpx_sse import aconnect_sse


async def run_agent(client: httpx.AsyncClient, prompt: str):
    async with aconnect_sse(
        client, "POST", "http://localhost:8000/query",
        json={"prompt": prompt},
    ) as events:
        async for sse in events.aiter_sse():
            print(sse.data)


async def main():
    prompts = [
        "Scrape the top 50 YC companies and save as CSV",
        "Analyze Python dependency security for requests==2.31.0",
        "Fetch today's arxiv papers on LLM agents and write a summary",
        "Build a SQLite DB of US national parks from NPS.gov",
    ]
    async with httpx.AsyncClient(timeout=600) as client:
        await asyncio.gather(*[run_agent(client, p) for p in prompts])

asyncio.run(main())
```

All four agents run simultaneously in isolated sandboxes. They can't see each other. When one finishes, its VM is destroyed -- the others keep running.

## Scaling

The Sandstorm server does almost no work itself -- it just proxies between your client and E2B. The real compute happens in E2B's cloud VMs. This means:

- **Horizontal scaling** -- run multiple Sandstorm instances behind a load balancer. No shared state to worry about.
- **Bottleneck is E2B** -- your concurrent sandbox limit depends on your [E2B plan](https://e2b.dev/pricing). The free tier allows a handful; paid plans scale higher.
- **CPU/memory on the server is minimal** -- each request holds an open SSE connection and streams stdout. A single 2-core machine can comfortably handle dozens of concurrent agents.
