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
        output_node: Optional[str] = None,
        sr: int = DEFAULT_SAMPLE_RATE,
    ):
        """
        Initialize the embedder.

        Args:
            model_path: Path to the TensorFlow model file (optional). If not provided,
                        attempts to load from models/ directory.
            sr: Target sample rate
        """
        self.sr = sr

        resolved_model = model_path or self._find_default_model()
        if not resolved_model:
            raise RuntimeError(
                "EffNet model not found. Place the model file in models/ (e.g., 'models/effnet-discogs.pb') "
                "or pass model_path=... to DiscogsEffnetEmbedder."
            )

        # Initialize predictor; try provided or common output node names if default fails
        last_err: Optional[Exception] = None
        candidate_nodes = [output_node] if output_node else [
            "PartitionedCall:1",  # Essentia docs recommended output tensor for Discogs Effnet
            "embeddings",
            "StatefulPartitionedCall",
            "PartitionedCall",
            "StatefulPartitionedCall_1",
        ]
        for node in candidate_nodes:
            try:
                self.pred = es.TensorflowPredictEffnetDiscogs(
                    graphFilename=str(resolved_model),
                    output=node,
                )
                self._output_node = node
                last_err = None
                break
            except AttributeError as e:
                available_tf = [name for name in dir(es) if name.lower().startswith("tensorflow")]
                raise RuntimeError(
                    "Your Essentia installation does not include 'TensorflowPredictEffnetDiscogs'. "
                    "Install Essentia with TensorFlow support (e.g., 'pip install essentia-tensorflow') "
                    "or use a supported predictor. Available TensorFlow-related algorithms: "
                    f"{available_tf}"
                ) from e
            except Exception as e:  # includes invalid node names
                last_err = e
                continue

        if last_err is not None:
            raise RuntimeError(
                "Failed to configure TensorflowPredictEffnetDiscogs with known output node names. "
                "Tried: 'embeddings', 'StatefulPartitionedCall', 'PartitionedCall'. "
                f"Set a compatible model or pass a known-good .pb matching the wrapper. Underlying error: {last_err}"
            )

    def _find_default_model(self) -> Optional[Path]:
        """Return a model path from models/ if available."""
        candidates = [
            MODELS / "discogs_multi_embeddings-effnet-bs64-1.pb",  # Primary model
            MODELS / "effnet-discogs.pb",
            MODELS / "DiscogsEffnet.pb", 
            MODELS / "effnet.pb",
        ]
        for p in candidates:
            if p.exists():
                return p
        return None

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


