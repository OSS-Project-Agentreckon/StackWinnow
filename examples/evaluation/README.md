# Project evaluation example

Use a disposable project directory with the installed `stackwinnow` command.
Read the [promptfoo integration gate and prerequisites](../../docs/integrations/promptfoo.md)
first: this branch requires the reviewed shared runner before normal apply can
execute. Planning and dry-run work without it.

```sh
mkdir "evaluation demo"
stackwinnow promptfoo plan "evaluation demo" --json > evaluation-plan.json
stackwinnow promptfoo apply evaluation-plan.json --dry-run --json
stackwinnow promptfoo apply evaluation-plan.json --json
```

On a supported build/environment, apply installs `promptfoo@0.125.1` in the
project's managed prefix, writes the owned configuration, and evaluates:

| Input | Expected output |
| --- | --- |
| `hello` | `HELLO` |
| `world` | `WORLD` |

The local JavaScript fixture makes no model calls. Expect `status: succeeded`,
two successes, zero failures/errors, and a result-file reference in the receipts.

```sh
stackwinnow promptfoo plan "evaluation demo" --scenario fail --json > negative-plan.json
stackwinnow promptfoo apply negative-plan.json --json
```

Expect CLI exit **1**, `status: failed`, and two assertion failures with upstream
process exit **100**. This verifies that the manager detects bad results. For a
fresh successful evaluation, create another default plan; the same owned install
and configuration are reused. Replaying an attempted plan is blocked.

The configuration references the provider bundled with your installed
StackWinnow package. Keep generated machine-specific plans and `.stackwinnow/`
local. The [optional OpenAI path](../../docs/integrations/promptfoo.md#optional-hosted-model-evaluation)
needs a separate opt-in and may incur charges. Local fixture success measures
the onboarding path, not LLM quality.
