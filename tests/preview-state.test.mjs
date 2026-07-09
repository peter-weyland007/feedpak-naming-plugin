import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import path from 'node:path';

const scriptPath = path.resolve('/Users/itadmin/Desktop/feedpak-naming-plugin/screen.js');
const script = fs.readFileSync(scriptPath, 'utf8');

function loadHelpers() {
  const sandbox = {
    window: {},
    document: {
      getElementById() { return null; },
      querySelectorAll() { return []; },
    },
    fetch: async () => ({ ok: true, text: async () => '{}' }),
    console,
    setTimeout,
    clearTimeout,
  };
  sandbox.window.window = sandbox.window;
  sandbox.window.document = sandbox.document;
  vm.runInNewContext(script, sandbox, { filename: 'screen.js' });
  return sandbox.window.__feedBackFeedpakNaming.__test;
}

test('skip_conflicts derives skipped rows instead of conflict rows', () => {
  const helpers = loadHelpers();
  assert.ok(helpers, 'expected test helpers to be exposed');
  const preview = {
    items: [
      {
        current_relative_path: 'starter/beethoven-fur_elise.feedpak',
        proposed_relative_path: 'Ludwig van Beethoven/F-r Elise.feedpak',
        actionable: true,
        target_exists: true,
      },
    ],
  };
  const derived = helpers.derivePreview(preview, {
    selectedPaths: ['starter/beethoven-fur_elise.feedpak'],
    duplicateHandling: 'skip_conflicts',
  });
  assert.equal(derived.items[0].effectiveStatus, 'skipped');
  assert.equal(derived.conflictCount, 0);
  assert.equal(derived.skippedCount, 1);
});
