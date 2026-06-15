// 计算 git short hash，供 postbuild 使用
import { execSync } from 'child_process';
import { writeFileSync } from 'fs';
import { resolve, dirname } from 'path';
import { fileURLToPath } from 'url';

const __dirname = dirname(fileURLToPath(import.meta.url));
let hash;
try {
  hash = execSync('git rev-parse --short HEAD', { cwd: resolve(__dirname, '..'), encoding: 'utf8' }).trim();
} catch {
  hash = Date.now().toString(36);
}
writeFileSync(resolve(__dirname, '.git-hash'), hash);
console.log(`[prebuild] git hash: ${hash}`);
