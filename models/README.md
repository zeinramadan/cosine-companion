# Models Directory

This directory contains the machine learning models required for audio similarity analysis.

## Required Model

### Discogs-EffNet Audio Embeddings Model

**File:** `discogs_multi_embeddings-effnet-bs64-1.pb`

**Download Link:** [Essentia Models Repository](https://essentia.upf.edu/models/feature-extractors/discogs_multi_embeddings/discogs_multi_embeddings-effnet-bs64-1.pb)

**Direct Download:**
```bash
wget https://essentia.upf.edu/models/feature-extractors/discogs_multi_embeddings/discogs_multi_embeddings-effnet-bs64-1.pb
```

Or using curl:
```bash
curl -O https://essentia.upf.edu/models/feature-extractors/discogs_multi_embeddings/discogs_multi_embeddings-effnet-bs64-1.pb
```

### Model Information

- **Purpose:** Generates high-dimensional embeddings from audio content for similarity analysis
- **Architecture:** EfficientNet-based model trained on Discogs dataset
- **Input:** 16kHz mono audio
- **Output:** 128-dimensional embedding vector
- **File Size:** ~23MB
- **License:** Check Essentia's licensing terms

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
- Ensure the file downloaded completely (~23MB)

**TensorFlow prediction errors:**
- Make sure you have `essentia-tensorflow` installed: `pip install essentia-tensorflow`
- Try reinstalling essentia: `conda install -c mtg essentia-tensorflow`

### Alternative Models

This application currently supports only the Discogs-EffNet model. Future versions may support additional embedding models from the Essentia collection.

For more information about Essentia models, visit: https://essentia.upf.edu/models.html
