// Minimal KernelSU WebUI bridge used by chrootctl.
// Deliberately exposes process spawning, not a shell-string exec helper.
let callbackCounter = 0;

function callbackName(prefix) {
  callbackCounter += 1;
  return `${prefix}_${Date.now()}_${callbackCounter}`;
}

function api() {
  const bridge = globalThis.ksu;
  if (!bridge || typeof bridge.spawn !== 'function') {
    throw new Error('KernelSU WebUI bridge is unavailable');
  }
  return bridge;
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
  return Boolean(globalThis.ksu && typeof globalThis.ksu.spawn === 'function');
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

  try {
    api().spawn(command, JSON.stringify(args), JSON.stringify(options), name);
  } catch (error) {
    child.emit('error', error);
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
