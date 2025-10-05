#!/usr/bin/env python3
"""Create Windows .ico file from PNG logo."""

from PIL import Image
from pathlib import Path


def create_ico(png_path: str, ico_path: str) -> None:
    """
    Convert PNG to ICO with multiple sizes for Windows.
    
    Args:
        png_path: Path to source PNG file
        ico_path: Path to output ICO file
    """
    print("🎨 Creating Windows icon...")
    
    # Load the PNG image
    img = Image.open(png_path)
    
    # Create multiple sizes for the ICO file
    # Windows uses different icon sizes in different contexts
    sizes = [
        (16, 16),    # Small icons (taskbar, etc.)
        (32, 32),    # Standard icons
        (48, 48),    # Large icons
        (64, 64),    # Extra large icons
        (128, 128),  # Jumbo icons
        (256, 256),  # Super jumbo icons
    ]
    
    print(f"   Source: {png_path}")
    print(f"   Sizes: {', '.join(f'{w}x{h}' for w, h in sizes)}")
    
    # Save as ICO with multiple sizes embedded
    img.save(ico_path, format='ICO', sizes=sizes)
    
    print(f"✅ Created: {ico_path}")
    print(f"   File size: {Path(ico_path).stat().st_size / 1024:.1f} KB")


def main():
    """Main function to create Windows icon."""
    assets_dir = Path(__file__).parent / "assets"
    
    # Input PNG
    png_path = assets_dir / "coco_logo.png"
    
    # Output ICO
    ico_path = assets_dir / "coco_logo.ico"
    
    # Check if PNG exists
    if not png_path.exists():
        print(f"❌ Error: {png_path} not found!")
        print("   Make sure coco_logo.png exists in the assets/ directory.")
        return 1
    
    # Create the icon
    try:
        create_ico(str(png_path), str(ico_path))
        print("\n✨ Windows icon ready for building!")
        print("   You can now run: python build_app.py")
        return 0
    except Exception as e:
        print(f"❌ Error creating icon: {e}")
        return 1


if __name__ == "__main__":
    exit(main())

