"""Current local Headroom inventory and explicitly requested fresh compression."""

from pathlib import Path
from uuid import uuid4

from stackwinnow.adapters import headroom_state as state
from stackwinnow.adapters.headroom import HeadroomError, run_headroom_compression
from stackwinnow.contracts import EvidenceRef, InstallPlan, OperationStatus, PlanStep
from stackwinnow.installer import InstallerError, execute_plan
from stackwinnow.runner import run_command
from stackwinnow.verify.models import CheckKind, CheckStatus, ToolVerification, VerificationCheck


def check_headroom(root: Path, options, *, command_runner=None) -> ToolVerification:
    checks = {
        kind: VerificationCheck(
            kind=kind,
            status=CheckStatus.BLOCKED,
            code="headroom-evidence-unavailable",
            message="Current Headroom installation evidence is unavailable.",
        )
        for kind in CheckKind
    }
    checks[CheckKind.CONNECTED] = VerificationCheck(
        kind=CheckKind.CONNECTED,
        status=CheckStatus.NOT_APPLICABLE,
        code="headroom-standalone-library",
        message="Local library mode has no assistant or provider connection.",
    )

    def inspect():
        current = state.inspect_installation(root)
        if current is None:
            raise HeadroomError("Headroom is not installed; apply a reviewed Headroom plan first.")
        evidence = (EvidenceRef(source=state.MANIFEST, detail="sha256:" + current[1]),)
        checks[CheckKind.INSTALLED] = VerificationCheck(
            kind=CheckKind.INSTALLED,
            status=CheckStatus.SUCCEEDED,
            code="headroom-inventory-current",
            message="Owned Headroom runtime matches its import health and file inventory.",
            evidence=evidence,
        )
        checks[CheckKind.CONFIGURED] = VerificationCheck(
            kind=CheckKind.CONFIGURED,
            status=CheckStatus.SUCCEEDED,
            code="headroom-library-recipe-current",
            message="Standalone library recipe uses the fixed fixture and gpt-4o/o200k_base tokenizer.",
            evidence=evidence,
        )
        return current

    try:
        baseline = inspect()
        checks[CheckKind.FUNCTIONAL] = VerificationCheck(
            kind=CheckKind.FUNCTIONAL,
            status=CheckStatus.NOT_RUN,
            code="headroom-compression-not-run",
            message="Request --run-functional for fresh measured compression; saved reports are historical.",
        )
        if options.run_functional:
            step_id = "headroom-" + uuid4().hex + "-verify"
            plan = InstallPlan(
                project_root=str(root),
                tool_ids=["headroom"],
                steps=[
                    PlanStep(
                        step_id=step_id,
                        tool_id="headroom",
                        description="Run fresh local compression verification.",
                    )
                ],
            )

            def revalidate():
                if inspect() != baseline:
                    raise HeadroomError("Headroom installation changed before verification.")

            _, results = execute_plan(
                plan,
                before_execute=revalidate,
                step_runner=lambda step: run_headroom_compression(
                    root, step.step_id, command_runner or run_command, scenario=options.scenario
                )[0],
            )
            result = results[0]
            checks[CheckKind.FUNCTIONAL] = VerificationCheck(
                kind=CheckKind.FUNCTIONAL,
                status=CheckStatus.SUCCEEDED
                if result.status == OperationStatus.SUCCEEDED
                else CheckStatus.FAILED,
                code="headroom-fresh-compression-result",
                message=result.message,
                evidence=tuple(result.evidence),
            )
    except (OSError, ValueError, RuntimeError, InstallerError):
        checks[CheckKind.FUNCTIONAL] = VerificationCheck(
            kind=CheckKind.FUNCTIONAL,
            status=CheckStatus.BLOCKED,
            code="headroom-state-unavailable",
            message="Current Headroom state could not be verified; inspect installation receipts and runtime.",
        )
    return ToolVerification(
        tool_id="headroom", connection_scope="standalone", checks=tuple(checks.values())
    )
