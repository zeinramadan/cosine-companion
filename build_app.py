#!/usr/bin/env python3
"""Build script for creating standalone DJ Companion application."""

import sys
import os
import platform
import subprocess
from pathlib import Path

def build_with_pyinstaller():
    """Build the application using PyInstaller."""
    
    system = platform.system()
    print(f"🔨 Building DJ Companion for {system}...")
    
    # Base PyInstaller command
    cmd = [
        "pyinstaller",
        "--name=DJ Companion",
        "--windowed",  # No console window
        "--onefile",   # Single executable
        "--clean",     # Clean cache
        "--noconfirm", # Overwrite without asking
    ]
    
    # Add icon based on platform
    if system == "Darwin":  # macOS
        if Path("assets/icon.icns").exists():
            cmd.extend(["--icon=assets/icon.icns"])
    elif system == "Windows":
        if Path("assets/icon.ico").exists():
            cmd.extend(["--icon=assets/icon.ico"])
    elif system == "Linux":
        if Path("assets/icon.png").exists():
            cmd.extend(["--icon=assets/icon.png"])
    
    # Add hidden imports for dynamic imports
    hidden_imports = [
        "core",
        "core.loader",
        "core.persistence",
        "core.index_builder",
        "core.duplicates",
        "processing",
        "processing.pipeline",
        "processing.embeddings",
        "processing.xml_parser",
        "recommendations",
        "recommendations.engine",
        "recommendations.scoring",
        "recommendations.set_generator",
        "recommendations.models",
        "recommendations.transitions",
        "recommendations.search",
        "ui",
        "ui.app",
        "ui.onboarding",
        "ui.recommendations_tab",
        "ui.set_creator_tab",
        "ui.library_tab",
        "ui.dialogs",
        "config",
        "config.paths",
        "config.defaults",
    ]
    
    for module in hidden_imports:
        cmd.extend(["--hidden-import", module])
    
    # Add data files (models directory)
    if Path("models").exists():
        cmd.extend(["--add-data", f"models{os.pathsep}models"])
    
    # Entry point
    cmd.append("src/dj_companion.py")
    
    # Run PyInstaller
    print(f"Running: {' '.join(cmd)}")
    result = subprocess.run(cmd)
    
    if result.returncode == 0:
        print("\n✅ Build successful!")
        print(f"📦 Application built in: dist/DJ Companion")
        
        if system == "Darwin":
            print("\n🍎 macOS: You can now run:")
            print("   open 'dist/DJ Companion.app'")
        elif system == "Windows":
            print("\n🪟 Windows: You can now run:")
            print("   .\\dist\\DJ Companion.exe")
        elif system == "Linux":
            print("\n🐧 Linux: You can now run:")
            print("   ./dist/DJ Companion")
    else:
        print("\n❌ Build failed!")
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
    print("DJ Companion - Application Builder")
    print("=" * 60)
    print()
    
    # Check if running from project root
    if not Path("src/dj_companion.py").exists():
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
