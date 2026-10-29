'use strict';
// Check the standalone source. Optionally verify the original portfolio baseline
// (checkout the recorded source_commit first) against its preserved hashes in a portfolio
// checkout at the documented commit: npm run verify:source -- /path/to/portfolio
const { createHash } = require('node:crypto');
const { readFileSync } = require('node:fs');
const path = require('node:path');
const root = path.resolve(__dirname, '..');
const manifest = JSON.parse(readFileSync(path.join(root, 'source-manifest.json'), 'utf8'));
const source = process.argv[2] ? path.resolve(process.argv[2]) : null;
let failed = false;
for (const entry of manifest.files) {
  for (const [label, directory] of [['export', root], ...(source ? [['portfolio', source]] : [])]) {
    const filename = path.resolve(directory, entry.path);
    if (!filename.startsWith(directory + path.sep)) throw new Error('Invalid manifest path');
    try {
      const digest = createHash('sha256').update(readFileSync(filename)).digest('hex');
      if (digest !== (label === 'portfolio' ? entry.source_sha256 : entry.sha256)) throw new Error('source differs from recorded snapshot');
    } catch (error) {
      console.error(`${label}/${entry.path}: ${error.code === 'ENOENT' ? 'file missing' : 'source verification failed'}`);
      failed = true;
    }
  }
}
if (failed) process.exitCode = 1;
else console.log(`Verified ${manifest.files.length} connection source files${source ? ' against current manifest and original portfolio baseline' : ' against current manifest'} (${manifest.source_commit}).`);
