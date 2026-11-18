import { spawn } from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const scriptDir = path.dirname(fileURLToPath(import.meta.url));
const repoRoot = path.resolve(scriptDir, '..', '..');
const port = process.env.OPENDCF_DESKTOP_PORT || '8011';

const pythonPath = process.platform === 'win32'
  ? path.join(repoRoot, '.venv', 'Scripts', 'python.exe')
  : path.join(repoRoot, '.venv', 'bin', 'python');

if (!fs.existsSync(pythonPath)) {
  console.error(`[OpenDCF Desktop] Python runtime not found: ${pythonPath}`);
  console.error('[OpenDCF Desktop] Create the virtual environment first:');
  console.error('  python -m venv .venv && .venv/bin/pip install -e .');
  process.exit(1);
}

const args = [
  '-m',
  'uvicorn',
  'src.main:app',
  '--host',
  '127.0.0.1',
  '--port',
  port,
];

let child = null;
let keepAliveTimer = null;

async function isHealthy() {
  try {
    const res = await fetch(`http://127.0.0.1:${port}/health`, { method: 'GET' });
    return res.ok;
  } catch {
    return false;
  }
}

function holdProcessOpen() {
  if (!keepAliveTimer) keepAliveTimer = setInterval(() => {}, 1 << 30);
}

function forward(sig) {
  if (child && !child.killed) {
    child.kill(sig);
    return;
  }
  if (keepAliveTimer) clearInterval(keepAliveTimer);
  process.exit(0);
}

process.on('SIGINT', () => forward('SIGINT'));
process.on('SIGTERM', () => forward('SIGTERM'));

if (await isHealthy()) {
  console.log(`[OpenDCF Desktop] Backend already running at http://127.0.0.1:${port}`);
  holdProcessOpen();
} else {
  child = spawn(pythonPath, args, {
    cwd: repoRoot,
    stdio: 'inherit',
  });

  child.on('exit', async (code) => {
    // If another process raced us and is already serving this port, keep going.
    if (code !== 0 && await isHealthy()) {
      console.log(`[OpenDCF Desktop] Backend already active at http://127.0.0.1:${port}`);
      holdProcessOpen();
      return;
    }
    process.exit(code ?? 0);
  });
}
