// KernelSU WebUI bridge adapter used by chrootctl.
// Supports native spawn when available and falls back to exec for managers that
// expose only the older exec API. Arguments are shell-quoted because KernelSU's
// WebView interface concatenates spawn arguments into a root-shell command.
let callbackCounter = 0;

function callbackName(prefix) {
  callbackCounter += 1;
  return `${prefix}_${Date.now()}_${callbackCounter}`;
}

function api() {
  const bridge = globalThis.ksu;
  if (!bridge || (typeof bridge.spawn !== 'function' && typeof bridge.exec !== 'function')) {
    throw new Error('KernelSU WebUI bridge is unavailable');
  }
  return bridge;
}

function shellQuote(value) {
  const text = String(value ?? '');
  return `'${text.replace(/'/g, `'\\''`)}'`;
}

function shellCommand(command, args) {
  return [shellQuote(command), ...args.map(shellQuote)].join(' ');
}

class EventEmitter {
  constructor() {
    this.listeners = new Map();
  }

  on(event, listener) {
    const current = this.listeners.get(event) || [];
    current.push(listener);
    this.listeners.set(event, current);
    return this;
  }

  emit(event, ...args) {
    for (const listener of this.listeners.get(event) || []) {
      listener(...args);
    }
  }
}

class Stream extends EventEmitter {
  write(data) {
    // KernelSU's native spawn bridge writes process output by calling
    // callback.stdout.write(...) / callback.stderr.write(...). Consumers use
    // Node-style 'data' listeners, so bridge writes must feed that channel.
    this.emit('data', data);
    this.emit('write', data);
  }
}

class ChildProcess extends EventEmitter {
  constructor() {
    super();
    this.stdin = new Stream();
    this.stdout = new Stream();
    this.stderr = new Stream();
  }
}

export function isAvailable() {
  return Boolean(globalThis.ksu && (typeof globalThis.ksu.spawn === 'function' || typeof globalThis.ksu.exec === 'function'));
}

export function spawn(command, args = [], options = {}) {
  if (typeof command !== 'string' || command.length === 0) {
    throw new TypeError('spawn command must be a non-empty string');
  }
  if (!Array.isArray(args) || !args.every((arg) => typeof arg === 'string')) {
    throw new TypeError('spawn arguments must be an array of strings');
  }

  const child = new ChildProcess();
  const bridge = globalThis.ksu;
  const name = callbackName('chrootctl_spawn');
  globalThis[name] = child;

  const cleanup = () => {
    try {
      delete globalThis[name];
    } catch (_) {
      globalThis[name] = undefined;
    }
  };
  child.on('exit', cleanup);
  child.on('error', cleanup);

  const deferError = (error) => {
    Promise.resolve().then(() => child.emit('error', error));
  };

  try {
    const native = api();
    if (typeof native.spawn === 'function') {
      // Match the proven KSU WebUI ABI used by SAN/KsuWebUIStandalone: argv is
      // JSON-encoded verbatim. The host owns argv-to-process conversion; pre-quoting
      // here turns quotes into literal argument bytes on compatible hosts.
      native.spawn(command, JSON.stringify(args), JSON.stringify(options), name);
      return child;
    }

    // Older/alternate managers may expose exec but not spawn. Emulate the
    // ChildProcess contract so callers do not hang indefinitely during startup.
    const execName = callbackName('chrootctl_exec');
    globalThis[execName] = (errno, stdout, stderr) => {
      try {
        if (stdout) child.stdout.emit('data', stdout);
        if (stderr) child.stderr.emit('data', stderr);
        // A non-zero process status is still a successfully delivered child
        // result. Treat it as an exit so callers can parse structured stdout
        // (notably bridge_error NDJSON) instead of misclassifying an
        // application failure as a transport failure and replaying the command.
        child.emit('exit', Number.isFinite(Number(errno)) ? Number(errno) : 1);
      } finally {
        try { delete globalThis[execName]; } catch (_) { globalThis[execName] = undefined; }
      }
    };
    native.exec(shellCommand(command, args), JSON.stringify(options), execName);
  } catch (error) {
    // Callers attach listeners after spawn() returns. Emitting synchronously here
    // loses the error and leaves their Promise unresolved forever.
    deferError(error);
  }
  return child;
}


export function exec(command, args = [], options = {}, timeoutMs = 15000) {
  if (typeof command !== 'string' || command.length === 0) {
    return Promise.reject(new TypeError('exec command must be a non-empty string'));
  }
  if (!Array.isArray(args) || !args.every((arg) => typeof arg === 'string')) {
    return Promise.reject(new TypeError('exec arguments must be an array of strings'));
  }
  let native;
  try { native = api(); } catch (error) { return Promise.reject(error); }
  if (typeof native.exec !== 'function') {
    return Promise.reject(new Error('KernelSU exec bridge is unavailable'));
  }
  const name = callbackName('chrootctl_exec_rpc');
  return new Promise((resolve, reject) => {
    let settled = false;
    let timer = null;
    const cleanup = () => {
      if (timer !== null) clearTimeout(timer);
      try { delete globalThis[name]; } catch (_) { globalThis[name] = undefined; }
    };
    globalThis[name] = (errno, stdout, stderr) => {
      if (settled) return;
      settled = true;
      cleanup();
      resolve({
        exitCode: Number.isFinite(Number(errno)) ? Number(errno) : 1,
        stdout: String(stdout ?? ''),
        stderr: String(stderr ?? ''),
      });
    };
    timer = setTimeout(() => {
      if (settled) return;
      settled = true;
      cleanup();
      const error = new Error(`KernelSU exec callback timed out after ${timeoutMs}ms`);
      error.code = 'KSU_EXEC_TIMEOUT';
      reject(error);
    }, Math.max(1000, Number(timeoutMs) || 15000));
    try {
      native.exec(shellCommand(command, args), JSON.stringify(options), name);
    } catch (error) {
      settled = true;
      cleanup();
      reject(error);
    }
  });
}


export async function selfTest(executable = '/data/adb/modules/chrootctl/runtime/arm64-v8a/chrootctl', timeoutMs = 8000) {
  const bridge = api();
  const methods = ['exec', 'spawn', 'moduleInfo', 'toast'].filter((name) => typeof bridge[name] === 'function');
  let module = null;
  try { module = typeof bridge.moduleInfo === 'function' ? bridge.moduleInfo() : null; } catch (_) {}
  const identity = await exec('/system/bin/id', [], {}, timeoutMs);
  if (identity.exitCode !== 0) {
    const error = new Error(identity.stderr || 'KernelSU root-shell identity probe failed');
    error.code = 'KSU_ID_PROBE_FAILED';
    throw error;
  }
  const backend = await exec(executable, ['version'], {}, timeoutMs);
  if (backend.exitCode !== 0) {
    const error = new Error(backend.stderr || `chrootctl backend probe failed with code ${backend.exitCode}`);
    error.code = 'KSU_BACKEND_PROBE_FAILED';
    throw error;
  }
  return { ok: true, methods, module, identity: identity.stdout.trim(), backend: backend.stdout.trim(), executable };
}

export function toast(message) {
  if (globalThis.ksu && typeof globalThis.ksu.toast === 'function') {
    globalThis.ksu.toast(String(message));
  }
}

export function moduleInfo() {
  if (!globalThis.ksu || typeof globalThis.ksu.moduleInfo !== 'function') {
    return null;
  }
  return globalThis.ksu.moduleInfo();
}
