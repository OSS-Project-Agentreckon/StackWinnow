# Headroom integration

**Package**: `headroom-ai`  
**Version**: `0.44.0`  
**License**: Apache-2.0 (reviewed)  
**Repository**: <https://github.com/headroomlabs-ai/headroom>  
**Category**: context compression  
**Implemented mode**: library

---

## What headroom-ai does

headroom-ai compresses tool outputs, logs, JSON, and chat history before each
LLM call.  Compression runs locally using NLP algorithms; no data is sent to
any external service and no model API key is required.  The `model` parameter
selects a tokenizer (via tiktoken) to count tokens against a specific context
window; it does not route requests to an LLM.

---

## Implemented mode: library

The StackWinnow adapter uses the Python library mode:

```python
from headroom import compress

result = compress(messages, model="gpt-4o")
print(result.messages)  # compressed message list
print(result.tokens_saved)  # integer (may be 0 for short inputs)
```

The adapter installs `headroom-ai` in an isolated Python virtualenv under
`.stackwinnow/envs/headroom/python/` and runs the compression in a subprocess
using the venv interpreter (`-I` mode to prevent path manipulation).

### Acceptance check

A fixed two-message fixture with known repetitive content is compressed on
every fresh run.  The step records `messages_in`, `messages_out`, and
`tokens_saved`.  Compression reducing tokens to zero is not asserted — the
acceptance check verifies that the library imported and ran without error, not
that the fixture exceeds a minimum compression ratio.

---

## Modes not implemented

| Mode | Description | Why not implemented here |
|------|-------------|--------------------------|
| **Proxy** | HTTP proxy between your code and an LLM API | Requires a running process and routing evidence from an active request |
| **Client-wrapper** | CLI wrapper that runs `claude`, `cursor`, etc. | Requires an active assistant session to verify routing |

Add a separate adapter step for either mode if live-routing evidence is
required.  Do not infer savings or connectivity from a running process.

---

## Prerequisites

- Python 3.11+ (the venv uses the interpreter running StackWinnow)
- pip or ensurepip (the adapter bootstraps pip via `ensurepip`)
- Internet access on first run — tiktoken downloads vocab files from Azure CDN
  and caches them in `<venv>/tiktoken-cache/`
- macOS arm64 (initial verified platform; Linux support can be added after
  independent testing)

---

## Managed paths

| Path | Purpose | Owned by |
|------|---------|----------|
| `.stackwinnow/envs/headroom/python/` | Isolated venv with headroom-ai and dependencies | StackWinnow |
| `.stackwinnow/envs/headroom/python/tiktoken-cache/` | Tokenizer vocab cache | StackWinnow |
| `.stackwinnow/headroom.lock` | Operation lock (removed after apply) | StackWinnow |

Removal is scoped to these paths.  External Python installations and project
source files are never modified.

---

## Running the integration check

```sh
pytest tests/integration/test_headroom.py --run-integration -v
```

The first run downloads tiktoken vocab files (~2 MB) and installs
`headroom-ai` and its dependencies (~150 MB) into the fixture project venv.
Subsequent runs reuse the installed venv and the tiktoken cache.

---

## Known limitations

- **Compression benefit is input-dependent**: a short fixture may show
  `tokens_saved = 0`; this does not indicate a failure.
- **litellm dependency**: `headroom-ai` depends on LiteLLM, a large package
  (~150 MB with its transitive dependencies).  The venv install may take
  several minutes on first run.
- **tiktoken network access**: The first compression call downloads tokenizer
  vocab files.  CI jobs without internet access will block at this point.
- **Platform**: Only macOS arm64 is verified in the initial adapter; support
  for Linux requires a separate testing pass.

---

## Real findings from initial integration

The following was recorded during acceptance testing on macOS arm64 with
Python 3.11 and headroom-ai 0.44.0:

- `compress(messages, model="gpt-4o")` completes locally without API keys.
- The two-message fixture (system + 41-line repetitive log) compressed
  successfully.  Token savings varied between 0 and ~15 depending on the
  algorithm selected.
- The tiktoken `cl100k_base` vocab file is downloaded on first call and cached;
  subsequent calls are fully offline.
- The venv install took approximately 90–180 seconds on a cold cache.
