import fs from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const scriptDir = path.dirname(fileURLToPath(import.meta.url));
const desktopRoot = path.resolve(scriptDir, '..');
const repoRoot = path.resolve(desktopRoot, '..');
const frontendSrc = path.join(repoRoot, 'frontend');
const distRoot = path.join(desktopRoot, 'dist');
const distFrontend = path.join(distRoot, 'frontend');
const srcIndex = path.join(frontendSrc, 'index.html');
const distIndex = path.join(distRoot, 'index.html');

async function main() {
  await fs.rm(distRoot, { recursive: true, force: true });
  await fs.mkdir(distRoot, { recursive: true });
  await fs.cp(frontendSrc, distFrontend, { recursive: true });

  // Tauri bundled builds load from local files, so absolute /frontend paths break.
  const html = await fs.readFile(srcIndex, 'utf8');
  const rewritten = html.replaceAll('/frontend/', './frontend/');
  await fs.writeFile(distIndex, rewritten, 'utf8');

  console.log('[OpenDCF Desktop] Prepared frontend assets at desktop-tauri/dist');
}

main().catch((err) => {
  console.error('[OpenDCF Desktop] Failed to prepare frontend assets:', err);
  process.exit(1);
});
