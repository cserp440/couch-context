# Memory Tools Fix Summary

## Problem Identified
The memory tools were **NOT working** because:
1. MCP server was configured to run on the host (`python3.11 -m cb_memory.server`)
2. Connection string pointed to Docker internal IP (`172.17.0.3`)
3. On macOS, Docker bridge network IPs are **not accessible from the host**
4. Result: MCP server couldn't connect → no memory tools available

## Solution Applied

### 1. Built Docker Image ✅
Created `Dockerfile` and built the `cb-memory-mcp` image that runs the MCP server inside Docker where it can access the Couchbase container.

### 2. Updated MCP Configuration ✅
Changed `~/.claude/settings.json` to use the startup script:
```json
{
  "command": "/Users/ruchit/.claude/bin/coding-memory-mcp.sh"
}
```

This script:
- Runs the MCP server **inside Docker** on the bridge network
- Can access Couchbase at `172.17.0.3` (container-to-container)
- Auto-imports Claude Code and Codex sessions on startup
- Streams MCP protocol via stdin/stdout to Claude Code

### 3. Verified Connection ✅
Tested that the Docker container can:
- ✅ Connect to Couchbase at `172.17.0.3`
- ✅ Access the `coding-memory` bucket
- ✅ Query data (30 sessions found)

## Current Status

### Database
- **Container**: `couchbase-memory-local` (running)
- **Sessions stored**: 30 (24 Codex + 5 Claude Code + 1 new)
- **Connection**: Working from within Docker bridge network

### MCP Server
- **Image**: `cb-memory-mcp:latest` (built)
- **Startup script**: `/Users/ruchit/.claude/bin/coding-memory-mcp.sh`
- **Network**: Docker bridge (can access 172.17.0.3)
- **Auto-import**: Enabled for Claude Code and Codex

## How to Verify It's Working

### After Restarting Claude Code:

1. **Check MCP tools are available**:
   - Ask: "What memory tools do you have?"
   - Should see: `memory_search`, `memory_context_for_request`, etc.

2. **Test retrieval**:
   ```
   Search memory for "couchbase setup"
   ```
   Should find sessions about the database setup.

3. **Test context**:
   ```
   What have we worked on in this project?
   ```
   Should call `memory_project_context` and list past sessions.

4. **Verify auto-import**:
   - Work on something in this session
   - Restart Claude Code
   - Should auto-import this session (30 → 31+ sessions)

## Files Created/Modified

### Created:
- ✅ `/Users/ruchit/Downloads/cb-retrival/Dockerfile`
- ✅ `/Users/ruchit/Downloads/cb-retrival/FIX_SUMMARY.md` (this file)

### Modified:
- ✅ `~/.claude/settings.json` - Updated MCP server command
- ✅ `.claude/settings.local.json` - Added Docker permissions
- ✅ `.env` - Fixed connection string to `couchbase://172.17.0.3`

## Technical Details

### Why Docker?
- Couchbase container is on Docker bridge network (172.17.0.3)
- macOS doesn't route traffic to Docker bridge IPs from host
- Only way to access container IP is from **another container** on same network
- MCP server runs in Docker → can access Couchbase container directly

### Architecture:
```
Claude Code (host)
    ↓ stdio
Shell Script (host)
    ↓ docker run
MCP Server (Docker container, bridge network)
    ↓ couchbase://172.17.0.3
Couchbase (Docker container, bridge network)
```

### Network Flow:
1. Claude Code launches `/Users/ruchit/.claude/bin/coding-memory-mcp.sh`
2. Script runs `docker run cb-memory-mcp` on bridge network
3. MCP server connects to Couchbase at `172.17.0.3` (same network)
4. MCP protocol flows over stdio back to Claude Code

## Next Steps

1. **Restart Claude Code** to load the new MCP configuration
2. **Test the memory tools** using the verification steps above
3. **Start using memory automatically** - Claude will call memory tools per CLAUDE.md instructions

## Troubleshooting

### If memory tools still don't appear:
```bash
# Check Docker image exists
docker images | grep cb-memory-mcp

# Test manual connection
docker run --rm --network bridge \
  -e CB_CONNECTION_STRING=couchbase://172.17.0.3 \
  -e CB_USERNAME=Administrator \
  -e CB_PASSWORD=password \
  -e CB_BUCKET=coding-memory \
  cb-memory-mcp -c "from cb_memory.db import CouchbaseClient; ..."
```

### If imports don't work:
```bash
# Check paths in the startup script
cat /Users/ruchit/.claude/bin/coding-memory-mcp.sh
```

## Success Criteria

✅ Docker image built: `cb-memory-mcp:latest`
✅ Connection tested from Docker container
✅ Settings updated to use startup script
⏳ **RESTART CLAUDE CODE** to activate
⏳ Verify memory tools are available
⏳ Test memory search and context retrieval

**Status**: Ready for testing after Claude Code restart! 🚀
