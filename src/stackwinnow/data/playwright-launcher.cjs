// Keep Playwright's Unix socket path short even when a project path is long.
// No credentials or personal browser profile are loaded by this launcher.
const fs = require('node:fs');
const path = require('node:path');
const allowed = new Set(['PATH', 'HOME', 'TMPDIR', 'TMP', 'TEMP', 'LANG', 'LC_ALL', 'PLAYWRIGHT_BROWSERS_PATH', 'CI']);
for (const key of Object.keys(process.env)) {
  if (!allowed.has(key)) delete process.env[key];
}
const sockets = fs.mkdtempSync('/tmp/stackwinnow-pw-');
fs.chmodSync(sockets, 0o700);
process.env.PWTEST_SOCKETS_DIR = sockets;
process.on('exit', () => fs.rmSync(sockets, { recursive: true, force: true }));
const entrypoint = process.argv[2];
process.argv.splice(1, 1);
require(path.resolve(entrypoint));
