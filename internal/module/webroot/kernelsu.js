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
      // KernelSU's WebUI API expects the executable as a raw command string and
      // the argv vector as a JSON array. Do not shell-quote either field here:
      // quoting changes the executable/argv bytes before KernelSU dispatches it.
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
        if (Number(errno) !== 0) {
          const error = new Error(stderr || `KernelSU exec failed with code ${errno}`);
          error.exitCode = Number(errno);
          child.emit('error', error);
        } else {
          child.emit('exit', 0);
        }
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
