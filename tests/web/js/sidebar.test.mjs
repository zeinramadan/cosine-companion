/* Behavioural coverage for the shipped, always-mounted sidebar component. */

import { test } from 'node:test';
import assert from 'node:assert/strict';

import { buildSidebarDom, installGlobals, resetDom } from './fixture.mjs';

installGlobals();

const { createStore } = await import('../../../src/web/static/js/store.js');
const { mountSidebar } = await import('../../../src/web/static/js/components/sidebar.js');

function renderedFooter(library) {
  resetDom();
  const dom = buildSidebarDom();
  const store = createStore({ destination: 'explore', library });
  mountSidebar({ store });
  return dom.footer.textContent;
}

test('the sidebar distinguishes a broken index, first run and a healthy library', () => {
  const loadError = {
    code: 'index_load_failed',
    message: 'The saved library index is inconsistent and could not be loaded.',
  };

  assert.deepEqual(
    {
      'corrupt index': renderedFooter({
        track_count: 0,
        is_empty: true,
        load_error: loadError,
      }),
      'empty first run': renderedFooter({
        track_count: 0,
        is_empty: true,
        load_error: null,
      }),
      'healthy 1532-track library': renderedFooter({
        track_count: 1532,
        is_empty: false,
        load_error: null,
      }),
    },
    {
      'corrupt index': '— tracks indexed',
      'empty first run': '0 tracks indexed',
      'healthy 1532-track library': '1,532 tracks indexed',
    },
  );
});
