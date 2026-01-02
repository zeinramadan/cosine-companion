# Models Directory

This directory contains the machine learning models required for audio similarity analysis.

## Required Model

### Discogs-EffNet Audio Embeddings Model

**File:** `discogs_multi_embeddings-effnet-bs64-1.pb`

**Download Link:** [Essentia Models Repository](https://essentia.upf.edu/models/feature-extractors/discogs_multi_embeddings/)

**Direct Download:**
```bash
wget https://essentia.upf.edu/models/feature-extractors/discogs_multi_embeddings/discogs_multi_embeddings-effnet-bs64-1.pb
```

Or using curl:
```bash
curl -O https://essentia.upf.edu/models/feature-extractors/discogs_multi_embeddings/discogs_multi_embeddings-effnet-bs64-1.pb
```

### Model Information

| Attribute | Value |
|-----------|-------|
| **Purpose** | Generates embeddings from audio for similarity analysis |
| **Architecture** | EfficientNet-based model trained on Discogs dataset |
| **Input** | 32kHz mono audio |
| **Raw Output** | Frame-wise embeddings (variable length) |
| **Pooled Output** | 256-dimensional vector (mean + std pooling) |
| **File Size** | ~300 MB |
| **License** | See [Essentia licensing terms](https://essentia.upf.edu/licensing_information.html) |

### Installation Steps

1. Download the model file to this `models/` directory
2. Ensure the filename is exactly: `discogs_multi_embeddings-effnet-bs64-1.pb`
3. The application will automatically detect and load the model on startup

### Verification

After downloading, your `models/` directory should contain:
```
models/
├── README.md (this file)
└── discogs_multi_embeddings-effnet-bs64-1.pb
```

### Troubleshooting

**Model not found error:**
- Verify the file is in the `models/` directory
- Check the filename matches exactly (case-sensitive)
- Ensure the file downloaded completely (~300 MB)

**TensorFlow prediction errors:**
- Make sure you have `essentia-tensorflow` installed: `pip install essentia-tensorflow`
- Try reinstalling essentia: `conda install -c mtg essentia-tensorflow`

### How Embeddings Work

The embedding process:
1. Audio is loaded and resampled to 32kHz mono
2. The model processes the audio in frames
3. Frame embeddings are pooled using mean + standard deviation
4. The result is L2-normalized for cosine similarity search

For technical details, see [docs/EMBEDDINGS_GUIDE.md](../docs/EMBEDDINGS_GUIDE.md).

### More Information

- [Essentia Models Documentation](https://essentia.upf.edu/models.html)
- [Discogs-EffNet Paper](https://essentia.upf.edu/models/feature-extractors/discogs_multi_embeddings/)
