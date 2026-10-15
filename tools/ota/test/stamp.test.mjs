// The pages' asset hashes must match the files (see stamp.py).

import { test } from 'node:test';
import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';

test('asset stamps are up to date', () => {
  const script = new URL('../stamp.py', import.meta.url).pathname;
  assert.doesNotThrow(() => execFileSync('python3', [script, '--check'], { stdio: 'pipe' }),
    'run: python3 tools/ota/stamp.py');
});
