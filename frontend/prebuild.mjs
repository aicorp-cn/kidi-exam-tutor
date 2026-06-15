// 注入 git short hash 到 sw.js，确保每次构建 SW 缓存自动失效
import { execSync } from 'child_process';
import { readFileSync, writeFileSync } from 'fs';
import { resolve, dirname } from 'path';
import { fileURLToPath } from 'url';

const __dirname = dirname(fileURLToPath(import.meta.url));
const swPath = resolve(__dirname, 'public/sw.js');

let hash;
try {
  hash = execSync('git rev-parse --short HEAD', { cwd: resolve(__dirname, '..'), encoding: 'utf8' }).trim();
} catch {
  hash = Date.now().toString(36); // fallback: 非 git 环境用时戳
}

let content = readFileSync(swPath, 'utf8');
content = content.replace(/__GIT_HASH__/g, hash);
writeFileSync(swPath, content);
console.log(`[prebuild] SW cache version: exam-tutor-${hash}`);
