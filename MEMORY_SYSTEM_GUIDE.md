# Couchbase Coding Memory - Quick Reference

## Status

This project now uses a Docker-free default path.

- Database: local or remote Couchbase Server
- Bootstrap command: `cb-memory init`
- Legacy alias: `cb-memory replicate` (deprecated, no Docker behavior)
- MCP server: `python -m cb_memory.server`

## Fast Path

```bash
pip install -e .
cp .env.example .env
cb-memory init
```

Optional convenience scripts:

```bash
./scripts/bootstrap_macos.sh
# or
./scripts/bootstrap_linux.sh
```

## What Gets Stored

- Conversations: sessions, messages, summaries
- Knowledge: decisions, bugs, thoughts, patterns
- Metadata: sync state

## MCP Tools

Retrieval:

```text
memory_context_for_request
memory_kv_semantic_search
memory_search
memory_recall_decision
memory_recall_bug
memory_list_sessions
memory_project_context
```

Capture:

```text
memory_save_decision
memory_save_bug
memory_save_pattern
memory_save_thought
```

## Couchbase Endpoints

- UI: `http://localhost:8091`
- Query service: `http://localhost:8093/query/service`

Example stats query:

```bash
curl -u Administrator:password -X POST \
  http://localhost:8093/query/service \
  -d 'statement=SELECT source, COUNT(*) AS cnt FROM `coding-memory`.conversations.sessions GROUP BY source'
```

## Troubleshooting

- Connection check: `curl -sf http://127.0.0.1:8091/pools`
- Ensure env values in `.env` are correct (`CB_CONNECTION_STRING`, `CB_USERNAME`, `CB_PASSWORD`, `CB_BUCKET`)
- Restart your MCP client after config changes
- Run schema setup directly: `cb-memory setup`

## Notes

- Historical Docker-specific instructions were removed from the active setup flow.
- For current onboarding, use `/Users/ruchit/Downloads/cb-retrival/README.md` and `/Users/ruchit/Downloads/cb-retrival/SETUP_GUIDE.md`.
