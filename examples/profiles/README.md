# Portable profile example

A portable profile records reproducible project selections — goals, assistant,
model preference, and chosen tools with catalog-derived compatibility — without
any machine-specific state. Read [profiles](../../docs/profiles.md) for the full
schema and limits. Export and import run offline, install nothing, and never
write to the inspected project.

Export the current project's selections to a shareable file:

```sh
mkdir "evaluation demo"
cd "evaluation demo" && npm pkg set devDependencies.promptfoo=0.125.1 && cd ..
stackwinnow profiles export "evaluation demo" \
    --goal "Evaluate answers" \
    --tool promptfoo \
    --assistant codex \
    --model-preference local \
    --platform macos \
    --json > profile.json
```

The result is a schema-versioned artifact like
[`example-profile.json`](example-profile.json). It contains the selected tools
and declared intent only. It deliberately omits the project path, observed
dependency facts, evidence, diagnostics, and any configuration values, so it is
safe to commit or share.

Re-plan the same selections in a different project:

```sh
mkdir "second project"
stackwinnow profiles import profile.json "second project" --json
```

Import re-inspects the target project with the profile's goals, assistant, model
preference, and selected tools, then prints recommendations in the same shape as
`stackwinnow recommend`. Add `--platform` to override the profile's recorded
target. Exit **0** means the re-inspection completed (including no-match
results); **1** means it was incomplete; **2** means the profile or a selection
was invalid.

A profile referencing a tool that is absent from the current catalog, a wrong
`schema_version`, or malformed JSON fails clearly with exit **2** and changes
nothing. Importing a profile does not install or configure anything; follow it
with the relevant adapter commands (for example
[promptfoo](../../docs/integrations/promptfoo.md)) to act on the selections.
