"""Current Graphify local-index verification; Codex connection remains separate."""

from pathlib import Path

from stackwinnow.adapters._managed import record_for
from stackwinnow.adapters.graphify import GraphifyError, relationship_query
from stackwinnow.adapters.graphify_index import (
    PROVENANCE_PATH,
    GraphifyProvenance,
    inspect_graphify_index,
)
from stackwinnow.adapters.graphify_install import MANIFEST, validate_graphify_installation
from stackwinnow.adapters.graphify_plan import ENV_PATH, _digest, _json, _read_at
from stackwinnow.contracts import EvidenceRef, OperationStatus
from stackwinnow.installer import InstallerError, StepReceipt, _now, _persist, _record_step
from stackwinnow.runner import run_command
from stackwinnow.state.lock import ProjectLockError, project_lock
from stackwinnow.verify.models import CheckKind, CheckStatus, ToolVerification, VerificationCheck

VERIFY_STEP_ID = "graphify-verify-relationship"


def check_graphify(root: Path, options, *, command_runner=None) -> ToolVerification:
    checks = {
        kind: VerificationCheck(
            kind=kind,
            status=CheckStatus.BLOCKED,
            code="graphify-evidence-unavailable",
            message="Current Graphify evidence is unavailable.",
        )
        for kind in CheckKind
    }
    checks[CheckKind.CONNECTED] = VerificationCheck(
        kind=CheckKind.CONNECTED,
        status=CheckStatus.BLOCKED,
        code="graphify-client-pending",
        message="Standalone graph queries do not establish an actual Codex connection.",
    )

    def inspect():
        recipe = None
        try:
            proof = GraphifyProvenance.model_validate(_json(_read_at(root, PROVENANCE_PATH)))
            recipe = proof.plan.installation_plan
        except (OSError, ValueError, RuntimeError):
            pass
        _, digest = validate_graphify_installation(root, recipe)
        checks[CheckKind.INSTALLED] = VerificationCheck(
            kind=CheckKind.INSTALLED,
            status=CheckStatus.SUCCEEDED,
            code="graphify-inventory-current",
            message="Owned Graphify runtime matches its reviewed recipe and inventory.",
            evidence=(EvidenceRef(source=MANIFEST, detail=f"sha256:{digest}"),),
        )
        provenance, relationship = inspect_graphify_index(root)
        evidence = EvidenceRef(
            source=PROVENANCE_PATH, detail=f"sha256:{_digest(_read_at(root, PROVENANCE_PATH))}"
        )
        checks[CheckKind.CONFIGURED] = VerificationCheck(
            kind=CheckKind.CONFIGURED,
            status=CheckStatus.SUCCEEDED,
            code="graphify-index-current",
            message="Local index inputs and graph are current; this is not Codex configuration.",
            evidence=(evidence,),
        )
        return provenance, relationship, evidence

    try:
        if not options.run_functional:
            inspect()
            checks[CheckKind.FUNCTIONAL] = VerificationCheck(
                kind=CheckKind.FUNCTIONAL,
                status=CheckStatus.NOT_RUN,
                code="graphify-query-not-run",
                message="Request --run-functional to run a fresh upstream relationship query.",
            )
        else:
            with project_lock(str(root)):
                provenance, relationship, evidence = inspect()
                record = record_for(root)
                previous = record.receipt_for(VERIFY_STEP_ID)
                if previous and (
                    previous.tool_id != "graphify"
                    or previous.owned_paths
                    or previous.configuration_ownership
                    or previous.configuration_intents
                ):
                    raise GraphifyError("Graphify verification step has conflicting ownership.")
                receipt = StepReceipt(
                    step_id=VERIFY_STEP_ID,
                    tool_id="graphify",
                    status=OperationStatus.FAILED,
                    message="Graphify verification began but did not complete.",
                    timestamp=_now(),
                )
                _record_step(record, receipt)
                _persist(record, project_root=str(root))
                succeeded = False
                try:
                    command = relationship_query(root, root / ENV_PATH / "bin/python", relationship)
                    argv = list(command.argv)
                    argv.insert(1, "-B")
                    result = (command_runner or run_command)(
                        argv,
                        cwd=command.cwd,
                        timeout=command.timeout_seconds,
                        extra_env=command.environment,
                    )
                    current, _ = inspect_graphify_index(root)
                    succeeded = result.succeeded and current == provenance
                except (OSError, ValueError, RuntimeError):
                    pass
                status = CheckStatus.SUCCEEDED if succeeded else CheckStatus.FAILED
                message = (
                    "Fresh Graphify relationship query passed."
                    if succeeded
                    else "Fresh Graphify relationship query failed; current functionality was not established."
                )
                receipt = receipt.model_copy(
                    update={
                        "status": OperationStatus.SUCCEEDED
                        if succeeded
                        else OperationStatus.FAILED,
                        "message": message,
                        "evidence": [evidence] if succeeded else [],
                    }
                )
                _record_step(record, receipt)
                _persist(record, project_root=str(root))
                checks[CheckKind.FUNCTIONAL] = VerificationCheck(
                    kind=CheckKind.FUNCTIONAL,
                    status=status,
                    code="graphify-query-result",
                    message=message,
                    evidence=(evidence,) if succeeded else (),
                )
    except (OSError, ValueError, RuntimeError, InstallerError, ProjectLockError):
        pass
    return ToolVerification(
        tool_id="graphify", connection_scope="assistant", checks=tuple(checks.values())
    )
