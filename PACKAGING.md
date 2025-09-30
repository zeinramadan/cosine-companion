# DJ Companion - Packaging Guide

This guide explains how to package DJ Companion as a standalone application that users can install and run without setting up Python.

## 📦 Building the Application

### Prerequisites

1. **Install PyInstaller**:
   ```bash
   pip install pyinstaller
   ```

2. **Install all dependencies** (see main README.md)

3. **Download the model** to the `models/` directory (required)

### Quick Build

From the project root, run:

```bash
python build_app.py
```

This will create a standalone application in the `dist/` directory.

### Platform-Specific Builds

#### macOS
```bash
# Build macOS .app bundle
python build_app.py

# Result: dist/DJ Companion.app
# Users can drag this to Applications folder
```

#### Windows
```bash
# Build Windows .exe
python build_app.py

# Result: dist/DJ Companion.exe
# Distribute with an installer (see below)
```

#### Linux
```bash
# Build Linux executable
python build_app.py

# Result: dist/DJ Companion
# Package as .deb, .rpm, or AppImage (see below)
```

## 🎨 Application Icon

Create icons for each platform:

1. Create `assets/` directory
2. Add icons:
   - macOS: `assets/icon.icns` (512x512)
   - Windows: `assets/icon.ico` (256x256)
   - Linux: `assets/icon.png` (512x512)

You can create these from a PNG using:
```bash
# macOS .icns
mkdir icon.iconset
sips -z 512 512 icon.png --out icon.iconset/icon_512x512.png
iconutil -c icns icon.iconset -o assets/icon.icns

# Windows .ico
convert icon.png -define icon:auto-resize=256,128,96,64,48,32,16 assets/icon.ico
```

## 📝 Creating Installers

### macOS - DMG Installer

```bash
# Install create-dmg
brew install create-dmg

# Create DMG
create-dmg \
  --volname "DJ Companion" \
  --volicon "assets/icon.icns" \
  --window-pos 200 120 \
  --window-size 600 400 \
  --icon-size 100 \
  --icon "DJ Companion.app" 175 120 \
  --hide-extension "DJ Companion.app" \
  --app-drop-link 425 120 \
  "DJ-Companion-Installer.dmg" \
  "dist/"
```

### Windows - NSIS Installer

1. Install NSIS (Nullsoft Scriptable Install System)
2. Create installer script `installer.nsi`:

```nsis
!define APPNAME "DJ Companion"
!define COMPANYNAME "Your Company"
!define DESCRIPTION "AI-powered DJ companion"
!define VERSIONMAJOR 1
!define VERSIONMINOR 0
!define VERSIONBUILD 0

Name "${APPNAME}"
OutFile "DJ-Companion-Setup.exe"
InstallDir "$PROGRAMFILES\${APPNAME}"

Page directory
Page instfiles

Section "Install"
  SetOutPath $INSTDIR
  File "dist\DJ Companion.exe"
  File /r "dist\models"
  
  CreateDirectory "$SMPROGRAMS\${APPNAME}"
  CreateShortCut "$SMPROGRAMS\${APPNAME}\${APPNAME}.lnk" "$INSTDIR\DJ Companion.exe"
  CreateShortCut "$DESKTOP\${APPNAME}.lnk" "$INSTDIR\DJ Companion.exe"
  
  WriteUninstaller "$INSTDIR\Uninstall.exe"
SectionEnd

Section "Uninstall"
  Delete "$INSTDIR\DJ Companion.exe"
  Delete "$INSTDIR\Uninstall.exe"
  RMDir /r "$INSTDIR\models"
  RMDir "$INSTDIR"
  Delete "$SMPROGRAMS\${APPNAME}\${APPNAME}.lnk"
  RMDir "$SMPROGRAMS\${APPNAME}"
  Delete "$DESKTOP\${APPNAME}.lnk"
SectionEnd
```

Build with: `makensis installer.nsi`

### Linux - AppImage

```bash
# Install appimagetool
wget https://github.com/AppImage/AppImageKit/releases/download/continuous/appimagetool-x86_64.AppImage
chmod +x appimagetool-x86_64.AppImage

# Create AppDir structure
mkdir -p DJ-Companion.AppDir/usr/bin
cp "dist/DJ Companion" DJ-Companion.AppDir/usr/bin/dj-companion
cp assets/icon.png DJ-Companion.AppDir/dj-companion.png

# Create .desktop file
cat > DJ-Companion.AppDir/dj-companion.desktop << EOF
[Desktop Entry]
Name=DJ Companion
Exec=dj-companion
Icon=dj-companion
Type=Application
Categories=AudioVideo;Audio;
EOF

# Create AppRun script
cat > DJ-Companion.AppDir/AppRun << 'EOF'
#!/bin/bash
SELF=$(readlink -f "$0")
HERE=${SELF%/*}
export PATH="${HERE}/usr/bin:${PATH}"
exec "${HERE}/usr/bin/dj-companion" "$@"
EOF
chmod +x DJ-Companion.AppDir/AppRun

# Build AppImage
./appimagetool-x86_64.AppImage DJ-Companion.AppDir DJ-Companion.AppImage
```

## 🚀 Distribution

### macOS
- Distribute the `.dmg` file
- Users drag the app to Applications folder
- May need to right-click → Open first time (Gatekeeper)

### Windows
- Distribute the `.exe` installer
- Users run installer
- May trigger Windows Defender on first run

### Linux
- Distribute `.AppImage` file
- Users make it executable: `chmod +x DJ-Companion.AppImage`
- Run: `./DJ-Companion.AppImage`

## 🔐 Code Signing (Recommended)

### macOS
```bash
# Sign the app
codesign --deep --force --verify --verbose --sign "Developer ID Application: Your Name" "dist/DJ Companion.app"

# Notarize with Apple
xcrun altool --notarize-app --primary-bundle-id "com.djcompanion.app" --username "your@email.com" --password "@keychain:AC_PASSWORD" --file "DJ-Companion-Installer.dmg"
```

### Windows
- Use `signtool` with a code signing certificate
- Purchase certificate from DigiCert, Sectigo, etc.

## 📋 Checklist Before Release

- [ ] Test on clean system (no Python installed)
- [ ] Verify model file is included
- [ ] Test first-run onboarding flow
- [ ] Test indexing with sample library
- [ ] Test all UI tabs work correctly
- [ ] Verify app icon displays correctly
- [ ] Test installer/uninstaller
- [ ] Check application size (should be < 500MB)
- [ ] Create release notes
- [ ] Update version numbers

## 🐛 Troubleshooting

### "Module not found" errors
- Add missing modules to `hiddenimports` in `.spec` file
- Rebuild with `pyinstaller dj-companion.spec`

### Large application size
- PyInstaller includes entire Python runtime
- Typical size: 200-400MB (includes ML model)
- Use UPX compression: `--upx-dir=/path/to/upx`

### Antivirus false positives
- Sign your code with a certificate
- Submit to antivirus vendors for whitelisting
- Build with `--noupx` if UPX causes issues

## 📚 Additional Resources

- [PyInstaller Documentation](https://pyinstaller.org/)
- [create-dmg Documentation](https://github.com/create-dmg/create-dmg)
- [NSIS Documentation](https://nsis.sourceforge.io/Docs/)
- [AppImage Documentation](https://docs.appimage.org/)
