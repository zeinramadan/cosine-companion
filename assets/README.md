# App Icons

This directory contains the application icons for DJ Companion.

## Required Files

### For the Application Window (macOS/Linux)
- **`coco_logo.png`** - PNG format, recommended size: 512x512 or 1024x1024 pixels (currently in use)

### For Windows (if building for Windows)
- **`coco_logo.ico`** - ICO format, recommended sizes: 16x16, 32x32, 48x48, 256x256

### For macOS App Bundle
- **`coco_logo.icns`** - ICNS format (Apple icon format)

## Creating Icons

### 1. Create a base PNG icon (512x512 or larger)
Design your icon in any image editor (Figma, Sketch, Photoshop, etc.) and export as PNG.

### 2. For macOS (.icns file)
Use the `iconutil` command-line tool (included with macOS):

```bash
# Create an iconset directory
mkdir icon.iconset

# Create all required sizes (use any image editor or ImageMagick)
sips -z 16 16     coco_logo.png --out icon.iconset/icon_16x16.png
sips -z 32 32     coco_logo.png --out icon.iconset/icon_16x16@2x.png
sips -z 32 32     coco_logo.png --out icon.iconset/icon_32x32.png
sips -z 64 64     coco_logo.png --out icon.iconset/icon_32x32@2x.png
sips -z 128 128   coco_logo.png --out icon.iconset/icon_128x128.png
sips -z 256 256   coco_logo.png --out icon.iconset/icon_128x128@2x.png
sips -z 256 256   coco_logo.png --out icon.iconset/icon_256x256.png
sips -z 512 512   coco_logo.png --out icon.iconset/icon_256x256@2x.png
sips -z 512 512   coco_logo.png --out icon.iconset/icon_512x512.png
sips -z 1024 1024 coco_logo.png --out icon.iconset/icon_512x512@2x.png

# Convert to .icns
iconutil -c icns icon.iconset

# Clean up
rm -rf icon.iconset
```

### 3. For Windows (.ico file)
Use an online converter or ImageMagick:

```bash
# Using ImageMagick
convert coco_logo.png -define icon:auto-resize=256,128,64,48,32,16 coco_logo.ico
```

Or use online tools like:
- https://convertio.co/png-ico/
- https://cloudconvert.com/png-to-ico

## Quick Start

The app currently uses `coco_logo.png` as the icon.

To use a different icon:

1. Replace `coco_logo.png` with your icon file (512x512 or larger)
2. Run the app - the icon will appear in the window titlebar
3. For a packaged macOS app, also create `coco_logo.icns` and rebuild with PyInstaller

## Icon Design Tips

- Use a simple, recognizable design that works at small sizes (16x16)
- Use high contrast colors
- Avoid fine details that won't be visible when scaled down
- Consider using a music/DJ-related symbol (turntable, waveform, headphones, etc.)
- Use transparency where appropriate
- Test how it looks on both light and dark backgrounds

