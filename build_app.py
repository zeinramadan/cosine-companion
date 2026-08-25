#!/usr/bin/env python3
"""Build script for creating standalone Cosine Companion application."""

import sys
import os
import platform
import subprocess
from pathlib import Path

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
        ("PIL", "pip install Pillow"),
        ("lxml", "pip install lxml"),
        ("soundfile", "pip install soundfile"),
        ("essentia", "pip install essentia-tensorflow"),
        ("typer", "pip install typer"),
        # The web UI's window. Imported as `webview`, installed as `pywebview`
        # - checking the import name is the only one of the two that proves the
        # build machine can actually collect it. Without it PyInstaller emits a
        # warning and produces a bundle that dies the moment `ui-web` runs, so
        # this belongs here, at the start, rather than in a user's crash report.
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

def main():
    """Main build script."""
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
    
    # Check dependencies
    if not check_dependencies():
        sys.exit(1)
    
    # Build with PyInstaller
    build_with_pyinstaller()
    
    print()
    print("=" * 60)
    print("Build Complete!")
    print("=" * 60)

if __name__ == "__main__":
    main()
