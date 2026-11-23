"""Noninteractive workflow commands with explicit selection and review."""

import json

from stackwinnow.adapters.graphify_plan import load_relationship_expectation
from stackwinnow.supported import select_tool, supported_modes
from stackwinnow.verify import check_project
from stackwinnow.workflow import (
    WorkflowRequest,
    apply_workflow,
    explain_workflow,
    load_workflow_plan,
    plan_workflow,
)


def add_workflow_parser(commands):
    parser = commands.add_parser(
        "workflow",
        help="Inspect, select, review, apply and verify supported tools.",
        allow_abbrev=False,
    )
    actions = parser.add_subparsers(dest="workflow_command", required=True)
    modes = actions.add_parser(
        "modes", help="List executable modes and prerequisites.", allow_abbrev=False
    )
    modes.add_argument("--json", action="store_true")
    for action in ("inspect", "plan", "status", "check"):
        command = actions.add_parser(action, allow_abbrev=False)
        command.add_argument("project_root")
        command.add_argument("--json", action="store_true")
        if action != "inspect":
            command.add_argument(
                "--tool",
                action="append",
                required=True,
                help="Explicit supported tool ID; repeat for each selection.",
            )
        if action in ("inspect", "plan"):
            command.add_argument("--goal", action="append", default=[])
            command.add_argument(
                "--model-preference", choices=("local", "hosted", "any"), default="local"
            )
        if action == "plan":
            command.add_argument(
                "--expectation",
                help="Reviewed Graphify relationship JSON; required only with Graphify.",
            )
    apply = actions.add_parser("apply", allow_abbrev=False)
    apply.add_argument("plan_file")
    apply.add_argument("--dry-run", action="store_true")
    apply.add_argument("--json", action="store_true")


def workflow_command(args, parser) -> int:
    try:
        action = args.workflow_command
        code = 0
        if action == "modes":
            payload = {
                "schema_version": 1,
                "modes": [m.model_dump(mode="json") for m in supported_modes()],
            }
        elif action == "inspect":
            payload = explain_workflow(
                args.project_root, goals=args.goal, model_preference=args.model_preference
            )
        elif action == "plan":
            request = WorkflowRequest(
                selections=tuple(select_tool(name) for name in args.tool),
                goals=tuple(args.goal),
                model_preference=args.model_preference,
                expectation=load_relationship_expectation(args.expectation)
                if args.expectation
                else None,
            )
            plan = plan_workflow(args.project_root, request)
            payload = plan.model_dump(mode="json")
            if not args.json:
                print(f"Project: {plan.project_root}")
                print("Selected tools: " + ", ".join(plan.request.tool_ids))
                print("Order: " + " -> ".join(plan.phases))
                print(
                    "No installation or verification has run. Review --json output saved outside the project;"
                )
                print("then use 'workflow apply PLAN.json'. Cancel by leaving the plan unapplied.")
                print(
                    "All selected modes run locally without provider API usage. Downloads may be required."
                )
                print("Use 'remove plan PROJECT --tool ID --json' for reviewed removal.")
                return 0
        elif action == "apply":
            result = apply_workflow(load_workflow_plan(args.plan_file), dry_run=args.dry_run)
            payload = result.as_payload()
            code = 0 if result.dry_run or result.ready else 1
        else:
            # The registry check prevents a catalog-only selection being mistaken
            # for executable support, including during passive status.
            selected = [select_tool(name).tool_id for name in args.tool]
            report = check_project(
                args.project_root, tool_ids=selected, run_functional=action == "check"
            )
            payload = report.as_payload()
            code = 0 if report.ready else 1
        if args.json:
            print(json.dumps(payload, indent=2))
        else:
            _show(action, payload)
        return code
    except (OSError, ValueError, RuntimeError) as exc:
        parser.exit(2, f"error: {exc}\n")
        return 2


def _show(action, payload):
    if action == "modes":
        for mode in payload["modes"]:
            print(f"{mode['tool_id']} / {mode['mode']} @ {mode['version']}: {mode['description']}")
            print("  Requires: " + ", ".join(mode["requirements"]))
    elif action == "inspect":
        inspection = payload["inspection"]
        print("Project: " + inspection["profile"]["project_root"])
        # Explain the existing recommendation schema without hiding diagnostics.
        print(json.dumps(payload["recommendations"], indent=2))
        print(
            "Use 'workflow modes' for execution support, then explicitly select tools with 'workflow plan --tool ID'."
        )
    else:
        print(f"Project: {payload['project_root']}")
        print(f"Status: {payload['status']}; ready: {'yes' if payload['ready'] else 'no'}")
        for phase in payload.get("outcomes", []):
            print(f"  [{phase['status']}] {phase['phase']}: {phase['message']}")
        for tool in payload.get("tools", []):
            for check in tool["checks"]:
                print(
                    f"  {tool['tool_id']} [{check['status']}] {check['kind']}: {check['message']}"
                )
        if action == "status":
            print(
                "Passive status does not run functional checks; use 'workflow check' for fresh evidence."
            )
