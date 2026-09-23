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

function redactBridgeDiagnostic(value) {
  let text = String(value ?? '');
  text = text.replace(/("(?:password|confirmPassword|token|secret|apiKey|authorization|accessToken|refreshToken|credential)"\s*:\s*")([^"]*)(")/gi, '$1<redacted>$3');
  text = text.replace(/([?&](?:token|key|password|secret|auth|authorization|signature|sig|credential|access_token|refresh_token)=)[^&#\s"'<>]+/gi, '$1<redacted>');
  text = text.replace(/\b(Bearer)\s+[A-Za-z0-9._~+\/=-]+/gi, '$1 <redacted>');
  return text;
}

function sanitizedBridgeError(error) {
  const safe = new Error(redactBridgeDiagnostic(error?.message ?? error));
  if (error?.code) safe.code = error.code;
  if (Number.isFinite(Number(error?.exitCode))) safe.exitCode = Number(error.exitCode);
  return safe;
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
  const name = callbackName('chrootctl_spawn');
  let pendingExitCode = null;
  let pendingExitTimer = null;
  let completed = false;

  child.bridgeTransport = 'kernelsu.spawn';
  child.bridgeError = null;

  const cleanup = () => {
    if (pendingExitTimer !== null) {
      clearTimeout(pendingExitTimer);
      pendingExitTimer = null;
    }
    try {
      delete globalThis[name];
    } catch (_) {
      globalThis[name] = undefined;
    }
  };

  const finishExit = (code) => {
    if (completed) return;
    completed = true;
    cleanup();
    child.emit('exit', code);
  };

  const finishError = (error) => {
    if (completed) return;
    completed = true;
    cleanup();
    child.emit('error', error);
  };

  // KernelSU's manager posts a non-zero `exit` event and then a separate
  // `error` event containing libsu's diagnostic. Keep the native callback alive
  // briefly after a non-zero exit so that diagnostic is not discarded.
  const nativeCallback = {
    stdout: child.stdout,
    stderr: child.stderr,
    emit(event, value) {
      if (event === 'exit') {
        const code = Number.isFinite(Number(value)) ? Number(value) : 1;
        pendingExitCode = code;
        if (code === 0) {
          finishExit(code);
          return;
        }
        if (pendingExitTimer !== null) clearTimeout(pendingExitTimer);
        pendingExitTimer = setTimeout(() => finishExit(code), 500);
        return;
      }
      if (event === 'error') {
        const raw = value && typeof value === 'object' ? value : { message: String(value ?? '') };
        const exitCode = Number.isFinite(Number(raw.exitCode)) ? Number(raw.exitCode) : pendingExitCode;
        child.bridgeError = {
          message: redactBridgeDiagnostic(raw.message ?? ''),
          exitCode: Number.isFinite(Number(exitCode)) ? Number(exitCode) : null,
        };
        if (pendingExitCode !== null) {
          finishExit(pendingExitCode);
          return;
        }
        const error = new Error(child.bridgeError.message || 'KernelSU spawn bridge failed');
        error.code = 'KSU_SPAWN_ERROR';
        error.exitCode = child.bridgeError.exitCode;
        finishError(error);
        return;
      }
      child.emit(event, value);
    },
  };
  globalThis[name] = nativeCallback;

  const deferError = (error) => {
    Promise.resolve().then(() => finishError(sanitizedBridgeError(error)));
  };

  try {
    const native = api();
    if (typeof native.spawn === 'function') {
      // KernelSU's Android host executes spawn through a root shell and currently
      // concatenates argv strings without shell escaping. Pass one fully quoted
      // shell command and an empty argv array so JSON/password/path arguments
      // remain one shell token each while retaining streaming output.
      native.spawn(shellCommand(command, args), JSON.stringify([]), JSON.stringify(options), name);
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
        finishExit(Number.isFinite(Number(errno)) ? Number(errno) : 1);
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
