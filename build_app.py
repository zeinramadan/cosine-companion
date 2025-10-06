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
        "pyinstaller",
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
            # Install launcher script for macOS
            app_path = Path("dist/Cosine Companion.app")
            if app_path.exists():
                print("\n🔧 Installing SDL environment wrapper...")
                macos_dir = app_path / "Contents" / "MacOS"
                binary_path = macos_dir / "Cosine Companion"
                binary_renamed = macos_dir / "Cosine Companion.bin"
                launcher_src = Path("macos_launcher.sh")
                
                # Step 1: Rename the PyInstaller binary if it exists
                if binary_path.exists() and not binary_renamed.exists():
                    print(f"   📝 Renaming binary to 'Cosine Companion.bin'...")
                    binary_path.rename(binary_renamed)
                
                # Step 2: Copy launcher script as main executable
                if launcher_src.exists():
                    import shutil
                    shutil.copy2(launcher_src, binary_path)
                    # Make it executable
                    os.chmod(binary_path, 0o755)
                    print(f"   ✅ Installed wrapper at {binary_path}")
                    print(f"   ✅ Binary at {binary_renamed}")
                else:
                    print(f"   ⚠️  Warning: {launcher_src} not found")
                
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
    
    return True

def main():
    """Main build script."""
    print("=" * 60)
    print("Cosine Companion - Application Builder")
    print("=" * 60)
    print()
    
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
