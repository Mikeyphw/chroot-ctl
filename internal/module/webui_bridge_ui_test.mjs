import assert from 'node:assert/strict';
import fs from 'node:fs';
const source=fs.readFileSync(new URL('./webroot/index.js',import.meta.url),'utf8');
for(const token of [
 "bridgeSelfTest",
 "async function bootstrapBackend()",
 "function renderBridgeFailure(e)",
 "WEBUI_BRIDGE_UNAVAILABLE",
 "KSU_EXEC_TIMEOUT",
 "KSU_ID_PROBE_FAILED",
 "KSU_BACKEND_PROBE_FAILED",
 "Retry connection",
 "bootstrapBackend();"
]) assert.ok(source.includes(token),`missing UI bridge state: ${token}`);
assert.ok(!source.includes("refreshBackendChip();loadCompatibility().then"),"legacy fire-and-forget bootstrap remains");
console.log("KernelSU bridge UI failure-state tests passed");
