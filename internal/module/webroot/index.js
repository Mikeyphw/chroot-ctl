import { invoke, isAvailable } from './chrootctl.js';

const SECTIONS = Object.freeze({
  chroots: {
    kicker: 'Chroots',
    title: 'WebUI foundation ready',
    description: 'The module-hosted interface is connected through a typed chrootctl bridge. Chroot management arrives in overlay 2 of 8.',
    copy: 'Chroot cards, lifecycle actions, details, rename, and safe removal are implemented in overlay 2 of 8.',
  },
  create: {
    kicker: 'Create',
    title: 'Create section reserved',
    description: 'Distribution, architecture, profile, username, tools, add-ons, and install progress arrive in overlay 3 of 8.',
    copy: 'The foundation intentionally does not expose install mutations yet.',
  },
  transfer: {
    kicker: 'Transfer',
    title: 'Transfer section reserved',
    description: 'Local import/export, integrity state, strategy selection, and live transfer progress arrive in overlay 4 of 8.',
    copy: 'Transfer mutations remain unavailable until their section-specific safety contract is added.',
  },
  rclone: {
    kicker: 'Rclone',
    title: 'Rclone section reserved',
    description: 'Remote status, configuration, browsing, and streaming transfer workflows arrive in overlay 5 of 8.',
    copy: 'No rclone credentials or remote commands are exposed by the foundation layer.',
  },
  operations: {
    kicker: 'Operations',
    title: 'Operations section reserved',
    description: 'Persistent operation state, progress, cancellation, and history arrive in overlay 6 of 8.',
    copy: 'Long-running process lifecycle behavior is added with the operations section.',
  },
  logs: {
    kicker: 'Logs',
    title: 'Logs & diagnostics reserved',
    description: 'Logs, journals, doctor output, live follow mode, and redaction arrive in overlay 7 of 8.',
    copy: 'The foundation displays only bounded backend readiness information.',
  },
  settings: {
    kicker: 'Settings',
    title: 'Settings & convergence reserved',
    description: 'Configuration, accessibility, hardening, integration tests, and the final package seal arrive in overlay 8 of 8.',
    copy: 'Final convergence closes cross-section gaps after all functional sections land.',
  },
});

const byId = (id) => document.getElementById(id);

function setStatus(kind, label, message) {
  const chip = byId('backend-chip');
  chip.classList.remove('ready', 'error', 'neutral');
  chip.classList.add(kind);
  byId('backend-chip-label').textContent = label;
  byId('bridge-state').textContent = label;
  byId('backend-message').textContent = message;
}

function showSection(name) {
  const section = SECTIONS[name] || SECTIONS.chroots;
  document.querySelectorAll('.nav-item').forEach((button) => {
    const active = button.dataset.section === name;
    button.classList.toggle('active', active);
    if (active) button.setAttribute('aria-current', 'page');
    else button.removeAttribute('aria-current');
  });
  byId('section-kicker').textContent = section.kicker;
  byId('section-title').textContent = section.title;
  byId('section-description').textContent = section.description;
  byId('placeholder-copy').textContent = section.copy;
}

async function refreshBackend() {
  const button = byId('refresh-backend');
  button.disabled = true;
  setStatus('neutral', 'Checking backend', 'Probing the allow-listed chrootctl version operation.');

  if (!isAvailable()) {
    setStatus('error', 'Bridge unavailable', 'KernelSU APIs are not available. Open this WebUI from a KernelSU-compatible module manager.');
    button.disabled = false;
    return;
  }

  try {
    const envelope = await invoke('version');
    const data = envelope.data || {};
    byId('backend-version').textContent = String(data.version || 'unknown');
    byId('backend-kind').textContent = String(data.backend || 'unknown');
    byId('backend-commit').textContent = String(data.commit || 'unknown');
    setStatus('ready', 'Backend ready', 'The KernelSU process bridge and chrootctl JSON contract are responding correctly.');
  } catch (error) {
    byId('backend-version').textContent = '—';
    byId('backend-kind').textContent = '—';
    byId('backend-commit').textContent = '—';
    const code = typeof error?.code === 'string' ? error.code : 'WEBUI_BACKEND_ERROR';
    setStatus('error', 'Backend unavailable', `${code}: ${error?.message || 'Unable to contact chrootctl.'}`);
  } finally {
    button.disabled = false;
  }
}

document.querySelectorAll('.nav-item').forEach((button) => {
  button.addEventListener('click', () => showSection(button.dataset.section));
});
byId('refresh-backend').addEventListener('click', refreshBackend);
showSection('chroots');
refreshBackend();
