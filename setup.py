#!/usr/bin/env python3
"""Setup script for Cosine Companion."""

from setuptools import setup, find_packages
from pathlib import Path

# Read README
readme = Path("README.md").read_text(encoding="utf-8")

setup(
    name="cosine-companion",
    version="1.0.0",
    author="Zein Ramadan",
    author_email="zeinbassemramadan@gmail.com",
    description="AI-powered music companion for DJs - find similar tracks and create seamless sets",
    long_description=readme,
    long_description_content_type="text/markdown",
    url="https://github.com/zeinramadan/cosine-companion",
    packages=find_packages(where="src"),
    package_dir={"": "src"},
    python_requires=">=3.8",
    install_requires=[
        "numpy>=1.20.0",
        "pandas>=1.3.0",
        "lxml>=4.6.0",
        "soundfile>=0.10.0",
        "essentia-tensorflow>=2.1b6",
        "faiss-cpu>=1.7.0",
        "typer>=0.4.0",
    ],
    extras_require={
        "dev": [
            "pytest>=6.0.0",
            "pytest-cov>=2.12.0",
            "black>=21.0.0",
            "pylint>=2.8.0",
        ],
    },
    entry_points={
        "console_scripts": [
            "cosine-companion=cosine_companion:cli",
        ],
        "gui_scripts": [
            "cosine-companion-ui=cosine_companion:ui",
        ],
    },
    classifiers=[
        "Development Status :: 4 - Beta",
        "Intended Audience :: End Users/Desktop",
        "Topic :: Multimedia :: Sound/Audio",
        "License :: OSI Approved :: MIT License",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
    ],
    keywords="dj music recommendation ai similarity audio",
    project_urls={
        "Bug Reports": "https://github.com/zeinramadan/cosine-companion/issues",
        "Source": "https://github.com/zeinramadan/cosine-companion",
    },
)
