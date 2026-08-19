/* The Settings form reads the current XML path and writes the edited one
 * through the shipped API client. This is a behaviour test, not a screenshot:
 * it proves the form's request and feedback sequence, while the WKWebView pass
 * remains responsible for the rendered result.
 */

import { test } from 'node:test';
import assert from 'node:assert/strict';

import {
  buildSettingsDom,
  installFetch,
  installGlobals,
  settle,
} from './fixture.mjs';

installGlobals();

test('the Settings destination loads and persists the edited XML path', async () => {
  const fetches = installFetch();
  const { form, input, submit, status } = buildSettingsDom();
  const { mountSettings } = await import(
    '../../../src/web/static/js/components/settings.js'
  );

  mountSettings();

  assert.equal(fetches.requests.length, 1);
  assert.equal(fetches.requests[0].path, '/api/settings');
  assert.equal(fetches.requests[0].options.method, 'GET');
  assert.equal(input.disabled, true);

  fetches.deliver('/api/settings?q=', {
    settings: { xml_path: '/old/collection.xml' },
  });
  await settle();

  assert.equal(input.value, '/old/collection.xml');
  assert.equal(input.disabled, false);
  assert.equal(submit.disabled, false);

  input.value = '/new/collection.xml';
  form.dispatch('submit');
  await settle();

  assert.equal(fetches.requests.length, 2);
  const write = fetches.requests[1];
  assert.equal(write.path, '/api/settings');
  assert.equal(write.options.method, 'POST');
  assert.equal(write.options.headers['Content-Type'], 'application/json');
  assert.deepEqual(JSON.parse(write.options.body), {
    xml_path: '/new/collection.xml',
  });
  assert.equal(input.disabled, true);

  fetches.deliver('/api/settings?q=', {
    settings: { xml_path: '/new/collection.xml' },
  });
  await settle();

  assert.equal(input.value, '/new/collection.xml');
  assert.equal(status.textContent, 'Settings saved.');
  assert.equal(status.dataset.state, 'success');
  assert.equal(input.disabled, false);
  assert.equal(submit.disabled, false);
});
