// postbuild: 将 webui/sw.js 中的 __GIT_HASH__ 替换为实际 git hash
import { readFileSync, writeFileSync, existsSync } from 'fs';
import { resolve, dirname } from 'path';
import { fileURLToPath } from 'url';

const __dirname = dirname(fileURLToPath(import.meta.url));
const hashFile = resolve(__dirname, '.git-hash');
const swFile = resolve(__dirname, '..', 'webui', 'sw.js');

if (!existsSync(hashFile)) {
  console.error('[postbuild] .git-hash not found — did prebuild run?');
  process.exit(1);
}

const hash = readFileSync(hashFile, 'utf8').trim();
let content = readFileSync(swFile, 'utf8');

const before = content;
content = content.replace(/__GIT_HASH__/g, hash);

if (content === before) {
  console.error('[postbuild] WARNING: __GIT_HASH__ placeholder not found in webui/sw.js');
} else {
  writeFileSync(swFile, content);
  console.log(`[postbuild] SW cache version → exam-tutor-${hash}`);
}
