"""Current Graphify runtime, owned configuration and actual client verification."""

import json
from pathlib import Path
from uuid import uuid4

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


def _check_local(root: Path, options, *, command_runner=None) -> ToolVerification:
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
            status=CheckStatus.BLOCKED,
            code="graphify-client-unconfigured",
            message="Local index is current; an owned Codex bridge registration is still required.",
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


def check_graphify(root: Path, options, *, command_runner=None) -> ToolVerification:
    from stackwinnow.adapters._managed import directories
    from stackwinnow.adapters.graphify_configure import (
        owned_graphify_configuration,
        registration_digest,
    )
    from stackwinnow.adapters.graphify_index import _publish
    from stackwinnow.adapters.graphify_install import graphify_server_settings
    from stackwinnow.configure.codex import RELATIVE_PATH
    from stackwinnow.verify.graphify_client import run_client_check

    try:
        ownership = owned_graphify_configuration(root)
    except (OSError, ValueError, RuntimeError, InstallerError):
        return _check_local(root, options, command_runner=command_runner)
    baseline = _check_local(root, options.model_copy(update={"run_functional": False}))
    checks = {c.kind: c for c in baseline.checks}
    if checks[CheckKind.FUNCTIONAL].status != CheckStatus.NOT_RUN:
        return baseline
    settings = graphify_server_settings(root)
    checks[CheckKind.CONFIGURED] = VerificationCheck(
        kind=CheckKind.CONFIGURED,
        status=CheckStatus.SUCCEEDED,
        code="graphify-owned-registration-current",
        message="The owned Codex bridge registration is current.",
        evidence=(
            EvidenceRef(
                source=RELATIVE_PATH, detail="registration-sha256:" + registration_digest(settings)
            ),
        ),
    )
    for kind in (CheckKind.CONNECTED, CheckKind.FUNCTIONAL):
        checks[kind] = VerificationCheck(
            kind=kind,
            status=CheckStatus.NOT_RUN,
            code="graphify-client-not-run",
            message="Request --run-functional for a fresh actual Codex tool call.",
        )
    if options.run_functional:
        try:
            with project_lock(root):
                provenance, relationship = inspect_graphify_index(root)
                if owned_graphify_configuration(root) != ownership:
                    raise GraphifyError("Configuration changed before verification.")
                proof_digest = _digest(_read_at(root, PROVENANCE_PATH))
                expected = {
                    "relationship_found": True,
                    "expectation": provenance.plan.expectation.model_dump(mode="json"),
                    "source_node_id": relationship.source_node_id,
                    "target_node_id": relationship.target_node_id,
                    "graph_sha256": provenance.graph_sha256,
                    "provenance_sha256": proof_digest,
                    "query_returncode": 0,
                }
                step_id = "graphify-client-" + uuid4().hex
                receipt = StepReceipt(
                    step_id=step_id,
                    tool_id="graphify",
                    status=OperationStatus.FAILED,
                    message="Graphify client check began but did not complete.",
                    timestamp=_now(),
                )
                record = record_for(root)
                _record_step(record, receipt)
                _persist(record, project_root=str(root))
            # The child bridge acquires the same lock for its query. Holding it
            # while waiting for Codex would deadlock. Recheck inputs afterward.
            try:
                result = run_client_check(
                    root,
                    settings,
                    expected,
                    runner=command_runner or run_command,
                    scenario=options.scenario,
                )
            except (OSError, ValueError, RuntimeError):
                result = {
                    "connected": False,
                    "functional": False,
                    "message": "The actual Codex check could not complete.",
                }
            with project_lock(root):
                record = record_for(root)
                if record.receipt_for(step_id) != receipt:
                    raise GraphifyError(
                        "Client verification intent changed; preserve state for inspection."
                    )
                current = False
                try:
                    current = (
                        inspect_graphify_index(root)[0] == provenance
                        and owned_graphify_configuration(root) == ownership
                        and _digest(_read_at(root, PROVENANCE_PATH)) == proof_digest
                    )
                except (OSError, ValueError, RuntimeError):
                    pass
                result["inputs_current"] = current
                result["functional"] = result.get("functional") is True and current
                relative = ".stackwinnow/graphify/checks/" + step_id + ".json"
                directories(root, ".stackwinnow/graphify/checks", create=True)
                raw = json.dumps(result, indent=2).encode()
                _publish(root, relative, raw)
                evidence = EvidenceRef(source=relative, detail="sha256:" + _digest(raw))
                succeeded = result["functional"] and result.get("connected") is True
                receipt = receipt.model_copy(
                    update={
                        "status": OperationStatus.SUCCEEDED
                        if succeeded
                        else OperationStatus.FAILED,
                        "message": "Actual Codex Graphify relationship check passed."
                        if succeeded
                        else "Actual Codex Graphify check failed; inspect evidence.",
                        "evidence": [evidence],
                    }
                )
                _record_step(record, receipt)
                _persist(record, project_root=str(root))
                for kind, key in (
                    (CheckKind.CONNECTED, "connected"),
                    (CheckKind.FUNCTIONAL, "functional"),
                ):
                    checks[kind] = VerificationCheck(
                        kind=kind,
                        status=CheckStatus.SUCCEEDED
                        if result.get(key) is True
                        else CheckStatus.FAILED,
                        code="graphify-client-" + key,
                        message=receipt.message,
                        evidence=(evidence,),
                    )
        except (OSError, ValueError, RuntimeError, InstallerError, ProjectLockError):
            for kind in (CheckKind.CONNECTED, CheckKind.FUNCTIONAL):
                checks[kind] = VerificationCheck(
                    kind=kind,
                    status=CheckStatus.BLOCKED,
                    code="graphify-client-state-changed",
                    message="Client verification could not safely record current evidence.",
                )
    return ToolVerification(
        tool_id="graphify", connection_scope="assistant", checks=tuple(checks.values())
    )
