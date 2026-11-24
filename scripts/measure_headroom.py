"""Optional single-fixture token measurement; requires an existing Headroom runtime."""

import argparse
import hashlib
import importlib.metadata
import json
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "input", type=Path, help="Synthetic messages JSON from the evidence snapshot"
    )
    parser.add_argument("output", type=Path, help="New output directory; must not exist")
    parser.add_argument(
        "--tokenizer-cache", type=Path, required=True, help="Existing warm tiktoken cache"
    )
    args = parser.parse_args()
    raw = args.input.read_bytes()
    messages = json.loads(raw)
    if not isinstance(messages, list) or not all(isinstance(m, dict) for m in messages):
        parser.error("Input must be a list of message objects")
    if importlib.metadata.version("headroom-ai") != "0.44.0":
        parser.error("Use the existing Headroom 0.44.0 runtime interpreter")
    if not args.tokenizer_cache.is_dir():
        parser.error("A populated tokenizer cache is required; downloads are disabled")
    args.output.mkdir(parents=False, exist_ok=False)
    attempts: list[str] = []

    def audit(event, _args):
        if event in {"socket.connect", "socket.getaddrinfo", "socket.bind"}:
            attempts.append(event)
            raise RuntimeError("Network activity is disabled for this measurement")

    # Run in a dedicated process: audit hooks cannot be removed. Never call from
    # the manager. The Python hook is a guard, not an OS-level network sandbox.
    sys.addaudithook(audit)
    with tempfile.TemporaryDirectory(prefix="sw-measure-") as temporary:
        scratch = Path(temporary)
        cache = scratch / "tiktoken"
        shutil.copytree(args.tokenizer_cache, cache)
        os.environ.update(
            HOME=str(scratch),
            XDG_CACHE_HOME=str(scratch / "cache"),
            XDG_CONFIG_HOME=str(scratch / "config"),
            HF_HOME=str(scratch / "hf"),
            TIKTOKEN_CACHE_DIR=str(cache),
            HF_HUB_OFFLINE="1",
            TRANSFORMERS_OFFLINE="1",
            LITELLM_LOCAL_MODEL_COST_MAP="True",
            DO_NOT_TRACK="1",
        )
        from headroom import compress

        started = time.perf_counter()
        result = compress(messages, model="gpt-4o", kompress_model="disabled")
        elapsed = time.perf_counter() - started
        output = json.dumps(
            result.messages, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode()
        original = json.loads(raw)
        systems = [m for m in original if m.get("role") == "system"]
        failure = "FAIL test_timeout: AssertionError: expected 0.5s got 10.2s"
        failure_present = any(failure in str(m.get("content", "")) for m in original)
        preserved = all(m in result.messages for m in systems) and (
            not failure_present
            or any(failure in str(m.get("content", "")) for m in result.messages)
        )
        counts_consistent = (
            result.tokens_before - result.tokens_after == result.tokens_saved
            and 0 <= result.tokens_after <= result.tokens_before
        )
        report = {
            "scope": "Synthetic direct-library tokens, not cost or setup-time savings",
            "version": "0.44.0",
            "input_sha256": hashlib.sha256(raw).hexdigest(),
            "output_sha256": hashlib.sha256(output).hexdigest(),
            "tokens_before": result.tokens_before,
            "tokens_after": result.tokens_after,
            "tokens_saved": result.tokens_saved,
            "counts_consistent": counts_consistent,
            "protected_content_preserved": preserved,
            "network_attempts": attempts,
            "compression_elapsed_seconds": elapsed,
        }
        (args.output / "messages.json").write_bytes(output)
        (args.output / "measurement.json").write_text(json.dumps(report, indent=2) + "\n")
        return 0 if counts_consistent and preserved and not attempts else 1


if __name__ == "__main__":
    raise SystemExit(main())
