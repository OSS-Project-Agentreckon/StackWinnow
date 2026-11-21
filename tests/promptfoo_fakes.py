"""Shared offline command double; never invokes npm, Node, or a hosted provider."""

import json
from dataclasses import dataclass
from pathlib import Path

from stackwinnow.adapters import promptfoo as adapter


@dataclass
class CommandResult:
    returncode: int = 0
    stdout: str = ""
    stderr: str = ""
    timed_out: bool = False

    @property
    def succeeded(self) -> bool:
        return self.returncode == 0 and not self.timed_out


class FakeCommands:
    def __init__(self) -> None:
        self.calls: list[tuple[list[str], Path, dict[str, str]]] = []
        self.install_exit = 0
        self.node_version = "v24.13.1\n"
        self.tool_version = adapter.VERSION
        self.report_change = lambda report: report
        self.eval_exit: int | None = None
        self.timed_out = False

    def __call__(self, args, *, cwd, timeout, extra_env=None):
        assert isinstance(args, list) and timeout > 0
        self.calls.append((args, Path(cwd), dict(extra_env or {})))
        if args == ["/declared/node", "--version"]:
            return CommandResult(stdout=self.node_version)
        if args[1] == "install":
            assert args[-1] == "promptfoo@0.125.1"
            assert {"--save-exact", "--ignore-scripts", "--no-audit", "--no-fund"} <= set(args)
            if self.install_exit:
                return CommandResult(self.install_exit, stderr="synthetic install failure")
            prefix = Path(args[args.index("--prefix") + 1])
            package = prefix / "node_modules/promptfoo"
            (package / "dist/src").mkdir(parents=True)
            (package / "dist/src/entrypoint.js").write_text("// offline test double\n")
            (package / "package.json").write_text(
                json.dumps({"name": "promptfoo", "version": adapter.VERSION, "license": "MIT"})
            )
            (prefix / "node_modules/.package-lock.json").write_text(
                json.dumps(
                    {
                        "packages": {
                            "node_modules/promptfoo": {
                                "version": adapter.VERSION,
                                "integrity": adapter.INTEGRITY,
                            }
                        }
                    }
                )
            )
            return CommandResult()
        assert args[1].endswith("/promptfoo/dist/src/entrypoint.js")
        if args[-1] == "--version":
            return CommandResult(stdout=self.tool_version + "\n")
        assert args[2] == "eval"
        config = json.loads(Path(args[args.index("--config") + 1]).read_text())
        assert [case["vars"]["input"] for case in config["tests"]] == ["hello", "world"]
        failed = "stackwinnowFail=true" in args
        report = {
            "results": {
                "version": 3,
                "stats": {
                    "successes": 0 if failed else 2,
                    "failures": 2 if failed else 0,
                    "errors": 0,
                },
                "results": [
                    {
                        "testIdx": index,
                        "success": not failed,
                        "response": {
                            "output": "INTENTIONAL MISMATCH" if failed else output,
                        },
                    }
                    for index, output in enumerate(["HELLO", "WORLD"])
                ],
            }
        }
        output = Path(args[args.index("--output") + 1])
        output.write_text(json.dumps(self.report_change(report)))
        code = self.eval_exit if self.eval_exit is not None else (100 if failed else 0)
        return CommandResult(code, timed_out=self.timed_out)

    def count(self, operation: str) -> int:
        return sum(operation in args for args, _, _ in self.calls)
