# Claude Memory Workflow

**CRITICAL**: Use cb-memory tools proactively during EVERY conversation. Memory retrieval is NOT optional - it's required before answering implementation, debugging, or architecture questions.

## Mandatory Memory Retrieval

**ALWAYS retrieve memory BEFORE answering when user asks about:**
- Past work, decisions, or implementations
- Debugging issues (check if similar bugs were fixed before)
- How to implement something (check past patterns and approaches)
- Project setup or configuration (check past sessions)
- Architecture decisions (check decision history)
- Code patterns or best practices used in this project
- Any "how do I" or "what's the best way" questions
- Questions about errors or failures
- Requests to build, modify, or extend existing code

## Step 1: Retrieve Context (REQUIRED)

**Before answering ANY technical question**, call `memory_context_for_request`:

```
memory_context_for_request(
  query: <user's request verbatim>,
  project_id: <current workspace absolute path or "default">,
  include_messages: true,
  limit: 12,
  per_type_limit: 6,
  message_limit: 20
)
```

**When to use cross-project search:**
- Only if user explicitly mentions multiple projects
- Use `related_project_ids: ["/path/to/project1", "/path/to/project2"]`
- Or use `include_all_projects: true` if user says "across all projects" or "global search"

## Step 2: Fallback Search (if context is sparse)

If `memory_context_for_request` returns <5 relevant items, immediately call:

```
memory_kv_semantic_search(
  terms: [<extracted keywords from query>],
  project_id: <current workspace path>,
  limit: 20,
  per_collection_limit: 10
)
```

## Step 3: Use Retrieved Context

- **Reference specific past sessions/decisions in your answer**
- Mention: "Based on previous work in session X..." or "We previously decided to..."
- If no relevant context found, state: "No past history found for this - proceeding with best practices"

## Saving Important Information (REQUIRED)

**After completing significant work, ALWAYS save to memory:**

### Save Architectural Decisions
When making important technical choices, call:
```
memory_save_decision(
  title: <short decision title>,
  description: <detailed explanation>,
  category: <"architecture"|"library-choice"|"api-design"|"database"|"deployment">,
  context: <why this decision was made>,
  alternatives: [<other options considered>],
  consequences: [<implications of this choice>],
  project_id: <current workspace path>
)
```

### Save Bug Fixes
After fixing bugs, call:
```
memory_save_bug(
  title: <bug description>,
  description: <what was wrong>,
  root_cause: <underlying issue>,
  fix_description: <how it was fixed>,
  files_affected: [<files modified>],
  error_messages: [<error messages if any>],
  severity: <"low"|"medium"|"high"|"critical">,
  project_id: <current workspace path>
)
```

### Save Code Patterns
When creating reusable patterns, call:
```
memory_save_pattern(
  title: <pattern name>,
  description: <what it does>,
  code_example: <example code>,
  use_cases: [<when to use this>],
  language: <programming language>,
  project_id: <current workspace path>
)
```

### Save Thoughts
For important observations or notes, call:
```
memory_save_thought(
  content: <the observation or note>,
  category: <"observation"|"idea"|"concern"|"todo">,
  related_files: [<relevant files>],
  project_id: <current workspace path>
)
```

## When to Save (Checklist)

Save memory AFTER:
- ✅ Making any architectural decision
- ✅ Choosing libraries or frameworks
- ✅ Fixing bugs (especially tricky ones)
- ✅ Creating reusable code patterns
- ✅ Discovering important project insights
- ✅ Setting up configuration or infrastructure
- ✅ Solving complex problems
- ✅ Writing significant new features

## Example Workflow

**User asks:** "How do I set up authentication in this project?"

1. **First** → Call `memory_context_for_request(query="How do I set up authentication in this project?")`
2. **Check results** → Found previous auth implementation in session X
3. **Answer** → "Based on previous work in session X, we're using JWT with passport.js..."
4. **After implementing** → Call `memory_save_decision()` to record the auth approach

**User asks:** "Fix this bug: TypeError in login handler"

1. **First** → Call `memory_context_for_request(query="TypeError in login handler")`
2. **Check results** → Found similar bug fixed in session Y
3. **Answer** → "We encountered this before - the issue is null check order..."
4. **After fixing** → Call `memory_save_bug()` to record the fix

## Summary

🔴 **MANDATORY**: Call `memory_context_for_request` BEFORE answering technical questions
🟡 **RECOMMENDED**: Use `memory_kv_semantic_search` as fallback
🟢 **REQUIRED**: Save decisions, bugs, and patterns after significant work

Memory tools are NOT optional - they ensure continuity across sessions and prevent solving the same problems multiple times.
