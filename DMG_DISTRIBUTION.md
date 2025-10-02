# 📦 DMG Distribution Guide

## ✅ DMG Installer Created Successfully!

Your DMG installer is ready for distribution: **DJ-Companion-Installer.dmg**

- **File**: `DJ-Companion-Installer.dmg`
- **Size**: ~207 MB
- **Location**: `/Users/zein/dj-cosine/DJ-Companion-Installer.dmg`

---

## 🎯 What's Included

The DMG provides a standard macOS drag-and-drop installer experience:
- DJ Companion.app (ready to drag to Applications folder)
- Applications folder shortcut for easy installation
- Custom volume icon (coco_logo.icns)
- Formatted window with proper layout

---

## 🧪 Testing the DMG

### 1. Open the DMG
```bash
open DJ-Companion-Installer.dmg
```

This will mount the disk image and show the installer window with:
- DJ Companion.app icon on the left
- Applications folder shortcut on the right
- Users can simply drag the app to Applications

### 2. Test Installation
From the mounted DMG:
1. Drag DJ Companion.app to Applications
2. Open from Applications folder
3. Verify the app launches and works correctly
4. Test all major features:
   - Onboarding with library indexing
   - Library browsing
   - Recommendations
   - Set creation
   - Settings

### 3. Unmount
```bash
hdiutil detach "/Volumes/DJ Companion"
```

---

## 📤 Distribution Methods

### Option 1: Direct Download
- Upload to your website/file hosting
- Users download and open the DMG
- Simple drag-and-drop installation

### Option 2: GitHub Releases
```bash
# Create a new release
gh release create v1.0.0 \
  DJ-Companion-Installer.dmg \
  --title "DJ Companion v1.0.0" \
  --notes "Initial release of DJ Companion"
```

Or manually:
1. Go to GitHub repository → Releases
2. Click "Draft a new release"
3. Tag: `v1.0.0`
4. Upload `DJ-Companion-Installer.dmg`
5. Add release notes
6. Publish release

### Option 3: Cloud Storage
Upload to:
- Google Drive
- Dropbox
- Amazon S3
- Any file hosting service

Share the download link with users.

---

## 🔐 Code Signing & Notarization

For wider distribution (especially to users outside your organization), you should code sign and notarize the app:

### 1. Code Sign the App

Before creating the DMG:
```bash
codesign --deep --force --verify --verbose \
  --sign "Developer ID Application: Your Name (TEAM_ID)" \
  --options runtime \
  'dist/DJ Companion.app'
```

### 2. Notarize the App

```bash
# Create a zip for notarization
ditto -c -k --keepParent 'dist/DJ Companion.app' DJ-Companion.zip

# Submit for notarization
xcrun notarytool submit DJ-Companion.zip \
  --apple-id "your@email.com" \
  --team-id "YOUR_TEAM_ID" \
  --password "app-specific-password" \
  --wait

# Staple the notarization ticket
xcrun stapler staple 'dist/DJ Companion.app'
```

### 3. Then Create the DMG

After code signing and notarization, create the DMG with the signed app.

### Requirements for Notarization:
- Apple Developer Account ($99/year)
- Developer ID Application certificate
- App-specific password from appleid.apple.com

---

## ⚠️ Without Code Signing

If you distribute without code signing/notarization, users will see:

> "DJ Companion.app can't be opened because it is from an unidentified developer."

**Users can bypass this:**
1. Right-click the app → Open
2. Click "Open" in the dialog
3. Or: System Preferences → Security & Privacy → "Open Anyway"

This is fine for:
- Personal use
- Testing
- Internal distribution
- Small user groups

For public release, code signing is strongly recommended.

---

## 📝 Installation Instructions for Users

Provide these instructions to your users:

### Installing DJ Companion

1. **Download** `DJ-Companion-Installer.dmg`

2. **Open** the downloaded DMG file
   - Double-click `DJ-Companion-Installer.dmg`
   - A new window will open

3. **Install** the application
   - Drag the **DJ Companion** icon to the **Applications** folder
   - Wait for the copy to complete

4. **Launch** the app
   - Open your Applications folder
   - Double-click **DJ Companion**
   - If you see a security warning, right-click → Open

5. **First Launch**
   - Follow the onboarding wizard
   - Select your Rekordbox XML library file
   - Wait for initial indexing (this may take a few minutes)
   - Start using DJ Companion!

---

## 🚀 Quick Distribution Checklist

Before distributing:

- [ ] DMG created successfully
- [ ] Tested DMG installation on clean system
- [ ] App launches from Applications folder
- [ ] All features work correctly
- [ ] (Optional) Code signed and notarized
- [ ] Installation instructions prepared
- [ ] Release notes written
- [ ] Version number updated
- [ ] GitHub release created (or other distribution method)

---

## 📊 File Sizes

Understanding the size:
- **DMG**: ~207 MB (compressed disk image)
- **App**: ~500-800 MB (when installed)
- Size includes:
  - Python runtime
  - All dependencies (numpy, pandas, essentia, faiss, etc.)
  - ML models (~34 MB)
  - Audio processing libraries

This is normal for a self-contained macOS application with machine learning capabilities.

---

## 🔄 Creating Updated Versions

When you release an update:

1. Update version number in `dj-companion.spec`:
   ```python
   'CFBundleVersion': "1.0.1",
   'CFBundleShortVersionString': "1.0.1",
   ```

2. Rebuild the app:
   ```bash
   python build_app.py
   ```

3. Create new DMG:
   ```bash
   create-dmg \
     --volname "DJ Companion" \
     --volicon "assets/coco_logo.icns" \
     --window-pos 200 120 \
     --window-size 800 450 \
     --icon-size 100 \
     --icon "DJ Companion.app" 200 190 \
     --hide-extension "DJ Companion.app" \
     --app-drop-link 600 185 \
     "DJ-Companion-v1.0.1-Installer.dmg" \
     "dist/DJ Companion.app"
   ```

4. Distribute the new version

---

## 🎉 You're Ready to Distribute!

Your DJ Companion DMG installer is ready for users. Test it thoroughly, and when ready, share it with your audience!

For questions about distribution, refer to:
- Apple's Distribution Guide: https://developer.apple.com/distribution/
- Code Signing Guide: https://developer.apple.com/support/code-signing/
- Notarization Guide: https://developer.apple.com/documentation/security/notarizing_macos_software_before_distribution

