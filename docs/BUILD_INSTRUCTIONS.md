# Cosine Companion - Build & Release Instructions

This guide covers how to build and distribute Cosine Companion as a standalone application.

## Prerequisites

### 1. Install Dependencies

Ensure you're in the `dj-companion` conda environment:

```bash
conda activate dj-companion
pip install -r requirements.txt
```

### 2. Required Files Checklist

Before building, verify these files exist:

- ✅ `assets/coco_logo.png` - Main logo (high-res)
- ✅ `assets/coco_logo_small.png` - Small logo for window icons
- ✅ `assets/coco_logo.icns` - macOS app icon
- ✅ `models/discogs_*_embeddings-effnet-bs64-1.pb` - Embedding models
- ✅ `cosine-companion.spec` - PyInstaller configuration

### 3. Verify Icon Files

The build process requires platform-specific icon files:

**macOS**: `assets/coco_logo.icns` (created automatically from PNG)
**Windows**: `assets/coco_logo.ico` (optional, for Windows builds)

If missing, create `.icns` from PNG:

```bash
cd assets
mkdir -p icon.iconset
sips -z 16 16 coco_logo.png --out icon.iconset/icon_16x16.png
sips -z 32 32 coco_logo.png --out icon.iconset/icon_16x16@2x.png
sips -z 32 32 coco_logo.png --out icon.iconset/icon_32x32.png
sips -z 64 64 coco_logo.png --out icon.iconset/icon_32x32@2x.png
sips -z 128 128 coco_logo.png --out icon.iconset/icon_128x128.png
sips -z 256 256 coco_logo.png --out icon.iconset/icon_128x128@2x.png
sips -z 256 256 coco_logo.png --out icon.iconset/icon_256x256.png
sips -z 512 512 coco_logo.png --out icon.iconset/icon_256x256@2x.png
sips -z 512 512 coco_logo.png --out icon.iconset/icon_512x512.png
sips -z 1024 1024 coco_logo.png --out icon.iconset/icon_512x512@2x.png
iconutil -c icns icon.iconset -o coco_logo.icns
rm -rf icon.iconset
cd ..
```

## Building the Application

### Option 1: Using the Build Script (Recommended)

```bash
python build_app.py
```

This script will:
- Check all dependencies
- Use the PyInstaller spec file
- Build the application
- Display the output location

### Option 2: Using PyInstaller Directly

```bash
pyinstaller --clean --noconfirm cosine-companion.spec
```

## Build Output

### macOS
- **Output**: `dist/Cosine Companion.app`
- **Test**: `open 'dist/Cosine Companion.app'`
- **Size**: ~500-800 MB (includes all dependencies and models)

### Windows
- **Output**: `dist/Cosine Companion.exe`
- **Test**: Run the executable
- **Size**: ~400-700 MB

### Linux
- **Output**: `dist/Cosine Companion`
- **Test**: `./dist/'Cosine Companion'`
- **Size**: ~400-700 MB

## Distribution

### License & Source Availability (AGPLv3)

When distributing builds, make sure you:
- Include the `LICENSE` file in the app bundle or installer
- Provide a source code link on the release page or download location
- Make corresponding source available for any distributed binaries

### macOS Distribution

#### 1. Test the Application
```bash
open 'dist/Cosine Companion.app'
```

Verify:
- Application launches without errors
- Onboarding flow works
- Icon appears correctly in dock
- All features function properly

#### 2. Code Signing (Optional but Recommended)

For wider distribution, sign the app:

```bash
codesign --deep --force --verify --verbose --sign "Developer ID Application: Your Name" \
  'dist/Cosine Companion.app'
```

#### 3. Create DMG Installer (Optional)

Using `create-dmg` (install via `brew install create-dmg`):

```bash
create-dmg \
  --volname "Cosine Companion" \
  --volicon "assets/coco_logo.icns" \
  --window-pos 200 120 \
  --window-size 800 400 \
  --icon-size 100 \
  --icon "Cosine Companion.app" 200 190 \
  --hide-extension "Cosine Companion.app" \
  --app-drop-link 600 185 \
  "DJ-Companion-Installer.dmg" \
  "dist/Cosine Companion.app"
```

#### 4. Notarization (For macOS 10.15+)

Required for distribution outside the Mac App Store:

```bash
# Submit for notarization
xcrun notarytool submit "DJ-Companion-Installer.dmg" \
  --apple-id "your@email.com" \
  --team-id "YOUR_TEAM_ID" \
  --password "app-specific-password" \
  --wait

# Staple the notarization ticket
xcrun stapler staple "DJ-Companion-Installer.dmg"
```

### Windows Distribution

1. Test the `.exe` file thoroughly
2. Consider creating an installer using:
   - **NSIS** (Nullsoft Scriptable Install System)
   - **Inno Setup**
   - **WiX Toolset**

### Linux Distribution

1. Test the executable
2. Package as:
   - **AppImage** (most portable)
   - **.deb** package (Debian/Ubuntu)
   - **.rpm** package (Fedora/Red Hat)
   - **Flatpak** or **Snap** (modern Linux)

## Troubleshooting

### Build Fails with Missing Modules

If PyInstaller can't find certain modules, add them to `hiddenimports` in `cosine-companion.spec`:

```python
hiddenimports=[
    'your.missing.module',
    ...
]
```

### Application Won't Launch

1. Check console output: `open -a Console` (macOS)
2. Run from terminal to see errors:
   ```bash
   ./dist/DJ\ Companion.app/Contents/MacOS/DJ\ Companion
   ```

### Icon Not Appearing

Verify:
- `assets/coco_logo.icns` exists and is valid
- `assets/coco_logo_small.png` exists (for window icons)
- File paths in spec file are correct

### Large File Size

This is normal! The app includes:
- Python runtime
- All dependencies (numpy, pandas, essentia, faiss, etc.)
- ML models (~400MB)
- Audio processing libraries

To reduce size:
- Remove unused dependencies from `requirements.txt`
- Use `--upx` compression in spec file (already enabled)

## Version Management

Before building a release:

1. Update version in `cosine-companion.spec`:
   ```python
   'CFBundleVersion': "1.0.1",
   'CFBundleShortVersionString': "1.0.1",
   ```

2. Tag the release:
   ```bash
   git tag -a v1.0.1 -m "Release version 1.0.1"
   git push origin v1.0.1
   ```

## Clean Build

To completely clean and rebuild:

```bash
# Remove build artifacts
rm -rf build/ dist/ *.spec~

# Rebuild
python build_app.py
```

## Release Checklist

Before distributing to users:

- [ ] All dependencies installed
- [ ] Icon files present and correct
- [ ] Build completes without errors
- [ ] Application launches and runs correctly
- [ ] Onboarding flow works
- [ ] Library indexing works
- [ ] Recommendations generate properly
- [ ] Settings window accessible
- [ ] Re-indexing works with cancellation
- [ ] Deleted tracks management works
- [ ] Application closes properly
- [ ] Version number updated
- [ ] Release notes written
- [ ] (macOS) Code signed and notarized
- [ ] Installation tested on clean system

## Support

For build issues, check:
- PyInstaller documentation: https://pyinstaller.org/
- Project issues: GitHub repository
- Build logs in `build/` directory
