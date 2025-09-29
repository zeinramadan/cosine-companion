#!/usr/bin/env python3
"""Audio embedding generation using Essentia Discogs-EffNet model."""

from pathlib import Path
from typing import Optional

import numpy as np
import essentia.standard as es

from config import DEFAULT_SAMPLE_RATE, MODELS


class DiscogsEffnetEmbedder:
    """
    Audio embedder using Essentia's TensorflowPredictEffnetDiscogs model.

    Generates embeddings for audio files by processing audio frames and
    pooling the results with mean and standard deviation.
    """

    def __init__(
        self,
        model_path: Optional[str] = None,
        sr: int = DEFAULT_SAMPLE_RATE,
    ):
        """
        Initialize the embedder.

        Args:
            model_path: Path to the TensorFlow model file (optional). Defaults to
                        'models/discogs_multi_embeddings-effnet-bs64-1.pb'
            sr: Target sample rate
        """
        self.sr = sr

        # Use the standard Discogs multi-embeddings model
        model_file = model_path or (MODELS / "discogs_multi_embeddings-effnet-bs64-1.pb")
        
        if not Path(model_file).exists():
            raise RuntimeError(
                f"Model not found: {model_file}\n"
                "Please download the model from: "
                "https://essentia.upf.edu/models/feature-extractors/discogs_multi_embeddings/discogs_multi_embeddings-effnet-bs64-1.pb"
            )

        try:
            # Initialize predictor with known output node for discogs_multi_embeddings model
            self.pred = es.TensorflowPredictEffnetDiscogs(
                graphFilename=str(model_file),
                output="PartitionedCall:1",
            )
        except AttributeError as e:
            raise RuntimeError(
                "Your Essentia installation does not include 'TensorflowPredictEffnetDiscogs'. "
                "Install Essentia with TensorFlow support: pip install essentia-tensorflow"
            ) from e
        except Exception as e:
            raise RuntimeError(
                f"Failed to load model {model_file}. "
                "Ensure you have the correct discogs_multi_embeddings-effnet-bs64-1.pb model."
            ) from e


    def embed_file(self, path_local: str) -> Optional[np.ndarray]:
        """
        Generate embedding for an audio file.

        Args:
            path_local: Local file path to the audio file

        Returns:
            Normalized embedding vector as float32 numpy array, or None if failed
        """
        try:
            # Load audio using Essentia's MonoLoader (resamples to target sr automatically)
            loader = es.MonoLoader(filename=path_local, sampleRate=self.sr, resampleQuality=4)
            audio = loader()
            
            # Direct model inference on the whole audio per Essentia docs
            pred_out = self.pred(audio)
            Y = np.asarray(pred_out)
            if Y.size == 0 or not np.isfinite(Y).all():
                return None
                
            # Pool along time/frame axis if present
            if Y.ndim == 1:
                pooled = Y
            elif Y.ndim == 2:
                pooled = np.concatenate([Y.mean(axis=0), Y.std(axis=0)])
            else:
                # Collapse extra dims then pool
                Y2 = Y.reshape(Y.shape[0], -1)
                pooled = np.concatenate([Y2.mean(axis=0), Y2.std(axis=0)])

            # L2 normalize
            pooled = pooled / (np.linalg.norm(pooled) + 1e-9)
            return pooled.astype("float32")
            
        except Exception as e:
            # If audio loading fails, return None (will be logged by caller)
            return None


