import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { spawn } from './webroot/kernelsu.js';

// exec-only managers must expose a non-zero child status as an exit, after
// forwarding stdout/stderr. A backend application failure is not a transport
// failure and must not be replayed against another executable candidate.
{
  globalThis.ksu = {
    exec(_command, _options, callbackName) {
      queueMicrotask(() => globalThis[callbackName](2, '{"type":"bridge_error","ok":false}\n', 'preview stale'));
    },
  };
  const child = spawn('/data/adb/modules/chrootctl/runtime/arm64-v8a/chrootctl', ['app', 'run'], {});
  let stdout = '';
  let stderr = '';
  let errors = 0;
  child.stdout.on('data', (chunk) => { stdout += String(chunk); });
  child.stderr.on('data', (chunk) => { stderr += String(chunk); });
  child.on('error', () => { errors += 1; });
  const code = await new Promise((resolve, reject) => {
    child.on('exit', resolve);
    setTimeout(() => reject(new Error('exec-fallback child did not exit')), 500);
  });
  assert.equal(code, 2);
  assert.equal(errors, 0);
  assert.match(stdout, /bridge_error/);
  assert.match(stderr, /preview stale/);
}

// The WebUI must pin the authoritative native runtime ELF, not the shell
// launcher, and preserve a structured pre-operation install failure instead of
// reducing it to the old INSTALL_FAILED fallback.
{
  let spawnCalls = 0;
  const active = '/data/adb/modules/chrootctl/runtime/arm64-v8a/chrootctl';
  const capabilities = JSON.stringify({
    protocolVersion: 1,
    requestId: 'capabilities',
    ok: true,
    data: {
      protocolVersion: 1,
      backendVersion: '0.11.0',
      arbitraryShell: false,
      transport: ['json', 'ndjson'],
      operations: [
        {name: 'install.run', mode: 'operation'},
        {name: 'operations.find_request', mode: 'query'},
        {name: 'operations.get', mode: 'query'},
      ],
    },
    error: null,
  });
  globalThis.ksu = {
    exec(command, _options, callbackName) {
      if (command.includes("'/system/bin/id'")) return queueMicrotask(() => globalThis[callbackName](0, 'uid=0(root)\n', ''));
      if (command.includes("'version'")) return queueMicrotask(() => globalThis[callbackName](0, 'chrootctl 0.11.0\n', ''));
      if (command.includes("'app' 'capabilities'")) return queueMicrotask(() => globalThis[callbackName](0, capabilities, ''));
      return queueMicrotask(() => globalThis[callbackName](127, '', 'unexpected exec'));
    },
    spawn(command, argsJson, _options, callbackName) {
      const args = JSON.parse(argsJson);
      assert.deepEqual(args, []);
      const child = globalThis[callbackName];
      if (command.includes("'app' 'query' '--request-json'") && command.includes('install.form')) {
        return queueMicrotask(() => {
          child.stdout.emit('data', JSON.stringify({protocolVersion:1,requestId:'webui-stream-probe',ok:true,data:{}}) + '\n');
          child.emit('exit', 0);
        });
      }
      spawnCalls += 1;
      assert.ok(command.startsWith(`'${active}' 'app' 'run' '--request-json' `));
      queueMicrotask(() => {
        child.stdout.emit('data', JSON.stringify({
          protocolVersion: 1,
          requestId: 'webui-run',
          type: 'bridge_error',
          operationId: '',
          ok: false,
          error: {code: 'PREVIEW_STALE', message: 'Resource state changed after preview; review again.'},
        }) + '\n');
        child.emit('exit', 2);
        queueMicrotask(() => {
          const error = new Error('preview stale');
          error.exitCode = 2;
          child.emit('error', error);
        });
      });
    },
    moduleInfo() { return '{"id":"chrootctl"}'; },
  };
  const bridge = await import('./webroot/chrootctl.js?install-failure-provenance');
  await assert.rejects(
    bridge.runInstall({
      distro: 'ubuntu', name: 'ubuntu', username: 'ubuntu', arch: 'arm64',
      preset: 'minimal-server', profile: 'minimal', desktop: 'none', mirror: 'auto',
      previewId: '0123456789abcdef0123456789abcdef', payloadHash: 'x', resourceRevision: 'y',
      tools: [], addons: [],
    }),
    (error) => {
      assert.equal(error.code, 'PREVIEW_STALE');
      assert.match(error.message, /Resource state changed/);
      assert.equal(error.command, active);
      return true;
    },
  );
  assert.equal(spawnCalls, 1, 'failed one-shot install must not be replayed through fallback executables');
}


// KernelSU emits a synthetic -1 exit followed by its libsu error on spawn
// failures. Preserve that native diagnostic and do not replay the install.
{
  let installSpawnCalls = 0;
  const active = '/data/adb/modules/chrootctl/runtime/arm64-v8a/chrootctl';
  const capabilities = JSON.stringify({
    protocolVersion: 1, requestId: 'capabilities', ok: true,
    data: {protocolVersion: 1, backendVersion: '0.11.0', arbitraryShell: false, transport: ['json','ndjson'], operations: [
      {name: 'install.run', mode: 'operation'},
      {name: 'operations.find_request', mode: 'query'},
      {name: 'operations.get', mode: 'query'},
    ]}, error: null,
  });
  globalThis.ksu = {
    exec(command, _options, callbackName) {
      if (command.includes("'/system/bin/id'")) return queueMicrotask(() => globalThis[callbackName](0, 'uid=0(root)\n', ''));
      if (command.includes("'version'")) return queueMicrotask(() => globalThis[callbackName](0, 'chrootctl 0.11.0\n', ''));
      if (command.includes("'app' 'capabilities'")) return queueMicrotask(() => globalThis[callbackName](0, capabilities, ''));
      if (command.includes("'operations.find_request'")) return queueMicrotask(() => globalThis[callbackName](1, '', 'not found'));
      return queueMicrotask(() => globalThis[callbackName](127, '', 'unexpected exec'));
    },
    spawn(command, argsJson, _options, callbackName) {
      assert.deepEqual(JSON.parse(argsJson), []);
      const child = globalThis[callbackName];
      if (command.includes("'app' 'query' '--request-json'") && command.includes('install.form')) {
        return queueMicrotask(() => { child.stdout.emit('data', JSON.stringify({protocolVersion:1,requestId:'webui-stream-probe',ok:true,data:{}}) + '\n'); child.emit('exit', 0); });
      }
      installSpawnCalls += 1;
      assert.ok(command.startsWith(`'${active}' 'app' 'run' '--request-json' `));
      queueMicrotask(() => {
        child.emit('exit', -1);
        queueMicrotask(() => {
          const error = new Error('libsu could not start the root-shell job');
          error.exitCode = -1;
          child.emit('error', error);
        });
      });
    },
    moduleInfo() { return '{"id":"chrootctl"}'; },
  };
  const bridge = await import('./webroot/chrootctl.js?install-native-spawn-failure');
  await assert.rejects(
    bridge.runInstall({
      distro: 'ubuntu', name: 'androidos', username: 'ubuntu', arch: 'arm64',
      preset: 'minimal-server', profile: 'minimal', desktop: 'none', mirror: 'auto',
      previewId: '1123456789abcdef0123456789abcdef', payloadHash: 'x', resourceRevision: 'y',
      tools: [], addons: [],
    }),
    (error) => {
      assert.equal(error.code, 'WEBUI_KSU_SPAWN_FAILED');
      assert.match(error.message, /libsu could not start/);
      assert.equal(error.exitCode, -1);
      assert.equal(error.bridge?.nativeError?.exitCode, -1);
      assert.match(error.bridge?.nativeError?.message || '', /root-shell job/);
      return true;
    },
  );
  assert.equal(installSpawnCalls, 1, 'synthetic -1 install result must never be replayed');
}


// A broken KSU streaming bridge must be detected by a harmless probe before
// the mutating install command is attempted, with operation-scoped diagnostics.
{
  let installSpawnCalls = 0;
  const capabilities = JSON.stringify({
    protocolVersion: 1, requestId: 'capabilities', ok: true,
    data: {protocolVersion: 1, backendVersion: '0.11.0', arbitraryShell: false, transport: ['json','ndjson'], operations: [
      {name: 'install.run', mode: 'operation'},
    ]}, error: null,
  });
  globalThis.ksu = {
    exec(command, _options, callbackName) {
      if (command.includes("'/system/bin/id'")) return queueMicrotask(() => globalThis[callbackName](0, 'uid=0(root)\n', ''));
      if (command.includes("'version'")) return queueMicrotask(() => globalThis[callbackName](0, 'chrootctl 0.11.0\n', ''));
      if (command.includes("'app' 'capabilities'")) return queueMicrotask(() => globalThis[callbackName](0, capabilities, ''));
      return queueMicrotask(() => globalThis[callbackName](127, '', 'unexpected exec'));
    },
    spawn(command, argsJson, _options, callbackName) {
      assert.deepEqual(JSON.parse(argsJson), []);
      const child = globalThis[callbackName];
      if (!(command.includes("'app' 'query' '--request-json'") && command.includes('install.form'))) installSpawnCalls += 1;
      queueMicrotask(() => {
        child.emit('exit', -1);
        queueMicrotask(() => {
          const error = new Error('KSU spawn transport is unavailable');
          error.exitCode = -1;
          child.emit('error', error);
        });
      });
    },
    moduleInfo() { return '{"id":"chrootctl"}'; },
  };
  const bridge = await import('./webroot/chrootctl.js?stream-preflight-failure');
  await assert.rejects(
    bridge.runInstall({
      distro: 'ubuntu', name: 'androidos', username: 'ubuntu', arch: 'arm64',
      preset: 'minimal-server', profile: 'minimal', desktop: 'none', mirror: 'auto',
      previewId: '2123456789abcdef0123456789abcdef', payloadHash: 'x', resourceRevision: 'y',
      tools: [], addons: [],
    }),
    (error) => {
      assert.equal(error.code, 'WEBUI_KSU_STREAM_PROBE_FAILED');
      assert.equal(error.operation, 'install.run');
      assert.equal(error.command, '/data/adb/modules/chrootctl/runtime/arm64-v8a/chrootctl');
      assert.equal(error.exitCode, -1);
      assert.match(error.bridge?.nativeError?.message || '', /transport is unavailable/);
      return true;
    },
  );
  assert.equal(installSpawnCalls, 0, 'failed streaming preflight must block the mutating install command');
}


// Seal the user-facing Create path too: detailed provenance must be rendered,
// and operations.find_request must remain available for pre-operation recovery.
{
  const bridgeSource = await readFile(new URL('./webroot/chrootctl.js', import.meta.url), 'utf8');
  const uiSource = await readFile(new URL('./webroot/index.js', import.meta.url), 'utf8');
  const htmlSource = await readFile(new URL('./webroot/index.html', import.meta.url), 'utf8');
  assert.match(bridgeSource, /'operations\.find_request'/);
  assert.match(bridgeSource, /ACTIVE_RUNTIME = `\$\{ACTIVE_MODULE\}\/runtime\/arm64-v8a\/chrootctl`/);
  assert.match(bridgeSource, /Object\.freeze\(\[ACTIVE_RUNTIME,/);
  assert.match(uiSource, /technicalError\('Install failed',e\)/);
  assert.match(uiSource, /technicalError\('Install retry failed',e\)/);
  assert.match(uiSource, /Bridge: <pre>/, 'technical failures must render sanitized KSU bridge provenance');
  assert.match(bridgeSource, /streamingBridgeSelfTestExecutable!==executable/, 'streaming preflight cache must be scoped to the selected backend executable');
  const redactStart = uiSource.indexOf('function redactDiagnosticText(value){');
  const redactEnd = uiSource.indexOf('\nfunction technicalExcerpt', redactStart);
  assert.ok(redactStart >= 0 && redactEnd > redactStart, 'diagnostic redactor must be present');
  const redactDiagnosticText = Function(`${uiSource.slice(redactStart, redactEnd)}; return redactDiagnosticText;`)();
  const secretDiagnostic = 'spawn failed --request-json {"password":"swordfish","token":"abc123"} https://example.invalid/file?access_token=urlsecret&x=1 Authorization: Bearer eyJhbGciOiJIUzI1NiJ9.payload.sig';
  const redactedDiagnostic = redactDiagnosticText(secretDiagnostic);
  assert.doesNotMatch(redactedDiagnostic, /swordfish|abc123|urlsecret|eyJhbGciOiJIUzI1NiJ9/);
  assert.match(redactedDiagnostic, /<redacted>/);
  assert.match(htmlSource, /connect-src 'self'/, 'standalone WebUI must be allowed to call its same-origin typed API');
  assert.doesNotMatch(htmlSource, /connect-src 'none'/, 'meta CSP must not silently block \/api\/v1 requests');
}

console.log('Install failure transport/provenance tests passed');
