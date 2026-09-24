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
// the mutating spawn is attempted. If ordinary ksu.exec works, use it exactly
// once as the compatibility transport instead of making install impossible.
{
  let installSpawnCalls = 0;
  let installExecCalls = 0;
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
      if (command.includes("'app' 'run' '--request-json'")) {
        installExecCalls += 1;
        const out = [
          {protocolVersion:1,requestId:'webui-run',operationId:'op-exec-1',sequence:1,type:'operation_started',payload:{progressText:'Started'}},
          {protocolVersion:1,requestId:'webui-run',operationId:'op-exec-1',sequence:2,type:'operation_succeeded',payload:{result:{name:'androidos'}}},
        ].map((x) => JSON.stringify(x)).join('\n') + '\n';
        return queueMicrotask(() => globalThis[callbackName](0, out, ''));
      }
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
  const bridge = await import('./webroot/chrootctl.js?stream-preflight-exec-fallback');
  const result = await bridge.runInstall({
    distro: 'ubuntu', name: 'androidos', username: 'ubuntu', arch: 'arm64',
    preset: 'minimal-server', profile: 'minimal', desktop: 'none', mirror: 'auto',
    previewId: '2123456789abcdef0123456789abcdef', payloadHash: 'x', resourceRevision: 'y',
    tools: [], addons: [],
  });
  assert.equal(result.operationId, 'op-exec-1');
  assert.equal(result.result?.name, 'androidos');
  assert.equal(installSpawnCalls, 0, 'failed streaming preflight must block mutating spawn');
  assert.equal(installExecCalls, 1, 'compatibility exec must run the mutation exactly once');
}

// Standalone browser mutations are non-replayable. If the start response is
// lost after the backend accepted the request, recover the operation by its
// stable request id and poll the persistent journal. Never resend install.run.
{
  delete globalThis.ksu;
  globalThis.window = {
    location: {protocol:'http:',hostname:'127.0.0.1',origin:'http://127.0.0.1:9876'},
  };
  globalThis.document = {cookie:'chrootctl_csrf=test-csrf'};
  const response = (data, status=200) => ({
    status,
    ok: status >= 200 && status < 300,
    async text() { return typeof data === 'string' ? data : JSON.stringify(data); },
  });
  let runPosts = 0;
  let xhrRequests = 0;
  let stableRequestId = '';
  globalThis.XMLHttpRequest = class {
    open() {}
    setRequestHeader() {}
    send() { xhrRequests += 1; throw new Error('mutation XHR replay must not happen'); }
  };
  globalThis.fetch = async (url, options={}) => {
    const path = new URL(String(url)).pathname;
    if (path === '/api/v1/health') return response({ok:true});
    if (path === '/api/v1/capabilities') return response({
      protocolVersion:1,requestId:'caps',ok:true,
      data:{protocolVersion:1,backendVersion:'0.11.0',arbitraryShell:false,transport:['standalone-http'],operations:[{name:'install.run',mode:'operation'}]},
      error:null,
    });
    if (path === '/api/v1/run/install.run') {
      runPosts += 1;
      stableRequestId = String(options.headers?.['X-Chrootctl-Request-ID'] || '');
      assert.ok(stableRequestId.startsWith('webui-'));
      // Simulate the exact failure that produced PREVIEW_NOT_FOUND: the server
      // accepted/started the mutation, but the browser lost the response.
      throw new TypeError('simulated lost start response after accept');
    }
    if (path === '/api/v1/query/operations.find_request') {
      const payload = JSON.parse(String(options.body || '{}'));
      assert.equal(payload.requestId, stableRequestId);
      return response({protocolVersion:1,requestId:'find',ok:true,data:{found:true,operationId:'op-http-1'},error:null});
    }
    if (path === '/api/v1/operations/op-http-1') {
      return response({protocolVersion:1,requestId:'op',ok:true,data:{
        operationId:'op-http-1',state:'succeeded',complete:true,eventSequence:2,resultPayload:{name:'androidos'},
        progressEvents:[
          {protocolVersion:1,requestId:stableRequestId,operationId:'op-http-1',sequence:1,type:'operation_started',payload:{progressText:'Started'}},
          {protocolVersion:1,requestId:stableRequestId,operationId:'op-http-1',sequence:2,type:'operation_succeeded',payload:{result:{name:'androidos'}}},
        ],
      },error:null});
    }
    return response({error:{code:'NOT_FOUND',message:`unexpected ${path}`}},404);
  };
  const bridge = await import('./webroot/chrootctl.js?standalone-mutation-no-replay');
  const result = await bridge.runInstall({
    distro:'ubuntu',name:'androidos',username:'ubuntu',arch:'arm64',preset:'minimal-server',profile:'minimal',desktop:'none',mirror:'auto',
    previewId:'3123456789abcdef0123456789abcdef',payloadHash:'x',resourceRevision:'y',tools:[],addons:[],
  });
  assert.equal(result.operationId, 'op-http-1');
  assert.equal(result.result?.name, 'androidos');
  assert.equal(runPosts, 1, 'one-shot install.run must never be replayed after an ambiguous network failure');
  assert.equal(xhrRequests, 0, 'mutation start must never fall through to XHR replay');
}


// Standalone cancellation is a mutation too. A lost cancel response must not
// trigger the generic fetch->XHR replay path.
{
  delete globalThis.ksu;
  globalThis.window = {location:{protocol:'http:',hostname:'127.0.0.1',origin:'http://127.0.0.1:9878'}};
  globalThis.document = {cookie:'chrootctl_csrf=test-csrf'};
  let cancelPosts = 0;
  let xhrRequests = 0;
  globalThis.XMLHttpRequest = class {
    open() {}
    setRequestHeader() {}
    send() { xhrRequests += 1; throw new Error('cancel XHR replay must not happen'); }
  };
  globalThis.fetch = async (url) => {
    const path = new URL(String(url)).pathname;
    if (path === '/api/v1/operations/op-cancel/cancel') {
      cancelPosts += 1;
      throw new TypeError('simulated lost cancel response');
    }
    throw new Error(`unexpected ${path}`);
  };
  const bridge = await import('./webroot/chrootctl.js?standalone-cancel-no-replay');
  await assert.rejects(bridge.cancelOperation('op-cancel'), (error) => {
    assert.equal(error.code, 'WEBUI_HTTP_ERROR');
    assert.match(error.message, /mutation was not replayed/);
    return true;
  });
  assert.equal(cancelPosts, 1);
  assert.equal(xhrRequests, 0);
}

// A complete journal record without its terminal event must still synthesize a
// terminal event with a fresh sequence number so the UI sees the backend's real
// failure instead of INSTALL_BACKEND_EXIT.
{
  delete globalThis.ksu;
  globalThis.window = {location:{protocol:'http:',hostname:'127.0.0.1',origin:'http://127.0.0.1:9877'}};
  globalThis.document = {cookie:'chrootctl_csrf=test-csrf'};
  const response = (data, status=200) => ({status,ok:status>=200&&status<300,async text(){return JSON.stringify(data)}});
  globalThis.fetch = async (url, options={}) => {
    const path = new URL(String(url)).pathname;
    if (path === '/api/v1/health') return response({ok:true});
    if (path === '/api/v1/capabilities') return response({protocolVersion:1,requestId:'caps',ok:true,data:{protocolVersion:1,backendVersion:'0.11.0',arbitraryShell:false,transport:['standalone-http'],operations:[{name:'install.run',mode:'operation'}]},error:null});
    if (path === '/api/v1/run/install.run') return response({accepted:true,requestId:String(options.headers?.['X-Chrootctl-Request-ID']||''),operationId:'op-http-failed',events:[{operationId:'op-http-failed',sequence:1,type:'operation_started',payload:{progressText:'Started'}}]},202);
    if (path === '/api/v1/operations/op-http-failed') return response({protocolVersion:1,requestId:'op',ok:true,data:{operationId:'op-http-failed',state:'failed',complete:true,eventSequence:2,error:'Rootfs verification failed',errorCode:'ROOTFS_VERIFY_FAILED',logPath:'/data/local/tmp/chrootctl/chrootctl.log',progressEvents:[{operationId:'op-http-failed',sequence:1,type:'operation_started',payload:{progressText:'Started'}},{operationId:'op-http-failed',sequence:2,type:'operation_progress',payload:{percent:50,message:'Verifying'}}]},error:null});
    return response({error:{code:'NOT_FOUND',message:`unexpected ${path}`}},404);
  };
  const bridge = await import('./webroot/chrootctl.js?standalone-synthetic-terminal');
  await assert.rejects(
    bridge.runInstall({distro:'ubuntu',name:'androidos',username:'ubuntu',arch:'arm64',preset:'minimal-server',profile:'minimal',desktop:'none',mirror:'auto',previewId:'4123456789abcdef0123456789abcdef',payloadHash:'x',resourceRevision:'y',tools:[],addons:[]}),
    (error) => {
      assert.equal(error.code, 'ROOTFS_VERIFY_FAILED');
      assert.match(error.message, /Rootfs verification failed/);
      assert.equal(error.operationId, 'op-http-failed');
      return true;
    },
  );
}

// Seal the user-facing Create path too: detailed provenance must be rendered,
// and operations.find_request must remain available for pre-operation recovery.
{
  const bridgeSource = await readFile(new URL('./webroot/chrootctl.js', import.meta.url), 'utf8');
  const uiSource = await readFile(new URL('./webroot/index.js', import.meta.url), 'utf8');
  const htmlSource = await readFile(new URL('./webroot/index.html', import.meta.url), 'utf8');
  const cssSource = await readFile(new URL('./webroot/index.css', import.meta.url), 'utf8');
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
  assert.match(htmlSource, /id="install-copy-error"[^>]*>Copy error<\/button>/, 'install dialog must expose a Copy error action');
  assert.match(cssSource, /\.dialog-actions\{[^}]*flex-wrap:wrap/, 'install dialog actions must wrap on narrow mobile screens');
  assert.match(uiSource, /copyDiagnosticText\('install-error','Install error'\)/, 'Copy error must copy the rendered install diagnostic');
  assert.match(htmlSource, /connect-src 'self'/, 'standalone WebUI must be allowed to call its same-origin typed API');
  assert.doesNotMatch(htmlSource, /connect-src 'none'/, 'meta CSP must not silently block \/api\/v1 requests');
}

console.log('Install failure transport/provenance tests passed');
