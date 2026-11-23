"""Portable profile export and destination-specific review, with no implicit apply."""

from stackwinnow.profiles import export_profile, import_profile, load_profile
from stackwinnow.workflow import load_workflow_plan


def add_profile_parser(commands):
    parser = commands.add_parser(
        "profile",
        help="Export portable selections or plan them in another project.",
        allow_abbrev=False,
    )
    actions = parser.add_subparsers(dest="profile_command", required=True)
    exporting = actions.add_parser(
        "export", help="Export selections from a saved workflow plan.", allow_abbrev=False
    )
    exporting.add_argument("plan_file")
    exporting.add_argument("--json", action="store_true")
    importing = actions.add_parser(
        "import", help="Create a fresh destination workflow plan.", allow_abbrev=False
    )
    importing.add_argument("profile_file")
    importing.add_argument("project_root")
    importing.add_argument("--json", action="store_true")


def profile_command(args, parser) -> int:
    try:
        if args.profile_command == "export":
            profile = export_profile(load_workflow_plan(args.plan_file))
            if args.json:
                print(profile.model_dump_json(indent=2))
            else:
                print("Portable selections: " + ", ".join(s.tool_id for s in profile.selections))
                print(
                    "Use --json to save the profile. No project state or freeform goals are exported."
                )
        else:
            plan = import_profile(load_profile(args.profile_file), args.project_root)
            if args.json:
                print(plan.model_dump_json(indent=2))
            else:
                print("Destination: " + plan.project_root)
                print("Selected tools: " + ", ".join(plan.request.tool_ids))
                print("Order: " + " -> ".join(plan.phases))
                print(
                    "No installation or verification ran. Save --json output outside the project,"
                )
                print("review it, then explicitly run 'workflow apply PLAN.json'.")
                print("External prerequisite versions are checked at apply time.")
        return 0
    except (OSError, ValueError, RuntimeError) as exc:
        parser.exit(2, f"error: {exc}\n")
        return 2
