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
  const child = spawn('/data/adb/modules/chrootctl-magisk/runtime/arm64-v8a/chrootctl', ['app', 'run'], {});
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
  const active = '/data/adb/modules/chrootctl-magisk/runtime/arm64-v8a/chrootctl';
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
      spawnCalls += 1;
      assert.equal(command, active);
      const args = JSON.parse(argsJson);
      assert.equal(args[0], 'app');
      assert.equal(args[1], 'run');
      const child = globalThis[callbackName];
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
      });
    },
    moduleInfo() { return '{"id":"chrootctl-magisk"}'; },
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


// Seal the user-facing Create path too: detailed provenance must be rendered,
// and operations.find_request must remain available for pre-operation recovery.
{
  const bridgeSource = await readFile(new URL('./webroot/chrootctl.js', import.meta.url), 'utf8');
  const uiSource = await readFile(new URL('./webroot/index.js', import.meta.url), 'utf8');
  assert.match(bridgeSource, /'operations\.find_request'/);
  assert.match(bridgeSource, /ACTIVE_RUNTIME = `\$\{ACTIVE_MODULE\}\/runtime\/arm64-v8a\/chrootctl`/);
  assert.match(bridgeSource, /Object\.freeze\(\[ACTIVE_RUNTIME,/);
  assert.match(uiSource, /technicalError\('Install failed',e\)/);
  assert.match(uiSource, /technicalError\('Install retry failed',e\)/);
}

console.log('Install failure transport/provenance tests passed');
