# Building User-Friendly DJ Companion Package

This document contains complete instructions to create a non-technical, download-and-run package for DJ Companion using PyInstaller.

## Overview

Transform the current command-line DJ Companion into a simple executable that non-technical users can download and use immediately, with a friendly GUI launcher.

## Target User Experience

1. **Download** `DJ-Companion-Release.zip`
2. **Extract** to any folder  
3. **Double-click** launcher script
4. **Follow GUI prompts** to export Rekordbox XML and index music
5. **Use DJ tool** for track recommendations

No technical knowledge, command lines, or package installation required.

## Files to Create

### 1. Build Script (`build_app.py`)

```python
#!/usr/bin/env python3
"""
Build script to create a standalone DJ Companion executable.
Run: python build_app.py
"""

import PyInstaller.__main__
import os
import sys
from pathlib import Path

def build_app():
    # Ensure we're in the right directory
    script_dir = Path(__file__).parent
    os.chdir(script_dir)
    
    # Files to include in the bundle
    added_files = [
        ('models', 'models'),
        ('README.md', '.'),
        ('PROGRAM_FLOW.md', '.'),
        ('SETUP_GUIDE.md', '.'),
    ]
    
    # Hidden imports for all our dependencies
    hidden_imports = [
        'essentia',
        'essentia.standard',
        'faiss',
        'tkinter',
        'tkinter.simpledialog',
        'tkinter.messagebox',
        'soundfile',
        'librosa',
        'audioread',
        'pandas',
        'numpy',
        'lxml',
        'typer',
        'urllib.parse',
    ]
    
    # Build arguments
    args = [
        'dj_companion.py',
        '--name=DJ-Companion',
        '--onefile',
        '--windowed',  # Hide console window
        '--icon=icon.ico' if os.path.exists('icon.ico') else '',
        '--add-data=' + (';' if sys.platform == 'win32' else ':').join([f'{src}{os.pathsep}{dst}' for src, dst in added_files]),
    ]
    
    # Add hidden imports
    for imp in hidden_imports:
        args.extend(['--hidden-import', imp])
    
    # Collect all packages that might be needed
    collect_packages = ['essentia', 'faiss', 'librosa', 'soundfile']
    for pkg in collect_packages:
        args.extend(['--collect-all', pkg])
    
    # Exclude unnecessary packages to reduce size
    exclude_modules = [
        'matplotlib', 'IPython', 'jupyter', 'notebook',
        'scipy', 'sklearn', 'PIL', 'cv2'
    ]
    for mod in exclude_modules:
        args.extend(['--exclude-module', mod])
    
    # Remove empty strings
    args = [arg for arg in args if arg]
    
    print("Building DJ Companion executable...")
    print("This may take several minutes...")
    
    PyInstaller.__main__.run(args)
    
    print("\n✅ Build complete!")
    print("📁 Executable location: dist/DJ-Companion")
    print("📋 Next steps:")
    print("   1. Test the executable: ./dist/DJ-Companion")
    print("   2. Create release package with create_release.py")

if __name__ == "__main__":
    build_app()
```

### 2. Release Package Creator (`create_release.py`)

```python
#!/usr/bin/env python3
"""
Create a complete release package for end users.
Run after build_app.py completes successfully.
"""

import shutil
import os
from pathlib import Path
import zipfile

def create_release():
    # Create release directory
    release_dir = Path("release")
    release_dir.mkdir(exist_ok=True)
    
    # Clear previous release
    if release_dir.exists():
        shutil.rmtree(release_dir)
    release_dir.mkdir()
    
    # Copy executable
    exe_name = "DJ-Companion.exe" if os.name == 'nt' else "DJ-Companion"
    exe_path = Path("dist") / exe_name
    
    if not exe_path.exists():
        print("❌ Executable not found. Run build_app.py first.")
        return
    
    shutil.copy2(exe_path, release_dir / exe_name)
    
    # Copy user guides
    guides = ["SETUP_GUIDE.md", "USER_MANUAL.md", "README.md"]
    for guide in guides:
        if Path(guide).exists():
            shutil.copy2(guide, release_dir)
    
    # Create models directory and copy models
    models_dir = release_dir / "models"
    models_dir.mkdir()
    
    if Path("models").exists():
        for model_file in Path("models").glob("*.pb"):
            shutil.copy2(model_file, models_dir)
    
    # Create data directory (empty, for user data)
    (release_dir / "data").mkdir()
    
    # Create example scripts for different platforms
    create_launcher_scripts(release_dir)
    
    # Create ZIP package
    create_zip_package(release_dir)
    
    print(f"\n✅ Release package created!")
    print(f"📁 Location: {release_dir.absolute()}")
    print(f"📦 ZIP package: DJ-Companion-Release.zip")

def create_launcher_scripts(release_dir):
    """Create simple launcher scripts for different platforms."""
    
    # Windows batch file
    windows_launcher = release_dir / "Launch DJ Companion.bat"
    windows_launcher.write_text("""@echo off
echo Starting DJ Companion...
echo.
echo If this is your first time:
echo 1. Export your Rekordbox collection as XML
echo 2. Use 'Index Music' to process your tracks
echo 3. Use 'Open DJ Tool' to get recommendations
echo.
pause
DJ-Companion.exe
pause
""")
    
    # Mac/Linux shell script
    unix_launcher = release_dir / "launch_dj_companion.sh"
    unix_launcher.write_text("""#!/bin/bash
echo "Starting DJ Companion..."
echo ""
echo "If this is your first time:"
echo "1. Export your Rekordbox collection as XML"
echo "2. Use 'Index Music' to process your tracks"
echo "3. Use 'Open DJ Tool' to get recommendations"
echo ""
read -p "Press Enter to continue..."
./DJ-Companion
""")
    unix_launcher.chmod(0o755)

def create_zip_package(release_dir):
    """Create a ZIP file for easy distribution."""
    zip_path = "DJ-Companion-Release.zip"
    
    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
        for file_path in release_dir.rglob('*'):
            if file_path.is_file():
                arcname = file_path.relative_to(release_dir)
                zipf.write(file_path, f"DJ-Companion/{arcname}")

if __name__ == "__main__":
    create_release()
```

### 3. User-Friendly Launcher GUI (`launcher.py`)

```python
#!/usr/bin/env python3
"""
User-friendly launcher for DJ Companion.
This provides a simple interface for non-technical users.
"""

import tkinter as tk
from tkinter import messagebox, filedialog
import subprocess
import sys
import os
from pathlib import Path
import threading

class DJCompanionLauncher:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("DJ Companion")
        self.root.geometry("500x400")
        self.root.configure(padx=20, pady=20)
        
        # Main title
        title = tk.Label(self.root, text="🎵 DJ Companion", 
                        font=("Helvetica", 24, "bold"))
        title.pack(pady=20)
        
        subtitle = tk.Label(self.root, text="AI-Powered Track Recommendations", 
                           font=("Helvetica", 12), fg="gray")
        subtitle.pack(pady=(0, 30))
        
        # Status label
        self.status_label = tk.Label(self.root, text="Ready", 
                                   font=("Helvetica", 10), fg="green")
        self.status_label.pack(pady=(0, 20))
        
        # Main buttons
        self.create_buttons()
        
        # Instructions
        self.create_instructions()
        
    def create_buttons(self):
        button_frame = tk.Frame(self.root)
        button_frame.pack(pady=20)
        
        # Index music button
        index_btn = tk.Button(button_frame, text="📁 Index Music Collection",
                             command=self.index_music,
                             font=("Helvetica", 14),
                             bg="#4CAF50", fg="white",
                             padx=20, pady=10,
                             width=20)
        index_btn.pack(pady=10)
        
        # Open UI button
        ui_btn = tk.Button(button_frame, text="🎧 Open DJ Tool",
                          command=self.open_ui,
                          font=("Helvetica", 14),
                          bg="#2196F3", fg="white",
                          padx=20, pady=10,
                          width=20)
        ui_btn.pack(pady=10)
        
        # Help button
        help_btn = tk.Button(button_frame, text="❓ Setup Guide",
                            command=self.show_help,
                            font=("Helvetica", 12),
                            bg="#FF9800", fg="white",
                            padx=20, pady=5,
                            width=20)
        help_btn.pack(pady=5)
        
    def create_instructions(self):
        instructions_frame = tk.Frame(self.root)
        instructions_frame.pack(fill="x", pady=20)
        
        instructions = tk.Text(instructions_frame, height=8, width=60,
                              font=("Helvetica", 10),
                              bg="#f5f5f5", fg="#333",
                              wrap=tk.WORD, padx=10, pady=10)
        instructions.pack(fill="x")
        
        instructions_text = """🚀 Quick Start:

1. Export your Rekordbox collection as XML:
   File → Export Collection in xml format

2. Click "Index Music Collection" and select your XML file
   (This processes your tracks - takes 2-5 min per 100 tracks)

3. Click "Open DJ Tool" to get track recommendations

4. Set current track and see similar tracks instantly!

💡 Tip: Indexing is only slow the first time. Updates are much faster!"""
        
        instructions.insert("1.0", instructions_text)
        instructions.config(state="disabled")
        
    def index_music(self):
        xml_file = filedialog.askopenfilename(
            title="Select Rekordbox XML Export",
            filetypes=[("XML files", "*.xml"), ("All files", "*.*")]
        )
        
        if not xml_file:
            return
            
        self.status_label.config(text="Processing music collection...", fg="orange")
        self.root.update()
        
        # Run indexing in background thread
        thread = threading.Thread(target=self.run_indexing, args=(xml_file,))
        thread.daemon = True
        thread.start()
        
    def run_indexing(self, xml_file):
        try:
            # Run the indexing command
            result = subprocess.run([
                sys.executable, "dj_companion.py", "index", xml_file
            ], capture_output=True, text=True)
            
            if result.returncode == 0:
                self.root.after(0, lambda: self.status_label.config(
                    text="✅ Indexing complete! Ready to use DJ Tool.", fg="green"))
                self.root.after(0, lambda: messagebox.showinfo(
                    "Success", "Music collection indexed successfully!\n\nYou can now use the DJ Tool to get recommendations."))
            else:
                self.root.after(0, lambda: self.status_label.config(
                    text="❌ Indexing failed. Check console for details.", fg="red"))
                self.root.after(0, lambda: messagebox.showerror(
                    "Error", f"Indexing failed:\n{result.stderr}"))
                
        except Exception as e:
            self.root.after(0, lambda: self.status_label.config(
                text="❌ Error occurred.", fg="red"))
            self.root.after(0, lambda: messagebox.showerror(
                "Error", f"An error occurred:\n{str(e)}"))
    
    def open_ui(self):
        try:
            # Check if data exists
            if not Path("data/meta.parquet").exists():
                messagebox.showwarning(
                    "No Data", 
                    "Please index your music collection first!\n\nClick 'Index Music Collection' and select your Rekordbox XML file.")
                return
                
            self.status_label.config(text="Opening DJ Tool...", fg="blue")
            self.root.update()
            
            # Run UI
            subprocess.Popen([sys.executable, "dj_companion.py", "ui"])
            
            self.status_label.config(text="DJ Tool opened!", fg="green")
            
        except Exception as e:
            messagebox.showerror("Error", f"Failed to open DJ Tool:\n{str(e)}")
            self.status_label.config(text="❌ Failed to open DJ Tool.", fg="red")
    
    def show_help(self):
        help_window = tk.Toplevel(self.root)
        help_window.title("Setup Guide")
        help_window.geometry("600x500")
        help_window.configure(padx=20, pady=20)
        
        help_text = tk.Text(help_window, wrap=tk.WORD, font=("Helvetica", 11))
        help_text.pack(fill="both", expand=True)
        
        scrollbar = tk.Scrollbar(help_window, orient="vertical", command=help_text.yview)
        scrollbar.pack(side="right", fill="y")
        help_text.config(yscrollcommand=scrollbar.set)
        
        help_content = """DJ Companion - Setup Guide

🚀 QUICK START:

1. Export Your Rekordbox Collection:
   • Open Rekordbox
   • Go to File → Export Collection in xml format
   • Save to Desktop as 'my_collection.xml'
   • Wait for export (may take a few minutes)

2. Index Your Music:
   • Click "Index Music Collection" in the main window
   • Select your XML file
   • Wait for processing (2-5 minutes per 100 tracks)
   • You'll see: [42/500] Artist - Track Name

3. Use DJ Tool:
   • Click "Open DJ Tool"
   • Click "Set Current Track"
   • Search for any track
   • See recommendations with similarity scores!

🔄 ADDING NEW MUSIC:

When you get new tracks:
1. Export updated XML from Rekordbox
2. Run "Index Music Collection" again
3. Only new tracks will be processed (much faster!)

🎯 USING RECOMMENDATIONS:

• Cos XX%: How similar tracks sound (AI analysis)
• Score XX%: Overall compatibility (includes key & BPM)
• Sort by: Score, Cosine, Key, BPM, or Artist
• Copy tracks to clipboard for easy playlist building

🔧 TROUBLESHOOTING:

• "File not found" errors: Make sure music files are accessible
• Slow processing: Normal for first time (faster for updates)
• No recommendations: Make sure indexing completed successfully

📁 IMPORTANT:
Keep the entire app folder together - it contains your processed music data!

🆘 Need more help? Check the full USER_MANUAL.md file."""
        
        help_text.insert("1.0", help_content)
        help_text.config(state="disabled")
    
    def run(self):
        self.root.mainloop()

if __name__ == "__main__":
    app = DJCompanionLauncher()
    app.run()
```

### 4. Modified Main App (`dj_companion.py` changes)

Add this to the top of `dj_companion.py` after imports:

```python
# Check if running as standalone executable
if getattr(sys, 'frozen', False):
    # Running as PyInstaller executable
    import tkinter as tk
    from launcher import DJCompanionLauncher
    
    # If no command line arguments, show the launcher GUI
    if len(sys.argv) == 1:
        app = DJCompanionLauncher()
        app.run()
        sys.exit(0)
```

Add this command to the CLI:

```python
@cli.command()
def launcher():
    """Open the user-friendly launcher interface."""
    from launcher import DJCompanionLauncher
    app = DJCompanionLauncher()
    app.run()
```

### 5. User Documentation Files

Create these files with comprehensive setup instructions:

- `SETUP_GUIDE.md` - Quick start guide for end users
- `USER_MANUAL.md` - Detailed usage instructions
- `requirements.txt` - All Python dependencies for building

### 6. Requirements File (`requirements.txt`)

```text
essentia-tensorflow>=2.1.0
faiss-cpu>=1.7.0
pandas>=2.0.0
numpy>=1.24.0
soundfile>=0.12.0
librosa>=0.10.0
audioread>=3.0.0
lxml>=4.9.0
typer>=0.9.0
pyinstaller>=5.0.0
```

## Build Process

### For Developer:

1. **Install build dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

2. **Create all the files above** in the DJ Companion directory

3. **Build the executable:**
   ```bash
   python build_app.py
   ```

4. **Create release package:**
   ```bash
   python create_release.py
   ```

5. **Test the package:**
   - Extract `DJ-Companion-Release.zip`
   - Run launcher script
   - Test full workflow

6. **Distribute:**
   - Upload ZIP file to GitHub releases
   - Provide download link to users

### For End Users:

1. **Download** `DJ-Companion-Release.zip`
2. **Extract** to any folder
3. **Double-click** `Launch DJ Companion.bat` (Windows) or `launch_dj_companion.sh` (Mac/Linux)
4. **Follow GUI instructions**

## Key Features

- **Zero technical setup** - just download and run
- **Friendly GUI launcher** - no command line needed
- **Clear instructions** - built-in help and guides
- **Incremental updates** - fast re-indexing of new music
- **Cross-platform** - Windows, Mac, Linux support
- **Self-contained** - all dependencies bundled

## File Structure in Release
```
