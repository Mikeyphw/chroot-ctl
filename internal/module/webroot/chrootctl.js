import { isAvailable as isKernelSUAvailable, spawn } from './kernelsu.js';

const OUTPUT_LIMIT = 1024 * 1024;
const EXECUTABLES = Object.freeze([
  '/system/bin/chrootctl',
  '/data/adb/modules/chrootctl-magisk/system/bin/chrootctl',
]);

// Overlay 1 intentionally exposes only the foundation probe. Functional
// sections add narrowly-scoped operations here instead of accepting raw argv.
const OPERATIONS = Object.freeze({
  version: Object.freeze({
    args: Object.freeze(['--json', 'version']),
    command: 'version',
    mutating: false,
  }),
});

export class ChrootCtlError extends Error {
  constructor(message, details = {}) {
    super(message);
    this.name = 'ChrootCtlError';
    this.code = details.code || 'WEBUI_BACKEND_ERROR';
    this.exitCode = details.exitCode ?? null;
    this.command = details.command || null;
    this.stderr = details.stderr || '';
    this.envelope = details.envelope || null;
  }
}

function appendBounded(current, chunk) {
  const next = current + String(chunk ?? '');
  if (next.length > OUTPUT_LIMIT) {
    throw new ChrootCtlError('Backend output exceeded the WebUI safety limit', {
      code: 'WEBUI_OUTPUT_LIMIT',
    });
  }
  return next;
}

function runProcess(executable, args) {
  return new Promise((resolve, reject) => {
    let stdout = '';
    let stderr = '';
    let settled = false;
    let child;

    const finish = (fn, value) => {
      if (settled) return;
      settled = true;
      fn(value);
    };

    try {
      child = spawn(executable, args, {});
    } catch (error) {
      reject(error);
      return;
    }

    child.stdout.on('data', (chunk) => {
      try {
        stdout = appendBounded(stdout, chunk);
      } catch (error) {
        finish(reject, error);
      }
    });
    child.stderr.on('data', (chunk) => {
      try {
        stderr = appendBounded(stderr, chunk);
      } catch (error) {
        finish(reject, error);
      }
    });
    child.on('error', (error) => finish(reject, error));
    child.on('exit', (code) => finish(resolve, {
      exitCode: Number.isFinite(Number(code)) ? Number(code) : 1,
      stdout,
      stderr,
      executable,
    }));
  });
}

async function runAllowedOperation(spec) {
  let last = null;
  for (const executable of EXECUTABLES) {
    try {
      const result = await runProcess(executable, [...spec.args]);
      // Exit 126/127 commonly means this fixed launcher path is unavailable.
      // Other failures came from chrootctl itself and must not be hidden by a
      // fallback to a second binary.
      if (result.exitCode !== 126 && result.exitCode !== 127) {
        return result;
      }
      last = result;
    } catch (error) {
      last = { error, executable };
    }
  }

  throw new ChrootCtlError('Unable to start the bundled chrootctl backend', {
    code: 'WEBUI_BACKEND_UNAVAILABLE',
    exitCode: last?.exitCode ?? null,
    stderr: last?.stderr || '',
  });
}

function parseEnvelope(spec, result) {
  let envelope;
  try {
    envelope = JSON.parse(result.stdout);
  } catch (_) {
    throw new ChrootCtlError('Backend returned invalid JSON', {
      code: 'WEBUI_INVALID_JSON',
      exitCode: result.exitCode,
      command: spec.command,
      stderr: result.stderr,
    });
  }

  if (!envelope || typeof envelope !== 'object' || Array.isArray(envelope)) {
    throw new ChrootCtlError('Backend returned an invalid response envelope', {
      code: 'WEBUI_INVALID_ENVELOPE',
      exitCode: result.exitCode,
      command: spec.command,
      stderr: result.stderr,
    });
  }
  if (envelope.schema_version !== 1 || envelope.command !== spec.command || typeof envelope.ok !== 'boolean') {
    throw new ChrootCtlError('Backend response contract is incompatible with this WebUI', {
      code: 'WEBUI_CONTRACT_MISMATCH',
      exitCode: result.exitCode,
      command: spec.command,
      stderr: result.stderr,
      envelope,
    });
  }
  if (!envelope.ok || result.exitCode !== 0) {
    const backendMessage = envelope.error?.message || envelope.error?.code || 'chrootctl command failed';
    throw new ChrootCtlError(backendMessage, {
      code: envelope.error?.code || 'WEBUI_BACKEND_FAILURE',
      exitCode: result.exitCode,
      command: spec.command,
      stderr: result.stderr,
      envelope,
    });
  }
  return envelope;
}

export function isAvailable() {
  return isKernelSUAvailable();
}

export async function invoke(operation) {
  const spec = OPERATIONS[operation];
  if (!spec) {
    throw new ChrootCtlError(`Unsupported WebUI operation: ${operation}`, {
      code: 'WEBUI_OPERATION_NOT_ALLOWED',
    });
  }
  if (!isKernelSUAvailable()) {
    throw new ChrootCtlError('Open this page from a KernelSU-compatible module WebUI host', {
      code: 'WEBUI_BRIDGE_UNAVAILABLE',
      command: spec.command,
    });
  }
  const result = await runAllowedOperation(spec);
  return parseEnvelope(spec, result);
}
