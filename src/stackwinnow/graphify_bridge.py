"""Manager-owned stdio MCP bridge over Graphify's real local query commands."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from stackwinnow.adapters.graphify import (
    GRAPH_PATH,
    GraphifyError,
    RelationshipExpectation,
    _root,
    check_relationship,
    relationship_query,
)
from stackwinnow.adapters.graphify_index import PROVENANCE_PATH, inspect_graphify_index
from stackwinnow.adapters.graphify_plan import ENV_PATH, _digest, _json, _read_at
from stackwinnow.runner import run_command
from stackwinnow.state.lock import ProjectLockError, project_lock

TOOL = "query_relationship"
MAX_MESSAGE_BYTES = 64 * 1024
PROTOCOLS = ("2024-11-05", "2025-03-26", "2025-06-18")
TOOL_SCHEMA = {
    "name": TOOL,
    "description": "Check an exact directed calls relationship in the current owned code graph.",
    "inputSchema": {
        "type": "object",
        "properties": {
            key: {"type": "string", "minLength": 1, "maxLength": 4096}
            for key in ("caller_file", "caller_label", "callee_file", "callee_label")
        },
        "required": ["caller_file", "caller_label", "callee_file", "callee_label"],
        "additionalProperties": False,
    },
    "annotations": {"readOnlyHint": True, "destructiveHint": False, "openWorldHint": False},
}


def query_relationship(root: Path, python: str, arguments: dict, *, runner=run_command) -> dict:
    """Validate and query under our own lock; callers must not hold that lock."""
    if not isinstance(arguments, dict) or any(
        not isinstance(v, str) or len(v) > 4096 for v in arguments.values()
    ):
        raise GraphifyError("Supply four bounded relationship strings.")
    expected = RelationshipExpectation.model_validate(arguments)
    root = _root(root)
    if python != str(root / ENV_PATH / "bin/python"):
        raise GraphifyError("The bridge requires the project's managed Graphify interpreter.")
    with project_lock(root):
        provenance, _ = inspect_graphify_index(root)
        graph = _json(_read_at(root, GRAPH_PATH))
        check = check_relationship(graph, expected)
        if check.status != "succeeded":
            raise GraphifyError("The requested directed relationship is absent or ambiguous.")
        command = relationship_query(root, python, check)
        argv = list(command.argv)
        argv.insert(1, "-B")
        result = runner(
            argv, cwd=command.cwd, timeout=command.timeout_seconds, extra_env=command.environment
        )
        current, _ = inspect_graphify_index(root)
        if not result.succeeded or current != provenance:
            raise GraphifyError("Graphify query failed or its reviewed inputs changed.")
        return {
            "relationship_found": True,
            "expectation": expected.model_dump(mode="json"),
            "source_node_id": check.source_node_id,
            "target_node_id": check.target_node_id,
            "graph_sha256": provenance.graph_sha256,
            "provenance_sha256": _digest(_read_at(root, PROVENANCE_PATH)),
            "query_returncode": result.returncode,
        }


def serve(root: Path, python: str, input_stream, output_stream, *, query=None) -> int:
    """Serve a bounded MCP subset; unsupported methods get JSON-RPC errors."""
    initialized = False

    def write(value):
        output_stream.write(json.dumps(value, allow_nan=False, separators=(",", ":")) + "\n")
        output_stream.flush()

    def error(identifier, code, message):
        write({"jsonrpc": "2.0", "id": identifier, "error": {"code": code, "message": message}})

    while raw := input_stream.readline(MAX_MESSAGE_BYTES + 1):
        if len(raw) > MAX_MESSAGE_BYTES:
            error(None, -32600, "MCP message exceeds 64 KiB.")
            return 2
        try:
            request = _json(raw if isinstance(raw, bytes) else raw.encode())
        except (ValueError, UnicodeError, RecursionError):
            error(None, -32700, "Invalid JSON.")
            continue
        if not isinstance(request, dict):
            error(None, -32600, "Expected one JSON-RPC object.")
            continue
        identifier = request.get("id")
        if (
            request.get("jsonrpc") != "2.0"
            or not isinstance(request.get("method"), str)
            or ("id" in request and type(identifier) not in (str, int))
        ):
            error(None, -32600, "Invalid JSON-RPC request.")
            continue
        method = request["method"]
        params = request.get("params", {})
        if "id" not in request:
            continue
        if not isinstance(params, dict):
            error(identifier, -32602, "Expected object parameters.")
            continue
        if method == "initialize":
            protocol = params.get("protocolVersion")
            if protocol not in PROTOCOLS:
                protocol = PROTOCOLS[-1]
            initialized = True
            result = {
                "protocolVersion": protocol,
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": "stackwinnow-graphify", "version": "1"},
            }
        elif method == "ping":
            result = {}
        elif not initialized:
            error(identifier, -32000, "Initialize the MCP session first.")
            continue
        elif method == "tools/list":
            result = {"tools": [TOOL_SCHEMA]}
        elif method == "tools/call":
            if params.get("name") != TOOL or set(params) - {"name", "arguments", "_meta"}:
                error(identifier, -32602, "Unknown tool or parameters.")
                continue
            try:
                value = (query or query_relationship)(root, python, params.get("arguments"))
                result = {
                    "content": [{"type": "text", "text": json.dumps(value)}],
                    "isError": False,
                }
            except (OSError, ValueError, RuntimeError, ProjectLockError):
                result = {
                    "content": [
                        {
                            "type": "text",
                            "text": "Graphify relationship check failed; inspect current inputs and ownership.",
                        }
                    ],
                    "isError": True,
                }
        else:
            error(identifier, -32601, "Method not supported.")
            continue
        write({"jsonrpc": "2.0", "id": identifier, "result": result})
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="StackWinnow's local Graphify MCP bridge.")
    parser.add_argument("--project", required=True)
    parser.add_argument("--python", required=True)
    args = parser.parse_args(argv)
    return serve(Path(args.project), args.python, sys.stdin.buffer, sys.stdout)


if __name__ == "__main__":
    raise SystemExit(main())
