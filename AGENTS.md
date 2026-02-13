# AGENTS.md

## Default Memory Retrieval Workflow (Codex)

When working in this repository, do the following for each new chat after the first substantive user request:

1. Call MCP tool `memory_context_for_request` once before proposing edits or conclusions.
2. Use arguments:
   - `query`: the user's latest request verbatim (or minimally cleaned)
   - `project_id`: current workspace absolute path (fallback `default` only when unknown)
   - `related_project_ids`: include only when user explicitly requests cross-project context
   - `include_all_projects`: `true` only when user explicitly asks for global memory across projects
   - `include_messages`: `true`
   - `limit`: `12`
   - `per_type_limit`: `6`
   - `message_limit`: `20`
3. If returned context is sparse (few/no relevant items), call MCP tool `memory_kv_semantic_search` before asking clarifying questions.
4. Use fallback arguments:
   - `terms`: extracted keywords from the user request
   - `project_id`: current workspace absolute path (fallback `default` only when unknown)
   - `limit`: `20`
   - `per_collection_limit`: `10`
5. Build a "rich context" summary from the tool output focused on:
   - directly relevant past decisions
   - similar bugs/fixes
   - related sessions/messages
   - reusable patterns
6. Keep the synthesized context to a maximum of `2000` tokens equivalent.
   - Practical cap: keep it concise (about 1200-1500 words max).
   - Prioritize high-signal items and drop weak matches.
7. Use this context to guide solution choices and tradeoffs for the current request.
8. Show the user a compact "context reasoning" section (2-5 bullets):
   - effective project id used
   - project scope (`project`/`cross-project`/`all`) and selected project IDs
   - sources in context (codex/claude-code/opencode)
   - why top items were selected
   - what is missing (if anything)

## Scope Rules

- Apply this workflow to coding/implementation/debugging requests.
- Skip for pure chit-chat or requests that do not benefit from project memory.
- If the MCP tool is unavailable, continue normally and state that memory retrieval was unavailable.
