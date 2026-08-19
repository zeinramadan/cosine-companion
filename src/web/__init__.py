"""The web front end: a loopback JSON API and a no-build HTML/CSS/ES-module UI.

Deliberately empty of imports. ``web.host`` is the only module that touches
``webview``, and re-exporting anything here would drag pywebview - and on a
headless CI runner, a hard failure - into every importer of ``web.server`` or
``web.api``. Pinned by tests/web/test_no_heavy_imports.py.
"""
