#!/usr/bin/env python3
"""Build script for creating standalone Cosine Companion application."""

import argparse
import hashlib
import os
import platform
import subprocess
import sys
from pathlib import Path


ESSENTIA_MODEL_NAME = "discogs_multi_embeddings-effnet-bs64-1.pb"
ESSENTIA_MODEL_PATH = Path("models") / ESSENTIA_MODEL_NAME
ESSENTIA_MODEL_URL = (
    "https://essentia.upf.edu/models/feature-extractors/discogs-effnet/"
    f"{ESSENTIA_MODEL_NAME}"
)
ESSENTIA_MODEL_SIZE = 16_367_182
ESSENTIA_MODEL_SHA256 = (
    "2c964064951217e1e345461cf88884086a21f4bca2ae0d48187ee75edc263cd7"
)
ESSENTIA_MODEL_OUTPUT = "PartitionedCall:1"
ESSENTIA_GRAPHDEF_MARKERS = (
    b"serving_default_melspectrogram",
    b"PartitionedCall",
)


class ModelVerificationError(RuntimeError):
    """The embedding model is absent, corrupt, or not the pinned graph."""


def verify_essentia_model_file(model_path=ESSENTIA_MODEL_PATH):
    """Verify the model's type and exact canonical content without TensorFlow."""
    path = Path(model_path)
    if not path.is_file():
        raise ModelVerificationError(f"Essentia model is missing: {path}")

    try:
        payload = path.read_bytes()
    except OSError as exc:
        raise ModelVerificationError(
            f"Essentia model cannot be read: {path}: {exc}"
        ) from exc

    prefix = payload[:512].lstrip().lower()
    if prefix.startswith((b"<!doctype html", b"<html", b"<head")):
        raise ModelVerificationError(
            f"Essentia model is an HTML response, not a GraphDef: {path}"
        )

    actual_size = len(payload)
    if actual_size != ESSENTIA_MODEL_SIZE:
        raise ModelVerificationError(
            "Essentia model has the wrong size: "
            f"expected {ESSENTIA_MODEL_SIZE} bytes, got {actual_size}: {path}"
        )

    missing_markers = [
        marker.decode("ascii")
        for marker in ESSENTIA_GRAPHDEF_MARKERS
        if marker not in payload
    ]
    if missing_markers:
        raise ModelVerificationError(
            "Essentia model is not the expected TensorFlow GraphDef; missing "
            f"node marker(s) {', '.join(missing_markers)}: {path}"
        )

    actual_sha256 = hashlib.sha256(payload).hexdigest()
    if actual_sha256 != ESSENTIA_MODEL_SHA256:
        raise ModelVerificationError(
            "Essentia model checksum mismatch: "
            f"expected {ESSENTIA_MODEL_SHA256}, got {actual_sha256}: {path}"
        )

    print(
        "✅ Essentia model bytes verified: "
        f"{path} ({actual_size} bytes, sha256 {actual_sha256})"
    )
    return path


def verify_essentia_graphdef(model_path):
    """Have the same Essentia TensorFlow loader used at runtime parse the graph."""
    path = Path(model_path)
    try:
        import essentia.standard as es

        es.TensorflowPredictEffnetDiscogs(
            graphFilename=str(path),
            output=ESSENTIA_MODEL_OUTPUT,
        )
    except Exception as exc:
        raise ModelVerificationError(
            "Essentia could not load the model as a TensorFlow GraphDef with "
            f"output {ESSENTIA_MODEL_OUTPUT}: {path}: {exc}"
        ) from exc

    print(
        "✅ Essentia loaded the TensorFlow GraphDef with output "
        f"{ESSENTIA_MODEL_OUTPUT}: {path}"
    )


def verify_essentia_model(model_path=ESSENTIA_MODEL_PATH):
    """Verify exact bytes, GraphDef structure, and runtime loadability."""
    path = verify_essentia_model_file(model_path)
    verify_essentia_graphdef(path)
    return path


def build_with_pyinstaller():
    """Build the application using PyInstaller with spec file."""
    
    system = platform.system()
    print(f"🔨 Building Cosine Companion for {system}...")
    
    # Check if spec file exists
    spec_file = Path("cosine-companion.spec")
    if not spec_file.exists():
        print("❌ Error: cosine-companion.spec file not found!")
        print("   The spec file is required for building.")
        sys.exit(1)
    
    # Build using spec file
    cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--clean",     # Clean cache
        "--noconfirm", # Overwrite without asking
        str(spec_file)
    ]
    
    # Run PyInstaller
    print(f"Running: {' '.join(cmd)}")
    print(f"Using spec file: {spec_file}")
    print()
    
    result = subprocess.run(cmd)
    
    if result.returncode == 0:
        print("\n" + "=" * 60)
        print("✅ Build successful!")
        print("=" * 60)
        
        if system == "Darwin":
            app_path = Path("dist/Cosine Companion.app")
            if app_path.exists():
                print("\n🍎 macOS Application Bundle Created:")
                print(f"   {app_path}")
                print("\nYou can now run:")
                print("   open 'dist/Cosine Companion.app'")
                print("\nTo distribute:")
                print("   Zip the .app bundle or create a DMG installer")
        elif system == "Windows":
            exe_path = Path("dist/Cosine Companion.exe")
            if exe_path.exists():
                print("\n🪟 Windows Executable Created:")
                print(f"   {exe_path}")
                print("\nYou can now run:")
                print("   .\\dist\\\"Cosine Companion.exe\"")
        elif system == "Linux":
            bin_path = Path("dist/Cosine Companion")
            if bin_path.exists():
                print("\n🐧 Linux Executable Created:")
                print(f"   {bin_path}")
                print("\nYou can now run:")
                print("   ./dist/\"Cosine Companion\"")
    else:
        print("\n❌ Build failed!")
        print("Check the error messages above for details.")
        sys.exit(1)

def check_dependencies():
    """Check if required dependencies are installed."""
    try:
        import PyInstaller
        print("✅ PyInstaller found")
    except ImportError:
        print("❌ PyInstaller not found")
        print("Install it with: pip install pyinstaller")
        return False
    # Verify core runtime deps are present in this interpreter
    required = [
        ("pandas", "pip install pandas"),
        ("numpy", "pip install numpy"),
        ("lxml", "pip install lxml"),
        ("soundfile", "pip install soundfile"),
        ("essentia", "pip install essentia-tensorflow"),
        ("typer", "pip install typer"),
        # The web UI's window. Imported as `webview`, installed as `pywebview`
        # - checking the import name is the only one of the two that proves the
        # build machine can actually collect it.
        ("webview", "pip install pywebview"),
    ]
    ok = True
    for mod, hint in required:
        try:
            __import__(mod)
            print(f"✅ {mod} found")
        except Exception as e:
            print(f"❌ {mod} missing in current Python ({sys.executable}): {e}")
            print(f"   Try: {hint}")
            ok = False
    if not ok:
        print("\nPlease install missing dependencies in this environment and re-run the build.")
        return False
    return True


def _parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="Build Cosine Companion or verify its pinned Essentia model."
    )
    parser.add_argument(
        "--verify-model",
        metavar="PATH",
        type=Path,
        help="verify one model artifact and exit without building",
    )
    return parser.parse_args(argv)


def main(argv=None):
    """Main build script."""
    args = _parse_args(argv)

    if args.verify_model is not None:
        try:
            verify_essentia_model(args.verify_model)
        except ModelVerificationError as exc:
            print(f"❌ Model verification failed: {exc}")
            sys.exit(1)
        return

    print("=" * 60)
    print("Cosine Companion - Application Builder")
    print("=" * 60)
    print()
    print(f"Python: {sys.executable}")
    print(f"CWD: {os.getcwd()}")
    
    # Check if running from project root
    if not Path("src/cosine_companion.py").exists():
        print("❌ Error: Must run this script from the project root directory")
        sys.exit(1)

    # Validate the artifact before PyInstaller can package it. The byte-level
    # checks deliberately run before dependency checks so a poisoned cache is
    # diagnosed even when the build environment has another problem too.
    try:
        verify_essentia_model_file()
    except ModelVerificationError as exc:
        print(f"❌ Model verification failed: {exc}")
        sys.exit(1)
    
    # Check dependencies
    if not check_dependencies():
        sys.exit(1)

    # Loading through Essentia proves this is a TensorFlow GraphDef usable by
    # the exact runtime API, not merely a file with the right-looking bytes.
    try:
        verify_essentia_graphdef(ESSENTIA_MODEL_PATH)
    except ModelVerificationError as exc:
        print(f"❌ Model verification failed: {exc}")
        sys.exit(1)
    
    # Build with PyInstaller
    build_with_pyinstaller()
    
    print()
    print("=" * 60)
    print("Build Complete!")
    print("=" * 60)

if __name__ == "__main__":
    main()
