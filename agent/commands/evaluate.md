---
description: "Evaluate whether a repo, local folder, article, or design note has anything worth adopting into ExecuteC2."
allowed-tools: Read, Bash, WebFetch, WebSearch, TodoWrite
---

# Evaluate

Investigate and evaluate whether the provided GitHub repo, local folder, article, design note, or spec contains anything worth adopting into ExecuteC2.

The goal is not generic praise. The goal is to identify concrete additions, patterns, fixes, or testing ideas that fit ExecuteC2's real architecture and operating constraints.

## Usage

```text
/evaluate <github_repo_url | local_folder_path | article_url> [additional targets...] [optional notes / focus area]
```

Examples:

```text
/evaluate https://github.com/example/python-c2-server
/evaluate /tmp/agent-prototype focus on transport reliability and task result handling
/evaluate "/tmp/red team notes" focus on listener plugin ideas
/evaluate https://blog.example.com/async-websocket-patterns prioritize operator sync improvements
/evaluate https://github.com/acme/c2-ui https://github.com/acme/agent-transport-notes compare ideas for agent tasking, check-in, and websocket sync
```

## Workflow

1. Parse `$ARGUMENTS`:
   - Build an ordered list of one or more `targets`.
   - If the input begins with a quoted string, treat the full quoted value as the first target candidate.
   - Continue consuming consecutive target-like values until the next token is clearly not a URL and not an existing local path.
   - Treat the remaining text as `evaluation_notes`.
   - For each target:
     - If it starts with `http://`, `https://`, or `github.com`, treat it as a URL target.
     - If the URL is a GitHub repository page, treat it as `target_repo_url`.
     - If the URL is an article, blog post, documentation page, or published spec, treat it as `target_article_url`.
     - Otherwise treat it as `local_folder_path`.
   - For local paths with spaces, require quoting.
2. Determine the target type before analysis:
   - For each target: `GitHub repo`, `Local folder / repo`, or `Article / spec / write-up`
   - If more than one target is supplied, also treat the run as a `Multi-target comparison`
3. Read current ExecuteC2 context first so recommendations are grounded in repo reality:
   - Start with `AGENTS.md`, `README.md`, and `pyproject.toml`
   - Then inspect the most relevant core modules:
     - `src/executec2/server/app.py`
     - `src/executec2/server/teamserver.py`
     - `src/executec2/server/database.py`
     - `src/executec2/server/broker.py`
     - `src/executec2/server/events.py`
     - `src/executec2/server/routes/`
     - `src/executec2/listeners/http_listener.py`
     - `src/executec2/agents/python_agent.py`
     - `src/executec2/commands/registry.py`
     - `src/executec2/commands/builtin/__init__.py`
     - `agent/main.py`, `agent/connector_http.py`, and `agent/crypto.py` when transport or payload ideas are relevant
   - Read tests that match the area being evaluated so you can judge test impact and coverage gaps.
4. Validate the target before analysis:
   - If any `local_folder_path` does not exist, is unreadable, or is clearly not a directory/repo-like folder, report the error and stop.
   - If any GitHub URL is not actually a repository page, report the error and stop.
   - If any article/spec URL cannot be fetched or read, report the error and stop.
   - Do not continue with partial analysis after a target-access failure.
5. For each `GitHub repo` or `Local folder / repo` target:
   - Inspect the high-signal files first: `README*`, `pyproject.toml`, `requirements*.txt`, `package.json`, `Dockerfile*`, `docker-compose*.yml`, entrypoints, `src/`, `agent/`, tests, changelog/release notes, protocol specs, and architecture docs.
   - Extract only concrete candidate additions such as:
     - listener or agent plugin patterns
     - task dispatch and result relay improvements
     - agent transport or crypto hardening ideas
     - operator API or WebSocket sync improvements
     - database, state model, or lifecycle handling refinements
     - testing strategies, fixtures, or protocol validation patterns
     - safe operator UX improvements for authorized team operations
   - Compare each candidate against ExecuteC2 before recommending it.
   - If you use a temporary clone for inspection, clean it up after analysis.
6. For each `Article / spec / write-up` target:
   - Read the source first.
   - Extract concrete implementation ideas only: protocol patterns, async design choices, state sync patterns, plugin interfaces, testing strategies, reliability controls, or operator workflow improvements.
   - Distinguish clearly between:
     - proven implementation details
     - conceptual ideas that still need design and validation
7. Evaluate every candidate against ExecuteC2's actual constraints:
   - Python 3.12 project using FastAPI, asyncio, aiosqlite, msgpack, Pydantic v2, structlog, and cryptography
   - Fully async design; avoid blocking I/O on the event loop
   - SQLite persistence and current teamserver state management
   - Listener and agent plugins loaded via `importlib`
   - Current built-in Python agent command model:
     - command registry in `src/executec2/commands/registry.py`
     - built-in command registration in `src/executec2/commands/builtin/__init__.py`
     - task payload building in `src/executec2/agents/python_agent.py`
     - agent-side execution in `agent/main.py`
   - Existing encrypted HTTP listener flow using AES-GCM, HKDF, msgpack, and per-agent session keys
   - Existing REST routes plus WebSocket synchronization through the message broker
   - Authorization-sensitive nature of the project:
     - keep recommendations scoped to legitimate red team operations
     - do not recommend features that weaken operator auth, credential handling, encryption, or safety boundaries
8. Always ask whether a recommendation is implementation-ready for this repo:
   - Which files or subsystems would change
   - Whether protocol compatibility would break
   - Whether new tests are required
   - Whether the change is small and incremental or a larger redesign
9. Prefer the smallest set of changes that materially improves ExecuteC2.
10. Reject vague praise. Only recommend additions that are specific enough to implement, prototype, or test.
11. If the evidence is weak or incomplete:
   - lower confidence explicitly
   - say what is missing
   - prefer `Consider later` or `Skip` over overstating value

## Output Format

Render exactly these five sections:

## 1. Executive verdict

State whether the target is worth mining for additions:
- `Yes, adopt now`
- `Yes, adapt selectively`
- `No meaningful addition`

Include one short paragraph explaining the decision in ExecuteC2 terms.

## 2. Ranked beneficial additions

If there are beneficial additions, render one markdown table with these columns in this order:

- `Rank`
- `Candidate`
- `Adopt type`
- `Why it matters`
- `Expected impact on ExecuteC2`
- `Integration fit`
- `Effort / test scope`
- `Risks / downsides`
- `Evidence`

If there are no meaningful additions, write `None`.

Use these adoption labels exactly in section 2:
- `Directly adopt`
- `Adapt conceptually`

Section 2 is for beneficial additions only. Do not place rejected ideas in this table. Rejected ideas belong only in section 5 under `Skip`.

When multiple targets were evaluated together:
- combine duplicates into one row
- use the `Evidence` column to name the supporting target(s)
- do not create separate rows for the same idea unless the implementations are materially different

## 3. Why it helps

For each non-skipped candidate, explain:
- what ExecuteC2 gap, weakness, or rough edge it addresses
- why this target is a strong source for that idea
- which ExecuteC2 subsystem would likely change
- what would improve in practice after adoption

Keep this tied to real repo constraints rather than generic benefits.

If section 2 is `None`, write `No meaningful additions identified.` and keep the section brief.

## 4. Expected impact

Summarize likely impact across these categories:
- teamserver architecture
- agent capability or transport
- operator/API workflow
- reliability and testing
- maintainability and security posture

Use `High`, `Medium`, or `Low` where helpful.

## 5. Highest-impact next steps

Render exactly three buckets:

### Add now

### Consider later

### Skip

Each bucket should contain concrete, short action items or candidate names.

If a candidate was rejected, list it only in `Skip` with a short reason.
If a bucket is empty, write `None`.

## Constraints

- Do not invent capabilities that are not present in the target.
- Do not recommend additions that conflict with ExecuteC2's async architecture, current tasking model, or encrypted agent transport unless you explicitly frame them as larger redesigns.
- Do not recommend features that would weaken operator authentication, credential handling, transport security, or safe authorized-use boundaries.
- Prefer reusable patterns over niche one-off ideas.
- If the target overlaps heavily with existing ExecuteC2 functionality, say so clearly and avoid padding the result.
- If the target is an article or design note, distinguish between proven implementation details and conceptual suggestions.
- If multiple targets are supplied, prefer a synthesized verdict over a file-by-file dump.
- If you used direct repo/folder inspection rather than a specialized analyzer, say so briefly in the response.
