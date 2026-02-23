# Memory Tools Migration Summary

## Status

This file records the migration from a Docker-dependent runtime to a Docker-free default setup.

## Current Direction

- Use local or remote Couchbase directly via `CB_CONNECTION_STRING`
- Bootstrap with `cb-memory init`
- Run MCP server directly with `python -m cb_memory.server`
- Keep `cb-memory replicate` as a deprecated alias during transition

## Why This Changed

- Docker bridge networking introduced avoidable runtime coupling.
- Local-contained setup lowers startup friction and external dependency surface.
- Current docs and CLI now default to non-Docker workflow.

## Active Verification Steps

```bash
cb-memory init --help
cb-memory replicate --help
python -m cb_memory.server
curl -sf http://127.0.0.1:8091/pools
```

## Source of Truth

- `/Users/ruchit/Downloads/cb-retrival/README.md`
- `/Users/ruchit/Downloads/cb-retrival/SETUP_GUIDE.md`
- `/Users/ruchit/Downloads/cb-retrival/src/cb_memory/cli/main.py`
