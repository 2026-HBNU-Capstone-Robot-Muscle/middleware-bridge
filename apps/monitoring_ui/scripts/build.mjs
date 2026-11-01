import { cp, mkdir, rm } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import { dirname, resolve } from 'node:path';

const appRoot = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const output = resolve(appRoot, 'dist');

await rm(output, { recursive: true, force: true });
await mkdir(output, { recursive: true });
await cp(resolve(appRoot, 'index.html'), resolve(output, 'index.html'));
await cp(resolve(appRoot, 'styles.css'), resolve(output, 'styles.css'));
await cp(resolve(appRoot, 'src'), resolve(output, 'src'), { recursive: true });
console.log(`Static Tauri frontend written to ${output}`);
