import assert from 'node:assert/strict';

let capturedSpawn = null;
globalThis.ksu = {
  spawn(command, argsJSON, optionsJSON, callbackName) {
    capturedSpawn = { command, args: JSON.parse(argsJSON), options: JSON.parse(optionsJSON), callbackName };
    queueMicrotask(() => {
      const child = globalThis[callbackName];
      child.stdout.emit('data', 'spawn-ok');
      child.emit('exit', 0);
    });
  },
};

const bridge = await import('./webroot/kernelsu.js');
const request = '{"protocolVersion":1,"requestId":"transport-test","operation":"chroots.list","payload":{"note":"O\'Brien $HOME ; &"}}';
const spawned = bridge.spawn('/data/adb/chrootctl/bin/chrootctl', ['app', 'query', '--request-json', request]);
let stdout = '';
await new Promise((resolve, reject) => {
  spawned.stdout.on('data', (chunk) => { stdout += chunk; });
  spawned.on('error', reject);
  spawned.on('exit', (code) => code === 0 ? resolve() : reject(new Error(`exit ${code}`)));
});
assert.equal(stdout, 'spawn-ok');
assert.equal(capturedSpawn.command, "'/data/adb/chrootctl/bin/chrootctl'");
assert.deepEqual(capturedSpawn.args.slice(0, 3), ["'app'", "'query'", "'--request-json'"]);
assert.ok(capturedSpawn.args[3].startsWith("'{\"protocolVersion\":1"));
assert.ok(capturedSpawn.args[3].includes("O'\\''Brien"));

// Synchronous native bridge exceptions must be delivered after callers attach
// listeners; otherwise the WebUI remains stuck forever at "Checking backend".
globalThis.ksu = { spawn() { throw new Error('native spawn unavailable'); } };
const broken = bridge.spawn('/data/adb/chrootctl/bin/chrootctl', ['version']);
const syncError = await new Promise((resolve, reject) => {
  const timeout = setTimeout(() => reject(new Error('lost synchronous spawn error')), 1000);
  broken.on('error', (error) => { clearTimeout(timeout); resolve(error); });
});
assert.match(syncError.message, /native spawn unavailable/);

// Managers exposing only the older exec API still get the ChildProcess contract.
let capturedExec = '';
globalThis.ksu = {
  exec(command, optionsJSON, callbackName) {
    capturedExec = command;
    JSON.parse(optionsJSON);
    queueMicrotask(() => globalThis[callbackName](0, 'exec-ok', ''));
  },
};
assert.equal(bridge.isAvailable(), true);
const fallback = bridge.spawn('/data/adb/chrootctl/bin/chrootctl', ['app', 'capabilities']);
let fallbackOut = '';
await new Promise((resolve, reject) => {
  fallback.stdout.on('data', (chunk) => { fallbackOut += chunk; });
  fallback.on('error', reject);
  fallback.on('exit', (code) => code === 0 ? resolve() : reject(new Error(`exit ${code}`)));
});
assert.equal(fallbackOut, 'exec-ok');
assert.equal(capturedExec, "'/data/adb/chrootctl/bin/chrootctl' 'app' 'capabilities'");

console.log('KernelSU WebUI transport tests passed');
