# Third-party software and attribution

StackWinnow's manager code is MIT licensed; retain [LICENSE](LICENSE) and its
existing contributor attribution. Small JavaScript/HTML fixtures are original
manager assets. Catalog entries and lock metadata do not bundle upstream software.
The wheel contains the manager and its declared resources. The source archive also
includes reference license metadata and selected verbatim notices.

Supported integrations download separate upstream packages into managed environments.
Python dependencies, Node, Codex, browsers and native libraries retain their own
licenses; StackWinnow's MIT license does not relicense those downloads.

| Observed release | Artifact license scope |
| --- | --- |
| [Graphify / graphifyy 0.9.114](https://pypi.org/project/graphifyy/0.9.114/) | Apache-2.0; release NOTICE and LICENSE-MIT preserve historical MIT contributions |
| [Headroom 0.44.0](https://pypi.org/project/headroom-ai/0.44.0/) | Apache-2.0; retain its NOTICE and asset/optional dependency qualifications |
| [promptfoo 0.125.1](https://www.npmjs.com/package/promptfoo/v/0.125.1) | MIT in the inspected npm artifact |
| [Playwright MCP 0.0.86](https://www.npmjs.com/package/@playwright/mcp/v/0.0.86) | Apache-2.0; Playwright and browser notices are separate |
| [Codex 0.169.0](https://github.com/openai/codex/tree/rust-v0.169.0) | Apache-2.0 source; launcher omitted LICENSE; native binary dependency audit is incomplete |
| [Node 24.13.1](https://nodejs.org/dist/v24.13.1/) | MIT plus its bundled dependency terms |

The [versioned reference inventory](licenses/reference-2026-11-23/README.md)
contains 809 historical records (739 installed), hashes and source references.
Selected manager-dependency and direct-tool license/notice texts are preserved
verbatim there. This is evidence for those artifacts, not a complete redistribution
clearance or a license inventory of a fresh final installation.

Significant qualifications from that review:

- Chromium headless shell 159.0.8154.6/revision 1255 includes LGPL-2.1/MPL-2.0
  components. sharp-libvips 1.3.4 includes LGPL-3.0-or-later/MPL-1.1 components;
  Apache-2.0 on its packaging repository does not cover all bundled binaries.
- MCP filesystem 2026.8.31 omits the referenced LICENSE. Exact release source
  identifies Apache-2.0 for new/relicensed code and MIT for historical contributions;
  source documentation has CC-BY-4.0 terms.
- tree-sitter-groovy 0.1.2 declares MIT but no notice text was found in the wheel,
  source distribution or release tree. This notice gap remains open.
- tokenizers 0.23.3 omits a wheel license; its exact-version source distribution
  contains Apache-2.0 text. Supplemental source evidence is not an installed notice.
- certifi includes MPL-2.0 data; tqdm has MPL-2.0 and MIT scopes; NumPy's binary
  notices include multiple licenses. LiteLLM's inspected wheel has MIT scope outside
  enterprise code; no enterprise directory was observed in that specific install.
- Observed manager dependencies: pydantic/pydantic-core/annotated-types/typing-inspection
  MIT, typing-extensions PSF-2.0, packaging Apache-2.0 OR BSD-2-Clause. They are
  installed separately by pip, not vendored into the manager archives.

A preinstalled bundle/container would need its own review and applicable notices,
source/relinking provisions and other obligations. This manager-only release does
not establish that downstream native/runtime redistribution is ready.
