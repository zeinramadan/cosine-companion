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

test('a failed Settings save reports the error and restores the form', async () => {
  const fetches = installFetch();
  const { form, input, submit, status } = buildSettingsDom();
  const { mountSettings } = await import(
    '../../../src/web/static/js/components/settings.js'
  );

  mountSettings();
  fetches.deliver('/api/settings?q=', {
    settings: { xml_path: '/old/collection.xml' },
  });
  await settle();

  input.value = '/new/collection.xml';
  form.dispatch('submit');
  await settle();
  fetches.reject('/api/settings?q=');
  await settle();

  assert.equal(status.textContent, 'Could not reach the local server.');
  assert.equal(status.dataset.state, 'error');
  assert.equal(input.disabled, false);
  assert.equal(submit.disabled, false);
});

test('submitting Settings prevents the browser form navigation', async () => {
  const fetches = installFetch();
  const { form, input } = buildSettingsDom();
  const { mountSettings } = await import(
    '../../../src/web/static/js/components/settings.js'
  );

  mountSettings();
  fetches.deliver('/api/settings?q=', {
    settings: { xml_path: '/old/collection.xml' },
  });
  await settle();

  let prevented = false;
  input.value = '/new/collection.xml';
  form.dispatch('submit', {
    preventDefault() {
      prevented = true;
    },
  });

  assert.equal(prevented, true);
});

test('a blank Settings path is refused without sending a write', async () => {
  const fetches = installFetch();
  const { form, input, status } = buildSettingsDom();
  const { mountSettings } = await import(
    '../../../src/web/static/js/components/settings.js'
  );

  mountSettings();
  fetches.deliver('/api/settings?q=', {
    settings: { xml_path: '/old/collection.xml' },
  });
  await settle();

  const requestsBeforeSubmit = fetches.requests.length;
  input.value = '  \t  ';
  form.dispatch('submit');
  await settle();

  assert.equal(fetches.requests.length, requestsBeforeSubmit);
  assert.equal(status.textContent, 'Enter a Rekordbox XML path before saving.');
  assert.equal(status.dataset.state, 'error');
  assert.equal(input.focused, 1);
});
