import assert from 'node:assert/strict';

let activeQueries = 0;
let maxActiveQueries = 0;
const queryCommands = [];
const capabilityEnvelope = JSON.stringify({
  protocolVersion: 1,
  requestId: 'capabilities',
  ok: true,
  data: {
    protocolVersion: 1,
    backendVersion: '0.11.0',
    arbitraryShell: false,
    transport: ['kernelsu'],
    operations: [{name: 'debug.timeline', mode: 'query'}],
  },
  error: null,
});

globalThis.ksu = {
  exec(command, _options, callbackName) {
    if (command.includes("'/system/bin/id'")) {
      queueMicrotask(() => globalThis[callbackName](0, 'uid=0(root)\n', ''));
      return;
    }
    if (command.includes("'version'")) {
      queueMicrotask(() => globalThis[callbackName](0, 'chrootctl 0.11.0\n', ''));
      return;
    }
    if (command.includes("'app' 'capabilities'")) {
      queueMicrotask(() => globalThis[callbackName](0, capabilityEnvelope, ''));
      return;
    }
    if (command.includes("'app' 'query'")) {
      queryCommands.push(command);
      activeQueries += 1;
      maxActiveQueries = Math.max(maxActiveQueries, activeQueries);
      const response = JSON.stringify({
        protocolVersion: 1,
        requestId: 'query',
        ok: true,
        data: {count: 0, events: [], limit: 1, schemaVersion: 2},
        error: null,
      });
      setTimeout(() => {
        activeQueries -= 1;
        globalThis[callbackName](0, response, '');
      }, 15);
      return;
    }
    queueMicrotask(() => globalThis[callbackName](127, '', 'unexpected command'));
  },
  moduleInfo() { return '{"id":"chrootctl-magisk"}'; },
};

const bridge = await import('./webroot/chrootctl.js?post-cux-transport');
await Promise.all([
  bridge.debugTimeline(1),
  bridge.debugTimeline(1),
  bridge.debugTimeline(1),
]);

assert.equal(maxActiveQueries, 1, 'KernelSU typed query RPCs must be serialized');
assert.equal(queryCommands.length, 3);
for (const command of queryCommands) {
  assert.ok(command.startsWith("'/data/adb/modules/chrootctl-magisk/system/bin/chrootctl' "), 'typed queries must reuse the self-tested executable');
}
console.log('Post-CUX KernelSU serialized typed-query transport tests passed');

// Standalone HTTP must preserve operation/backend/raw-response provenance when a
// typed endpoint returns malformed JSON. This is the same detail surfaced by
// System -> Diagnostics instead of the old global "Bridge returned invalid JSON" toast.
delete globalThis.ksu;
globalThis.window = {
  location: {
    protocol: 'http:',
    hostname: '127.0.0.1',
    origin: 'http://127.0.0.1:8765',
  },
};
globalThis.document = {cookie: ''};
const response = (text, status = 200) => ({
  status,
  ok: status >= 200 && status < 300,
  async text() { return text; },
});
globalThis.fetch = async (url) => {
  const path = new URL(String(url)).pathname;
  if (path === '/api/v1/health') return response(JSON.stringify({ok: true}));
  if (path === '/api/v1/capabilities') {
    return response(JSON.stringify({
      protocolVersion: 1,
      requestId: 'capabilities-http',
      ok: true,
      data: {
        protocolVersion: 1,
        backendVersion: '0.11.0',
        arbitraryShell: false,
        transport: ['standalone-http'],
        operations: [{name: 'release.readiness', mode: 'query'}],
      },
      error: null,
    }));
  }
  if (path === '/api/v1/query/release.readiness') return response('not-json-from-release-readiness');
  return response(JSON.stringify({error: {code: 'NOT_FOUND', message: 'not found'}}), 404);
};

const standalone = await import('./webroot/chrootctl.js?post-cux-standalone-error');
await assert.rejects(
  standalone.releaseReadiness(),
  (error) => {
    assert.equal(error.code, 'WEBUI_INVALID_JSON');
    assert.equal(error.operation, 'release.readiness');
    assert.equal(error.command, 'standalone-http');
    assert.match(error.stdout, /not-json-from-release-readiness/);
    return true;
  },
);
console.log('Post-CUX standalone typed-query error provenance tests passed');
