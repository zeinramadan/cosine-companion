"""A reader and a writer that are different PROCESSES, which is the real case.

WHY THIS FILE EXISTS
--------------------
``import-playlists`` is a CLI command (``cosine_companion.py:83``) and the
drawer is a webview served by a long-running process. The workflow the feature
builds leads straight to running both at once: the drawer tells the user their
playlists are stale and names the command, and the natural thing to do is run
it in a terminal with the app still open. Reader and writer are different
processes **by design**, so no in-process lock can order them, and every
assertion here is about what one side may observe while the other is mid-flight.

Two properties, and one test group each:

**A reader must never parse bytes it did not verify.** Validating the tables and
then re-opening them by path is two different reads of a mutable name. See
``test_a_writer_landing_while_the_reader_is_open_*``.

**Two writers must never commit each other's tables.** Staging to one shared
name means two imports write the same path, and whichever digest is taken last
describes bytes the other one produced. See ``test_two_concurrent_writers_*``.

NO SLEEPS, NO LUCK
------------------
A race proved by timing is a test that flakes in CI and gets deleted, which is
worse than not having it. Every interleaving below is *injected*: the reader is
paused at a named seam, or the two writers are stepped through each other with
``threading.Event``. Every ``wait`` carries a timeout so a deadlock fails the
test instead of hanging the suite.

The reader loop over real import processes is the one test whose reader is
free-running, and even there nothing is left to a scheduler: it does not start
an import until the reader has been *seen* to observe the previous one. Its
invariant can be violated but never "passed by luck", and its ordering
assertion can no longer be FAILED by luck either.

THE SEAM THE READER IS PAUSED AT
--------------------------------
"After the reader has committed to a manifest, before it has read a byte of
either table." That window is described in terms of behaviour rather than of
one function's name, so the probes do not have to be rewritten when the store's
internals change - which is the point of a regression test for a race.
``_PausesBeforeReadingATable`` hooks both ways a table's bytes can be reached
(``Path.read_bytes`` and ``pandas.read_parquet``) and fires once, on whichever
comes first.
"""

import importlib.util
import json
import os
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import pytest

from playlist_fixtures import (
    FIXTURE_TRACK_IDS,
    FIXTURE_XML,
    write_schema_2_layout,
)

import core.playlist_store as store
from core.playlist_store import (
    LEGACY_TABLE_FILENAMES,
    MEMBERSHIP_STEM,
    PLAYLISTS_STEM,
    PROVENANCE_FILENAME,
    REAP_GRACE_SECONDS,
    STAGING_SUFFIX,
    committed_table_paths,
    playlist_manifest_path,
    read_playlist_tables,
    read_provenance,
    reap_superseded_generations,
)
from services.playlist_import import import_playlists
from services.playlist_service import IMPORT_COMMAND, PlaylistService

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

FIXED_CLOCK = datetime(2026, 8, 19, 14, 30, 0, tzinfo=timezone.utc)

#: Waits are bounded so a deadlock is a failure, not a hung CI job. Generous
#: because it is only ever reached when something is already wrong.
DEADLOCK_TIMEOUT = 30.0

#: Generation A is the fixture as written; generation B renames one playlist.
#: The rename is what makes a mixed pair VISIBLE: ``mint_playlist_id`` derives
#: the id from the playlist's path, so B's "renamed top" has an id A's
#: membership rows have never heard of. Serve B's playlist table beside A's
#: membership table and the row for it dangles and is dropped in silence -
#: exactly the corruption that reads as a normal import.
GENERATION_B_XML = FIXTURE_XML.replace('Name="top level"', 'Name="renamed top"')

#: What ``t1``'s playlists are in each generation, worked out by hand from the
#: fixture: it is in the top-level playlist and in ``Alpha / shared name``.
T1_IN_A = (("top level",), ("Alpha", "shared name"))
T1_IN_B = (("renamed top",), ("Alpha", "shared name"))

#: The first playlist's name in each generation, keyed by the basename the
#: manifest records. A committed generation must agree with its own manifest;
#: this table is how every assertion below says so.
BY_SOURCE = {"a.xml": T1_IN_A, "b.xml": T1_IN_B}


def full_paths(refs):
    """``PlaylistRef``s as tuples of path segments, or ``None``."""
    if refs is None:
        return None
    return tuple(ref.full_path for ref in refs)


def write_library(data_dir):
    """A data directory holding just enough ``meta.parquet`` to import against."""
    data_dir.mkdir(parents=True, exist_ok=True)
    pd.DataFrame({"track_id": list(FIXTURE_TRACK_IDS)}).to_parquet(
        data_dir / "meta.parquet", index=False
    )
    return data_dir


@pytest.fixture
def two_generations(tmp_path):
    """``(data_dir, a_xml, b_xml)`` with generation A already imported.

    The two exports are named ``a.xml`` and ``b.xml`` because the manifest
    records the basename, and the basename is how every assertion here tells
    which generation is committed.
    """
    a_xml = tmp_path / "a.xml"
    a_xml.write_text(FIXTURE_XML, encoding="utf-8")
    b_xml = tmp_path / "b.xml"
    b_xml.write_text(GENERATION_B_XML, encoding="utf-8")

    data_dir = write_library(tmp_path / "data")
    import_playlists(a_xml, data_dir=data_dir, now=FIXED_CLOCK)
    return data_dir, a_xml, b_xml


def assert_committed_state_is_coherent(data_dir):
    """The committed generation must be the one its own manifest describes.

    The single invariant this whole file exists to defend, stated once. A
    reader may see either generation; what it may never see is a manifest
    naming one export beside table rows that came from the other, or a pair of
    tables that disagree with each other.

    ONE ``lookup``, NOT TWO ACCESSORS
    ---------------------------------
    ``PlaylistService`` re-reads the manifest on every access, because the
    writer is another process and an index cached for the life of the window is
    an index that never changes. That makes ``service.provenance`` and
    ``service.playlists_for(...)`` two separate observations, and asking for
    the provenance of one generation and the rows of the next is a way to build
    a blend out of two correct answers rather than to detect one. ``lookup``
    checks the pointer once and answers from what it found, which is also what
    the drawer's request does.
    """
    answer = PlaylistService(data_dir).lookup("t1")
    if answer.provenance is None:
        return None

    assert answer.provenance.source_name in BY_SOURCE, (
        f"manifest names an export no generation here wrote: "
        f"{answer.provenance.source_name!r}"
    )
    assert full_paths(answer.playlists) == BY_SOURCE[answer.provenance.source_name], (
        f"the manifest says the tables came from {answer.provenance.source_name}, "
        f"but their rows say otherwise - a blended generation reported as imported"
    )
    return answer.provenance.source_name


# ---------------------------------------------------------------------------
# BLOCKER 1 - the reader must parse the bytes it verified
# ---------------------------------------------------------------------------


class _PausesBeforeReadingATable:
    """Runs ``action`` once, the first time the reader reaches a table's bytes.

    Installed over BOTH ways those bytes can be reached, so it fires at the
    same moment whether the store digests a path and re-opens it or reads the
    bytes once and parses them in memory. It disarms itself before running
    ``action``, so an import performed by the action re-enters nothing.

    The manifest is deliberately not a trigger: the window under test opens
    once the reader has decided WHICH generation it is reading, which is after
    the manifest has been read.
    """

    def __init__(self, data_dir, action):
        self.data_dir = Path(data_dir)
        self.action = action
        self.fired = False

    def _maybe_fire(self, path):
        if self.fired or path is None:
            return
        path = Path(path)
        if path.name == PROVENANCE_FILENAME:
            return
        if path.parent != self.data_dir:
            return
        self.fired = True
        self.action()

    def install(self, monkeypatch):
        real_read_bytes = Path.read_bytes
        real_read_parquet = store.pd.read_parquet

        def read_bytes(inner_self):
            self._maybe_fire(inner_self)
            return real_read_bytes(inner_self)

        def read_parquet(source, *args, **kwargs):
            self._maybe_fire(source if isinstance(source, (str, Path)) else None)
            return real_read_parquet(source, *args, **kwargs)

        monkeypatch.setattr(Path, "read_bytes", read_bytes)
        monkeypatch.setattr(store.pd, "read_parquet", read_parquet)
        return self


class _Interrupted(RuntimeError):
    """A writer that stopped partway through its commit."""


class _DyingOs:
    """The real ``os``, except that ``replace`` stops working after N calls.

    Stands in for a writer that got N of its atomic steps done and then died -
    or, here, for one that is simply not finished yet. Parametrising over N is
    what keeps these probes independent of how many files a given design
    replaces: it says "the other process got this far", not "it replaced the
    playlist table".
    """

    def __init__(self, allow):
        self._allow = allow
        self.calls = 0

    def __getattr__(self, name):
        return getattr(os, name)

    def replace(self, src, dst):
        if self.calls >= self._allow:
            raise _Interrupted(f"stopped before os.replace #{self.calls + 1}")
        self.calls += 1
        return os.replace(src, dst)


def land_generation_b(data_dir, b_xml, allow):
    """Run an import of B that gets ``allow`` of its atomic commit steps done.

    ``allow`` large enough to cover the whole commit is a complete, successful
    import; anything smaller is a writer caught in the middle of one. Both are
    states a reader in another process can be looking at the directory during.
    """
    dying = _DyingOs(allow)
    real_os = store.os
    store.os = dying
    try:
        import_playlists(b_xml, data_dir=data_dir, now=FIXED_CLOCK)
    except _Interrupted:
        pass
    finally:
        store.os = real_os


@pytest.mark.parametrize("writer_got_this_far", [0, 1, 2, 3])
def test_a_writer_landing_while_the_reader_is_open_cannot_blend_two_generations(
    two_generations, monkeypatch, writer_got_this_far
):
    """THE BLOCKER. A reader that has validated generation A must PARSE A.

    The reader is paused at the moment it has committed to A's manifest and has
    not yet read a table byte. A writer then lands - completely, or stopped
    partway through its commit - and the reader is allowed to continue.

    Against a reader that validates a PATH and then re-opens it, the bytes
    under that path have changed in between, and every one of these cases is
    served as a normal import: the manifest still says ``a.xml`` while the rows
    come from ``b.xml``, and where the pair is mixed the dangling membership
    rows are dropped without a word.

    A reader that verifies the bytes it actually parsed cannot do that, and a
    writer that never chooses a name an existing generation is using cannot
    make it try.

    The reader is one ``lookup`` - the drawer's request - because that is the
    unit inside which the answer has to hold together. By the time it returns,
    the pointer on disk may well name B; what this asserts is that the answer
    built from A's manifest is built from A's rows, whole.
    """
    data_dir, _, b_xml = two_generations

    _PausesBeforeReadingATable(
        data_dir, lambda: land_generation_b(data_dir, b_xml, writer_got_this_far)
    ).install(monkeypatch)

    answer = PlaylistService(data_dir).lookup("t1")

    assert answer.imported is True, (
        "generation A's committed files were readable when the read began and "
        "nothing may take them away mid-read"
    )
    assert answer.provenance.source_name == "a.xml"
    assert full_paths(answer.playlists) == T1_IN_A


def test_a_committed_table_edited_in_place_is_refused(two_generations):
    """The digest is checked against the bytes that were parsed, so the check
    still has something to say when nothing raced at all.

    A committed generation is immutable because no writer ever picks its name -
    which is a rule the importer keeps, not one the filesystem enforces. A
    restore from backup, a hand edit or a half-written block can still put
    different bytes under a name the manifest names, and this is the guard that
    notices. VALID parquet with exactly the right columns, so the column check
    passes it and only the digest can refuse it.
    """
    data_dir, _, _ = two_generations
    playlists_pq, _ = committed_table_paths(data_dir)

    frame = pd.read_parquet(playlists_pq)
    frame.loc[0, "name"] = "edited by hand"
    frame.to_parquet(playlists_pq, index=False)

    service = PlaylistService(data_dir)
    assert service.imported is False
    assert service.lookup("t1").playlists is None


class _SwapsTheFileBeforeTheSECONDReadOfIt:
    """Counts the reads of one file, and changes it under the second one.

    A reader that takes its digest from one read and its rows from another is
    exposed at exactly one instant - between the two - and WHICH two depends on
    how it happens to be written:

    * ``digest_file(path)`` then ``read_parquet(path)``;
    * ``digest_file(path)`` then ``read_bytes()`` then a parse of the buffer;
    * ``read_bytes()`` then ``read_parquet(path)``.

    An earlier version of this fired on the first ``read_parquet`` and so only
    covered the first and third of those. The second slipped through, because
    by the time a parse was reached the damage was being done to a file whose
    bytes had already been taken. So this counts instead of naming a seam:
    every route to a file's bytes is hooked, and the file changes just before
    the SECOND of them, whichever two they turn out to be.

    A reader that reads once never reaches a second read and never sees a
    swapped byte. That is exactly the property under test, and it is why the
    guard at the end of the test is "the file was read at all" rather than "the
    swap fired".
    """

    def __init__(self, path, replacement):
        self.path = Path(path)
        self.replacement = replacement
        self.reads = 0
        self.swapped = False

    def _count(self, path):
        if path is None or Path(path) != self.path:
            return
        self.reads += 1
        if self.reads >= 2 and not self.swapped:
            self.swapped = True
            self.path.write_bytes(self.replacement)

    def install(self, monkeypatch):
        real_digest = store.digest_file
        real_read_bytes = Path.read_bytes
        real_read_parquet = store.pd.read_parquet

        def digest_file(path):
            self._count(path)
            return real_digest(path)

        def read_bytes(inner_self):
            self._count(inner_self)
            return real_read_bytes(inner_self)

        def read_parquet(source, *args, **kwargs):
            self._count(source if isinstance(source, (str, Path)) else None)
            return real_read_parquet(source, *args, **kwargs)

        monkeypatch.setattr(store, "digest_file", digest_file)
        monkeypatch.setattr(Path, "read_bytes", read_bytes)
        monkeypatch.setattr(store.pd, "read_parquet", read_parquet)
        return self


def test_the_digest_describes_the_bytes_THAT_WERE_PARSED(two_generations, monkeypatch):
    """Round 2's blocker, restated at the level of one function.

    Immutable generation names are what actually stop a writer from changing a
    table under a reader, and they are load-bearing: with them in place, a
    reader that hashed the path and then re-opened it would pass every other
    test in this file. So the rule "the digest describes the bytes that were
    parsed" is asserted here directly - the file changes between any two reads
    of it, so a reader that needs two gets bytes its digest never described.

    A reader that reads once has no such instant, which is the whole point; the
    test is what stops one being reintroduced by somebody who reasonably
    observes that immutable names make the second read harmless.
    """
    data_dir, _, b_xml = two_generations
    playlists_pq, _ = committed_table_paths(data_dir)

    # A VALID playlist table, right columns, different rows: only a digest can
    # tell it apart from the one the manifest names.
    elsewhere = write_library(data_dir.parent / "elsewhere")
    import_playlists(b_xml, data_dir=elsewhere, now=FIXED_CLOCK)
    other_generation = committed_table_paths(elsewhere)[0].read_bytes()

    watcher = _SwapsTheFileBeforeTheSECONDReadOfIt(
        playlists_pq, other_generation
    ).install(monkeypatch)

    answer = PlaylistService(data_dir).lookup("t1")

    assert watcher.reads, "the reader never opened the playlist table at all"
    assert answer.imported is True
    assert full_paths(answer.playlists) == T1_IN_A


# ---------------------------------------------------------------------------
# BLOCKER 2 - two writers must never commit each other's tables
# ---------------------------------------------------------------------------


class _StepsTwoWritersThroughEachOther:
    """Pauses each import once, right after it has written its first table.

    The interleaving is fixed and injected, never timed:

    1. writer A writes its first table and stops;
    2. writer B writes its first table - over the same name, if the design
       gives both writers the same name - and stops;
    3. A is released and runs to completion;
    4. B is released and runs to completion.

    Step 2 inside step 1's window is the whole probe: any digest A takes after
    that point describes bytes B produced.
    """

    def __init__(self):
        self.a_wrote = threading.Event()
        self.b_wrote = threading.Event()
        self.release_a = threading.Event()
        self.release_b = threading.Event()
        self._paused = set()

    def install(self, monkeypatch):
        real_to_parquet = pd.DataFrame.to_parquet
        gate = {
            "writer-a": (self.a_wrote, self.release_a),
            "writer-b": (self.b_wrote, self.release_b),
        }

        def to_parquet(frame, *args, **kwargs):
            result = real_to_parquet(frame, *args, **kwargs)
            name = threading.current_thread().name
            if name in gate and name not in self._paused:
                self._paused.add(name)
                wrote, release = gate[name]
                wrote.set()
                assert release.wait(DEADLOCK_TIMEOUT), f"{name} was never released"
            return result

        monkeypatch.setattr(pd.DataFrame, "to_parquet", to_parquet)
        return self


def test_two_concurrent_writers_never_commit_each_others_tables(
    tmp_path, monkeypatch
):
    """THE BLOCKER. Whatever is committed must be one writer's own work.

    Two imports of two different exports, stepped through each other so that
    B's first table is written while A is between writing its own and looking
    at it. Staging both to one shared name puts B's bytes under the name A is
    about to digest and then commit, so A returns successfully having published
    B's playlist table beneath A's manifest - and because the digest was taken
    after the overwrite, the digests agree and a reader trusts the result.

    Neither writer needs to win. What is asserted is that the directory ends up
    describing itself: the export the manifest names is the export the rows
    came from.
    """
    a_xml = tmp_path / "a.xml"
    a_xml.write_text(FIXTURE_XML, encoding="utf-8")
    b_xml = tmp_path / "b.xml"
    b_xml.write_text(GENERATION_B_XML, encoding="utf-8")
    data_dir = write_library(tmp_path / "data")

    steps = _StepsTwoWritersThroughEachOther().install(monkeypatch)
    failures = {}

    def run(name, xml):
        try:
            import_playlists(xml, data_dir=data_dir, now=FIXED_CLOCK)
        except BaseException as error:  # noqa: BLE001 - reported, not swallowed
            failures[name] = error

    writer_a = threading.Thread(target=run, args=("a", a_xml), name="writer-a")
    writer_b = threading.Thread(target=run, args=("b", b_xml), name="writer-b")

    writer_a.start()
    assert steps.a_wrote.wait(DEADLOCK_TIMEOUT), "writer A never wrote a table"
    writer_b.start()
    assert steps.b_wrote.wait(DEADLOCK_TIMEOUT), "writer B never wrote a table"

    steps.release_a.set()
    writer_a.join(DEADLOCK_TIMEOUT)
    steps.release_b.set()
    writer_b.join(DEADLOCK_TIMEOUT)
    assert not writer_a.is_alive() and not writer_b.is_alive()

    committed = assert_committed_state_is_coherent(data_dir)
    assert committed is not None, (
        "both writers ran to completion, so one of the two generations has to "
        f"be committed (writer errors: {failures})"
    )


def test_two_concurrent_writers_both_succeed_and_each_commits_its_own(
    tmp_path, monkeypatch
):
    """Sharper: a writer that RETURNS has published its own export, not a rival's.

    The test above accepts a writer that fails, because a failure is at least
    honest. This one does not: two imports that never touch the same file have
    no reason to interfere, so both must succeed, and the manifest must be the
    one written by whichever committed last.
    """
    a_xml = tmp_path / "a.xml"
    a_xml.write_text(FIXTURE_XML, encoding="utf-8")
    b_xml = tmp_path / "b.xml"
    b_xml.write_text(GENERATION_B_XML, encoding="utf-8")
    data_dir = write_library(tmp_path / "data")

    steps = _StepsTwoWritersThroughEachOther().install(monkeypatch)
    summaries = {}
    failures = {}

    def run(name, xml):
        try:
            summaries[name] = import_playlists(xml, data_dir=data_dir, now=FIXED_CLOCK)
        except BaseException as error:  # noqa: BLE001
            failures[name] = error

    writer_a = threading.Thread(target=run, args=("a", a_xml), name="writer-a")
    writer_b = threading.Thread(target=run, args=("b", b_xml), name="writer-b")

    writer_a.start()
    assert steps.a_wrote.wait(DEADLOCK_TIMEOUT)
    writer_b.start()
    assert steps.b_wrote.wait(DEADLOCK_TIMEOUT)
    steps.release_a.set()
    writer_a.join(DEADLOCK_TIMEOUT)
    steps.release_b.set()
    writer_b.join(DEADLOCK_TIMEOUT)

    assert not failures, f"neither import had a reason to fail: {failures}"
    # B was released last, so B's manifest is the one on disk.
    assert assert_committed_state_is_coherent(data_dir) == "b.xml"
    # ...and A's own record still describes what A wrote, which is the claim
    # its caller printed to the terminal.
    assert summaries["a"].provenance.source_name == "a.xml"


class _InterruptsTheInstantTheCommitLands:
    """The real ``os``, except that ``replace`` returns and then Ctrl-C lands.

    The ambiguous instant, and the only one that matters: the rename has TAKEN
    EFFECT and an asynchronous exception surfaces before the caller can record
    that it did. CPython delivers a pending signal at a bytecode boundary, so
    there is no line of Python that reliably runs between the syscall
    returning and the ``KeyboardInterrupt`` being raised - which is why "set a
    flag on the next line" is not a fix and this double raises from inside the
    call rather than after it.

    A SIGKILL is not this case: it runs no handler at all, so it cannot undo
    anything. Only a CAUGHT exception can.
    """

    def __getattr__(self, name):
        return getattr(os, name)

    def replace(self, src, dst):
        os.replace(src, dst)
        raise KeyboardInterrupt("the user pressed Ctrl-C")


def test_a_commit_that_took_effect_is_never_undone_by_its_own_cleanup(
    two_generations
):
    """THE BLOCKER. Cleanup may not reach a file the manifest now names.

    ``import-playlists`` is the command the drawer tells the user to run in a
    terminal, so Ctrl-C is an ordinary thing to press at an arbitrary point in
    it - and the point that matters is the one where the pointer has already
    moved. Deleting the new tables there leaves the manifest naming two files
    that are gone, which every reader reports as "nothing imported": the user
    has interrupted an import and lost the import they already had.
    """
    data_dir, _, b_xml = two_generations
    previous = committed_table_paths(data_dir)

    real_os = store.os
    store.os = _InterruptsTheInstantTheCommitLands()
    try:
        with pytest.raises(KeyboardInterrupt):
            import_playlists(b_xml, data_dir=data_dir, now=FIXED_CLOCK)
    finally:
        store.os = real_os

    committed = committed_table_paths(data_dir)
    assert committed is not None
    assert committed != previous, "the interrupted import did commit, or nothing is proved"
    assert all(path.is_file() for path in committed), (
        "the manifest names these and the interrupt handler deleted them"
    )
    assert assert_committed_state_is_coherent(data_dir) == "b.xml"


def test_a_commit_that_did_NOT_take_effect_still_cleans_up_after_itself(
    two_generations
):
    """The other side of the same rule, so the fix cannot be "never clean up".

    ``rename`` changes nothing when it fails, so an ``OSError`` out of the
    commit is proof the pointer did not move - and the two tables this import
    claimed are still nobody's but its own. They go, as they always did.
    """
    data_dir, _, b_xml = two_generations
    before = sorted(path.name for path in data_dir.iterdir())

    class _CommitFails:
        def __getattr__(self, name):
            return getattr(os, name)

        def replace(self, src, dst):
            raise OSError("no space left on device")

    real_os = store.os
    store.os = _CommitFails()
    try:
        with pytest.raises(OSError):
            import_playlists(b_xml, data_dir=data_dir, now=FIXED_CLOCK)
    finally:
        store.os = real_os

    assert sorted(path.name for path in data_dir.iterdir()) == before
    assert assert_committed_state_is_coherent(data_dir) == "a.xml"


# ---------------------------------------------------------------------------
# The real case: a separate PROCESS, running the shipped command
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parents[2]
CLI = REPO_ROOT / "src" / "cosine_companion.py"

#: The shipped command is a typer CLI, and typer is a declared runtime
#: dependency (``requirements.txt:16``) rather than a test one. A minimal
#: environment - numpy, pandas, pyarrow, lxml, pytest and nothing else - can
#: still run every other test in this file, so these three skip there with a
#: stated reason instead of failing. CI installs typer precisely so they do NOT
#: skip: the multi-process case is the real one, and a guarantee that is only
#: ever checked on a developer's machine is not a guarantee.
needs_the_cli = pytest.mark.skipif(
    importlib.util.find_spec("typer") is None,
    reason=(
        "the shipped import-playlists command needs typer, which this "
        "environment has not got. Install it to run the multi-process tests: "
        "pip install typer"
    ),
)


def run_import_cli(xml, data_dir):
    """Run the shipped ``import-playlists`` command in a real subprocess."""
    return subprocess.run(
        [
            sys.executable,
            str(CLI),
            "import-playlists",
            "--data-dir",
            str(data_dir),
            str(xml),
        ],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        timeout=300,
    )


@needs_the_cli
def test_the_shipped_command_writes_to_the_data_dir_it_is_given(tmp_path):
    """``--data-dir`` exists, because otherwise none of the below can be tested
    without writing into the developer's real library."""
    xml = tmp_path / "a.xml"
    xml.write_text(FIXTURE_XML, encoding="utf-8")
    data_dir = write_library(tmp_path / "data")

    result = run_import_cli(xml, data_dir)

    assert result.returncode == 0, result.stderr
    assert str(data_dir) in result.stdout
    assert PlaylistService(data_dir).provenance.source_name == "a.xml"


@needs_the_cli
def test_a_real_import_process_landing_mid_read_cannot_blend_two_generations(
    two_generations, monkeypatch
):
    """The multi-process case, made deterministic from the reader's side.

    The writer is a genuine ``subprocess`` running the shipped command - no
    injection, no patching, the same binary the drawer tells the user to run.
    The interleaving is injected on the READER side only, which is legitimate
    because the reader is this process: it is paused at the seam and the real
    import is run to completion inside that pause.

    This is the interleaving no lock can prevent, because there is no lock two
    processes both hold.
    """
    data_dir, _, b_xml = two_generations
    results = []

    def import_in_another_process():
        results.append(run_import_cli(b_xml, data_dir))

    _PausesBeforeReadingATable(data_dir, import_in_another_process).install(monkeypatch)

    answer = PlaylistService(data_dir).lookup("t1")

    assert results and results[0].returncode == 0, results and results[0].stderr
    assert answer.imported is True
    assert answer.provenance.source_name == "a.xml"
    assert full_paths(answer.playlists) == T1_IN_A

    # And the next reader sees the new generation, whole.
    assert assert_committed_state_is_coherent(data_dir) == "b.xml"


@needs_the_cli
def test_a_reader_looping_across_real_imports_never_observes_a_blend(tmp_path):
    """A free-running reader against a sequence of real import processes.

    Nothing is injected into the store and the reader is never paused: it reads
    as fast as it can while a genuine ``import-playlists`` subprocess commits
    underneath it, and every single observation has to satisfy the one
    invariant - either nothing is imported, or the generation on disk is the
    one its own manifest describes.

    THE BARRIER IS ON THE WRITER, AND IT IS WHAT MAKES THIS CI-SAFE
    ---------------------------------------------------------------
    The ordering assertion at the bottom is the half of this test that says the
    reader really did read ACROSS the commits rather than only before and
    after them. Left to the scheduler it is a coin toss: a reader thread that
    does not happen to run during the moments b.xml is current produces
    ``["a.xml"]`` from a store that behaved perfectly, and the test fails for
    something that is not a defect. That is not a hypothetical - descheduling
    the reader across the middle commit reproduces it exactly, and a test that
    can fail on correct code is a test that gets deleted.

    It is a RARE failure rather than a common one, which is worse and not
    better. The b.xml generation stays current for as long as the next import
    takes to start a Python interpreter, so the reader has hundreds of
    milliseconds to sample a loop that takes a few - 15 runs of the unbarriered
    shape on a machine with every core saturated did not produce it once. A
    test that fails twice a year is a test nobody trusts and everybody re-runs
    until it goes green.

    So the next import does not START until the reader has been seen to observe
    the previous one. That is a barrier on the WRITER, not on the reader: the
    reader is never held still, the import still lands underneath a running
    read loop, and the interleaving under test is untouched. All it removes is
    the possibility of a generation coming and going unlooked-at, which is the
    only thing the assertion was ever sensitive to.

    An import that the reader never observes now fails as a timeout naming the
    commit it stopped at, rather than as a mismatched list at the end.
    """
    a_xml = tmp_path / "a.xml"
    a_xml.write_text(FIXTURE_XML, encoding="utf-8")
    b_xml = tmp_path / "b.xml"
    b_xml.write_text(GENERATION_B_XML, encoding="utf-8")
    data_dir = write_library(tmp_path / "data")

    observed = []
    reads = [0]
    stop = threading.Event()
    problems = []
    progress = threading.Condition()

    def read_until_stopped():
        while not stop.is_set():
            reads[0] += 1
            try:
                seen = assert_committed_state_is_coherent(data_dir)
            except AssertionError as error:
                with progress:
                    problems.append(error)
                    progress.notify_all()
                return
            if seen is not None and (not observed or observed[-1] != seen):
                with progress:
                    observed.append(seen)
                    progress.notify_all()

    reader = threading.Thread(target=read_until_stopped, name="reader")
    reader.start()
    try:
        for index, xml in enumerate((a_xml, b_xml, a_xml)):
            assert run_import_cli(xml, data_dir).returncode == 0
            with progress:
                landed = progress.wait_for(
                    lambda: problems or len(observed) > index, DEADLOCK_TIMEOUT
                )
            assert not problems, problems[0]
            assert landed, (
                f"the reader never observed commit #{index + 1} ({xml.name}); "
                f"it is still on {observed}"
            )
    finally:
        stop.set()
        reader.join(DEADLOCK_TIMEOUT)

    assert not problems, problems[0]
    assert reads[0] > 10, f"the reader barely ran ({reads[0]} reads)"
    assert observed == ["a.xml", "b.xml", "a.xml"], (
        f"the reader did not straddle all three commits: {observed}"
    )


# ---------------------------------------------------------------------------
# THE LONG-LIVED READER - one service, held for the life of the window
# ---------------------------------------------------------------------------
#
# ``web/host.py:77`` builds ONE ``PlaylistService`` inside ``build_api`` and the
# window holds it until it closes, so every test above that builds a fresh
# service after an import is measuring a process that has just started. The
# workflow this feature is for does the opposite: the drawer names the command,
# the user runs it in a terminal, and the app they run it for is still open.


@needs_the_cli
def test_a_long_lived_service_sees_an_import_committed_by_another_process(tmp_path):
    """The feature's core loop, with the reader that the app actually has.

    Nothing imported, so the drawer shows the call-to-action; the user runs the
    command it names; the SAME service must answer with the playlists. A
    service that latches "nothing imported" on its first miss shows that screen
    until the app is restarted, which is the one thing the call-to-action
    promises will not happen.
    """
    a_xml = tmp_path / "a.xml"
    a_xml.write_text(FIXTURE_XML, encoding="utf-8")
    data_dir = write_library(tmp_path / "data")

    service = PlaylistService(data_dir)
    assert service.imported is False, "nothing has been imported yet"

    assert run_import_cli(a_xml, data_dir).returncode == 0

    assert service.imported is True, (
        "the import succeeded in another process and this service is the one "
        "the window is holding - it has to notice"
    )
    assert service.provenance.source_name == "a.xml"
    assert full_paths(service.playlists_for("t1")) == T1_IN_A


@needs_the_cli
def test_a_long_lived_service_follows_a_RE_import_from_another_process(
    two_generations
):
    """Not only the first import: every one after it, too.

    The service already holds generation A's reverse index. A second import in
    another process commits B, and the same instance must answer from B - both
    the provenance the drawer prints and the rows it lists.
    """
    data_dir, _, b_xml = two_generations

    service = PlaylistService(data_dir)
    assert service.provenance.source_name == "a.xml"
    assert full_paths(service.playlists_for("t1")) == T1_IN_A

    assert run_import_cli(b_xml, data_dir).returncode == 0

    assert service.provenance.source_name == "b.xml"
    assert full_paths(service.playlists_for("t1")) == T1_IN_B


@needs_the_cli
def test_the_staleness_prompt_clears_when_the_user_runs_the_command_it_names(
    tmp_path
):
    """The staleness prompt, end to end, against one long-lived service.

    ``staleness()`` re-hashes the export on every call, so it notices the
    re-export immediately - and then names a command whose effect the same
    service could not see. Detecting a change it cannot act on is worse than
    not detecting it: the drawer tells the user to run something, they run it,
    and the prompt stays up.

    One path, rewritten in place, because that is what re-exporting from
    Rekordbox does.
    """
    xml = tmp_path / "library_export.xml"
    xml.write_text(FIXTURE_XML, encoding="utf-8")
    data_dir = write_library(tmp_path / "data")
    assert run_import_cli(xml, data_dir).returncode == 0

    service = PlaylistService(data_dir)
    assert service.staleness().stale is False

    xml.write_text(GENERATION_B_XML, encoding="utf-8")

    verdict = service.staleness()
    assert verdict.stale is True
    assert IMPORT_COMMAND in verdict.reason

    assert run_import_cli(xml, data_dir).returncode == 0

    assert service.staleness().stale is False, (
        "the prompt named a command, the user ran it, and it worked - the "
        "service that raised the prompt has to stand down"
    )
    assert full_paths(service.playlists_for("t1")) == T1_IN_B


# ---------------------------------------------------------------------------
# Migration off the flat-file layout
# ---------------------------------------------------------------------------


@pytest.fixture
def schema_2_install(tmp_path):
    xml = tmp_path / "a.xml"
    xml.write_text(FIXTURE_XML, encoding="utf-8")
    return write_schema_2_layout(write_library(tmp_path / "data"), xml), xml


def test_a_schema_2_install_reads_as_nothing_imported(schema_2_install):
    """Migration is one re-import, and the state in between is the one whose
    screen already names the command that fixes it - not an error.

    What the USER sees in that state is asserted end to end over the real
    endpoint in ``tests/web/test_api_playlists.py``; this is the service-level
    half.
    """
    data_dir, _ = schema_2_install

    service = PlaylistService(data_dir)

    assert service.imported is False
    assert service.lookup("t1").playlists is None
    assert service.lookup("t1").provenance is None


def test_re_importing_a_schema_2_install_restores_the_playlists(schema_2_install):
    """And the command the drawer names has to actually repair it."""
    data_dir, xml = schema_2_install

    import_playlists(xml, data_dir=data_dir, now=FIXED_CLOCK)

    service = PlaylistService(data_dir)
    assert service.imported is True
    assert full_paths(service.playlists_for("t1")) == T1_IN_A


# ---------------------------------------------------------------------------
# Reaping: when a generation nobody points at is allowed to go
# ---------------------------------------------------------------------------


def age(path, seconds):
    """Backdate a file's mtime, which is what the reaper reads."""
    stamp = os.stat(path).st_mtime - seconds
    os.utime(path, (stamp, stamp))
    return path


def age_everything(data_dir, seconds=REAP_GRACE_SECONDS + 60):
    for path in data_dir.iterdir():
        age(path, seconds)


def test_a_superseded_generation_survives_one_more_import_and_then_goes(
    two_generations
):
    """The reaping cadence, stated as the two steps it actually has.

    Reaping runs at the START of an import, never at the end of the one that
    supersedes a generation: a reader in another process may have read the
    previous manifest a microsecond ago and be about to open the files it
    names, so deleting them there would put the race back with extra steps.

    Because the manifest is still the previous one when the reaper runs, the
    generation being superseded is protected during that import too, and goes
    at the one after. That extra cycle is free margin - the steady state is two
    generations on disk, ~66 KB at the real export's size.
    """
    data_dir, a_xml, b_xml = two_generations
    superseded = committed_table_paths(data_dir)
    age_everything(data_dir)

    import_playlists(b_xml, data_dir=data_dir, now=FIXED_CLOCK)

    assert all(path.is_file() for path in superseded), (
        "the manifest still named these when the reaper ran"
    )
    age_everything(data_dir)

    import_playlists(a_xml, data_dir=data_dir, now=FIXED_CLOCK)

    assert not any(path.exists() for path in superseded)
    assert all(path.is_file() for path in committed_table_paths(data_dir))


def test_the_directory_holds_at_most_two_generations(two_generations):
    """Six imports, all of them older than the grace by the time the next one
    runs: the live generation and the one before it, and nothing else."""
    data_dir, a_xml, b_xml = two_generations

    for xml in (b_xml, a_xml, b_xml, a_xml, b_xml):
        age_everything(data_dir)
        import_playlists(xml, data_dir=data_dir, now=FIXED_CLOCK)

    tables = sorted(path.name for path in data_dir.glob("*.parquet"))
    assert len(tables) == 4 + 1, tables  # two generations, plus meta.parquet
    assert sorted(path.name for path in data_dir.iterdir()) == sorted(
        [*tables, PROVENANCE_FILENAME]
    )


def test_the_generation_the_manifest_names_is_never_reaped(two_generations):
    """However old it is. Age is what makes an UNREFERENCED file safe to
    delete; it is not on its own a reason to delete anything."""
    data_dir, _, _ = two_generations
    live = committed_table_paths(data_dir)
    age_everything(data_dir, REAP_GRACE_SECONDS * 100)

    removed = reap_superseded_generations(data_dir)

    assert removed == []
    assert all(path.is_file() for path in live)
    assert PlaylistService(data_dir).imported is True


def test_a_generation_COMMITTED_WHILE_THE_REAPER_RUNS_is_not_deleted(
    two_generations, monkeypatch
):
    """THE BLOCKER. Protection read once, up front, is protection of the past.

    The reaper decides what is protected, and only then starts unlinking. A
    writer that commits inside that gap has published a generation the reaper
    has never heard of - and the reaper is holding a list that says those two
    files belong to nobody.

    The interleaving is injected at the seam where the protected set is read:
    the real set is captured (naming generation A, which is the manifest at
    that instant), a REAL import of B runs to completion, and the stale set is
    then handed back to the loop that does the unlinking. Ageing stands in for
    B having stalled long enough to be past the grace, which is the other half
    of the reviewer's interleaving and the only part a clock would otherwise
    decide.

    The result on an unfixed reaper is the worst state this module has: a
    manifest naming a generation whose files are gone, with the PREVIOUS
    generation's files still on disk and referenced by nothing.
    """
    data_dir, _, b_xml = two_generations
    age_everything(data_dir)

    real_protected = store._protected_table_names
    landed = []

    def snapshot_then_let_b_commit(directory):
        protected = real_protected(directory)
        if not landed:
            landed.append(True)
            import_playlists(b_xml, data_dir=data_dir, now=FIXED_CLOCK)
            age_everything(data_dir)
        return protected

    monkeypatch.setattr(store, "_protected_table_names", snapshot_then_let_b_commit)

    reap_superseded_generations(data_dir)

    assert landed, "the reaper never read the protected set, so nothing was proved"
    live = committed_table_paths(data_dir)
    assert live is not None
    assert all(path.is_file() for path in live), (
        "the manifest names these two files and the reaper deleted them"
    )
    assert assert_committed_state_is_coherent(data_dir) == "b.xml"


def test_a_manifest_that_cannot_be_READ_protects_everything(two_generations):
    """Fail closed. An unreadable pointer is not a pointer that names nothing.

    ``_protected_table_names`` parses the manifest loosely on purpose, so that
    a record from a schema this build cannot interpret still protects its own
    files. A record it cannot even PARSE has to protect more, not less: the
    reaper knows it has no idea what is live, and the only safe answer to that
    is to delete nothing. Reaping is tidiness; the files are the user's data.
    """
    data_dir, _, _ = two_generations
    live = committed_table_paths(data_dir)
    age_everything(data_dir, REAP_GRACE_SECONDS * 10)
    playlist_manifest_path(data_dir).write_text("{ truncated", encoding="utf-8")

    removed = reap_superseded_generations(data_dir)

    assert removed == [], f"an unreadable manifest is not a licence to delete: {removed}"
    assert all(path.is_file() for path in live)


def test_a_manifest_that_disappears_mid_reap_protects_everything(two_generations):
    """The same rule at the other seam: unreadable when the unlink is decided.

    Re-reading the manifest before each unlink is what makes the reaper safe,
    and it introduces a read that can itself fail. It must fail the same way -
    closed - rather than falling back to "nothing is protected".
    """
    data_dir, _, _ = two_generations
    live = committed_table_paths(data_dir)
    age_everything(data_dir, REAP_GRACE_SECONDS * 10)

    real_read_text = Path.read_text

    def read_text(inner_self, *args, **kwargs):
        if inner_self.name == PROVENANCE_FILENAME:
            raise OSError("too many open files")
        return real_read_text(inner_self, *args, **kwargs)

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(Path, "read_text", read_text)
        removed = reap_superseded_generations(data_dir)

    assert removed == []
    assert all(path.is_file() for path in live)


def test_another_writers_in_flight_generation_is_protected_by_the_grace(
    two_generations
):
    """The reason the grace period is correctness and not tidiness.

    Writer B's tables exist before B's manifest does, so to a reaper running
    inside writer A they are files no manifest names - which is the exact
    description of debris. They are also seconds old, and that is what saves
    them: without the grace, the two importers this whole design exists to keep
    out of each other's way would delete each other's work.
    """
    data_dir, _, _ = two_generations
    in_flight = data_dir / f"{PLAYLISTS_STEM}.{'a1' * 16}.parquet"
    in_flight.write_bytes(b"writer B is still working on this")

    removed = reap_superseded_generations(data_dir)

    assert removed == []
    assert in_flight.is_file()

    # ...and once it is old enough to be nobody's, it goes.
    age(in_flight, REAP_GRACE_SECONDS + 60)
    assert reap_superseded_generations(data_dir) == [in_flight]


def test_the_reaper_never_touches_a_file_this_scheme_did_not_write(two_generations):
    """It runs inside an import, in the directory holding the user's library.

    ``meta.parquet``, the exports, ``settings.json``, the index files: all aged
    well past the grace and none of them matching the pattern this scheme
    writes. A reaper that deleted by age alone would eat the library.
    """
    data_dir, _, _ = two_generations
    bystanders = {}
    for name in ("meta.parquet", "embeddings.parquet", "index.npy", "ids.json",
                 "settings.json", "library_export.xml", "playlists.parquet.bak"):
        path = data_dir / name
        path.write_bytes(f"the contents of {name}".encode())
        bystanders[path] = path.read_bytes()
    age_everything(data_dir, REAP_GRACE_SECONDS * 10)

    reap_superseded_generations(data_dir)

    assert all(path.read_bytes() == raw for path, raw in bystanders.items())


def test_the_flat_schema_2_tables_are_cleared_by_the_FIRST_import(schema_2_install):
    """Migration leaves two files this build can no longer read.

    They are derived, re-importable, and named by nothing, so they are cleared
    by the first import after the upgrade rather than left looking current
    forever. Nothing is lost that the import about to run does not replace.

    NOTHING IS BACKDATED HERE, AND THAT IS THE POINT
    ------------------------------------------------
    An earlier version of this test aged the directory past the grace first,
    which quietly conceded that "the first import clears them" was false: on a
    real upgrade those two files are minutes old, so the grace kept them and
    the user's data directory held two stale tables that looked current until
    the next import. The grace exists to protect an in-flight writer's claim,
    and no writer in this build can ever be in flight on a name it does not
    write - so these two are exempt from it by name.
    """
    data_dir, xml = schema_2_install
    flat = [data_dir / name for name in LEGACY_TABLE_FILENAMES]
    assert all(path.is_file() for path in flat)
    assert all(
        path.stat().st_mtime > time.time() - REAP_GRACE_SECONDS for path in flat
    ), "these must be INSIDE the grace, or the test has aged them after all"

    import_playlists(xml, data_dir=data_dir, now=FIXED_CLOCK)

    assert not any(path.exists() for path in flat)
    assert PlaylistService(data_dir).imported is True


def test_a_manifest_this_build_cannot_READ_still_protects_its_own_tables(
    two_generations
):
    """Version skew must not turn one build into the other's reaper.

    A manifest from a newer schema reads as "nothing imported" here - correctly,
    since this build cannot interpret it - but it still NAMES two files, and
    those files belong to somebody. The reaper parses the manifest loosely for
    exactly this reason: its job is to delete debris, not to enforce a version.
    """
    data_dir, _, _ = two_generations
    live = committed_table_paths(data_dir)
    manifest = playlist_manifest_path(data_dir)
    raw = json.loads(manifest.read_text(encoding="utf-8"))
    raw["schema_version"] = 99
    manifest.write_text(json.dumps(raw), encoding="utf-8")
    age_everything(data_dir, REAP_GRACE_SECONDS * 10)

    removed = reap_superseded_generations(data_dir)

    assert removed == []
    assert all(path.is_file() for path in live)


def test_staged_manifest_debris_is_reaped(two_generations):
    """What a SIGKILL between writing the staged manifest and replacing it
    leaves. Nothing reads it; it should not accumulate either."""
    data_dir, _, _ = two_generations
    debris = data_dir / f"{PROVENANCE_FILENAME}.{'f0' * 16}{STAGING_SUFFIX}"
    debris.write_text("{}", encoding="utf-8")
    age(debris, REAP_GRACE_SECONDS + 60)

    assert reap_superseded_generations(data_dir) == [debris]


def test_a_reader_holding_a_reaped_manifest_gets_nothing_rather_than_a_blend(
    two_generations
):
    """The documented cost of reaping, pinned so it stays the documented one.

    A reader that read a manifest, lost the race with a reap, and only then
    opened the files it names finds them gone. That is ``FileNotFoundError``
    inside ``read_playlist_tables``, which is "nothing imported" - the drawer's
    import call-to-action, repaired by the next ``reload``. It is never half a
    generation, because a generation's files are never written twice.
    """
    data_dir, a_xml, b_xml = two_generations
    stale_manifest = read_provenance(data_dir)
    for xml in (b_xml, a_xml):
        age_everything(data_dir)
        import_playlists(xml, data_dir=data_dir, now=FIXED_CLOCK)

    assert read_playlist_tables(data_dir, stale_manifest) is None
    # The reader's NEXT read is simply the generation that is there now.
    assert assert_committed_state_is_coherent(data_dir) == "a.xml"


# ---------------------------------------------------------------------------
# What makes a collision impossible rather than unlikely
# ---------------------------------------------------------------------------


def test_two_writers_that_mint_the_same_id_still_get_different_names(
    tmp_path, monkeypatch
):
    """``uuid4`` is why a second attempt is never needed. ``O_EXCL`` is why the
    guarantee holds anyway.

    The id scheme is forced to collide - the same hex handed out twice - which
    is the one thing ``uuid4`` will not do on its own and therefore the one
    thing no unmutated test can exercise. The claim is a single
    ``O_CREAT | O_EXCL`` syscall, so the kernel picks the winner: the second
    caller gets ``FileExistsError``, mints again, and ends up somewhere else.
    Without it, "cannot collide" would be a statement about probability.
    """
    import core.playlist_store as store

    data_dir = write_library(tmp_path / "data")
    minted = iter(["ab" * 16, "ab" * 16, "cd" * 16])
    monkeypatch.setattr(
        store.uuid, "uuid4", lambda: type("U", (), {"hex": next(minted)})()
    )

    first = store._claim_generation(data_dir)
    second = store._claim_generation(data_dir)

    assert first[0] == "ab" * 16
    assert second[0] == "cd" * 16
    assert {first[1], first[2]}.isdisjoint({second[1], second[2]})
    assert all(path.is_file() for path in (*first[1:], *second[1:]))


def test_a_half_claimed_generation_leaves_no_file_behind(tmp_path, monkeypatch):
    """Both names are claimed before either is written, so a generation is
    all-or-nothing from the moment it exists: losing the race on the SECOND
    name must not leave the first one claimed forever."""
    import core.playlist_store as store

    data_dir = write_library(tmp_path / "data")
    # Somebody else already holds this generation's membership name.
    squatted = data_dir / f"{MEMBERSHIP_STEM}.{'ab' * 16}.parquet"
    squatted.write_bytes(b"someone else got here first")
    minted = iter(["ab" * 16, "cd" * 16])
    monkeypatch.setattr(
        store.uuid, "uuid4", lambda: type("U", (), {"hex": next(minted)})()
    )

    generation, playlists, membership = store._claim_generation(data_dir)

    assert generation == "cd" * 16
    assert not (data_dir / f"{PLAYLISTS_STEM}.{'ab' * 16}.parquet").exists()
    assert squatted.read_bytes() == b"someone else got here first"


# ---------------------------------------------------------------------------
# The manifest is input
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "name",
    [
        "../outside.parquet",
        "/etc/passwd",
        "nested/table.parquet",
        "",
        "..",
    ],
    ids=["parent", "absolute", "nested", "empty", "dotdot"],
)
def test_a_manifest_naming_anything_but_a_plain_basename_is_refused(
    two_generations, name
):
    """The manifest is a file in a directory the user can reach, so what it
    says is input. A record may only ever name a file beside itself; anything
    with a separator in it - or nothing at all - reads as nothing imported
    rather than as an instruction to go and open it."""
    data_dir, _, _ = two_generations
    manifest = playlist_manifest_path(data_dir)
    raw = json.loads(manifest.read_text(encoding="utf-8"))
    raw["playlists_file"] = name
    manifest.write_text(json.dumps(raw), encoding="utf-8")

    assert committed_table_paths(data_dir) is None
    assert PlaylistService(data_dir).imported is False
