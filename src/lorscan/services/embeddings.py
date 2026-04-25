"""Local card-image recognition via SigLIP embeddings.

Pipeline:
1. Download every catalog card image once (cached in ~/.lorscan/cache/images/)
2. Run each through SigLIP ViT-B-16 → 768-dim float32 embedding
3. Store all embeddings + their card_ids in ~/.lorscan/embeddings.npz
4. At scan time: detect/warp each card, embed it, find the nearest catalog
   embedding by cosine similarity. ~80ms per card on Apple Silicon MPS,
   brute-force over ~2300 vectors.

Why SigLIP over the original ViT-B-32: SigLIP is trained with sigmoid loss
specifically for fine-grained instance retrieval (image ↔ caption alignment
without the full softmax across the batch), and uses 16×16 patches instead
of 32×32, giving ~4× more spatial detail per image. On Lorcana cards, the
coarse ViT-B-32 latched onto dominant color palettes (every orange-toned
Location looked alike); SigLIP can distinguish actual artwork content.

This bypasses the LLM entirely for the "is this catalog card X?" question,
which is what binder organization needs.
"""

from __future__ import annotations

import io
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image

# SigLIP ViT-B-16 from the WebLI dataset. Loads via OpenCLIP; the model
# weights live on HuggingFace and are downloaded + cached on first use.
DEFAULT_MODEL_NAME = "ViT-B-16-SigLIP"
DEFAULT_PRETRAINED = "webli"
EMBEDDING_DIM = 768  # SigLIP-B/16 output dimension


@dataclass(frozen=True)
class Match:
    """One nearest-neighbor lookup result."""

    card_id: str
    similarity: float


def _detect_device() -> str:
    """Pick the best available compute device."""
    import torch

    if torch.backends.mps.is_available():
        return "mps"
    if torch.cuda.is_available():
        return "cuda"
    return "cpu"


def _load_clip_model(device: str | None = None):
    """Load SigLIP ViT-B/16 + its preprocessor. ~750MB first time, cached after."""
    import open_clip

    device = device or _detect_device()
    model, _, preprocess = open_clip.create_model_and_transforms(
        DEFAULT_MODEL_NAME, pretrained=DEFAULT_PRETRAINED
    )
    model = model.to(device).eval()
    return model, preprocess, device


def _normalize(vec: np.ndarray) -> np.ndarray:
    """L2-normalize a 1D or 2D array along the last axis."""
    norm = np.linalg.norm(vec, axis=-1, keepdims=True)
    norm = np.where(norm == 0, 1.0, norm)
    return vec / norm


class CardImageIndex:
    """In-memory index of catalog card embeddings.

    Pure data + lookup. Building/saving lives in this class; the higher-level
    "go fetch all images and build the index" lives in `build_index_for_catalog`.
    """

    def __init__(self, card_ids: list[str], embeddings: np.ndarray):
        if embeddings.ndim != 2 or embeddings.shape[0] != len(card_ids):
            raise ValueError("embeddings must be (N, dim) with one row per card_id")
        self.card_ids = card_ids
        # Pre-normalize so cosine similarity is just a dot product.
        self.embeddings = _normalize(embeddings.astype(np.float32))

    @classmethod
    def empty(cls) -> CardImageIndex:
        return cls([], np.zeros((0, EMBEDDING_DIM), dtype=np.float32))

    @property
    def size(self) -> int:
        return len(self.card_ids)

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        np.savez_compressed(
            path,
            card_ids=np.array(self.card_ids, dtype=object),
            embeddings=self.embeddings,
        )

    @classmethod
    def load(cls, path: Path) -> CardImageIndex:
        data = np.load(path, allow_pickle=True)
        embeddings = data["embeddings"]
        if embeddings.ndim == 2 and embeddings.shape[1] != EMBEDDING_DIM:
            raise ValueError(
                f"embedding-dim mismatch: index at {path} has dim "
                f"{embeddings.shape[1]} but the current model produces "
                f"{EMBEDDING_DIM}. Re-run `lorscan index-images` to rebuild "
                f"with the new model."
            )
        return cls(list(data["card_ids"]), embeddings)

    def find_matches(self, query_embedding: np.ndarray, *, top_k: int = 5) -> list[Match]:
        """Cosine similarity nearest-neighbor lookup.

        query_embedding: 1D vector of shape (dim,) or 2D (1, dim). Will be L2-normalized.
        """
        if self.size == 0:
            return []
        q = _normalize(query_embedding.astype(np.float32))
        if q.ndim == 1:
            q = q.reshape(1, -1)
        # (N, dim) @ (dim,) → (N,)
        sims = (self.embeddings @ q[0]).astype(float)
        top_idx = np.argsort(-sims)[:top_k]
        return [Match(card_id=self.card_ids[i], similarity=float(sims[i])) for i in top_idx]


def encode_image(model, preprocess, device: str, image: Image.Image) -> np.ndarray:
    """Run a single PIL image through CLIP. Returns a (EMBEDDING_DIM,) float32 vector."""
    import torch

    if image.mode != "RGB":
        image = image.convert("RGB")
    tensor = preprocess(image).unsqueeze(0).to(device)
    with torch.no_grad():
        features = model.encode_image(tensor)
    return features.detach().cpu().numpy().astype(np.float32)[0]


def encode_image_bytes(model, preprocess, device: str, image_bytes: bytes) -> np.ndarray:
    """Convenience wrapper: encode raw image bytes."""
    image = Image.open(io.BytesIO(image_bytes))
    image.load()
    return encode_image(model, preprocess, device, image)


def encode_images_batch(
    model,
    preprocess,
    device: str,
    images: list[Image.Image],
) -> np.ndarray:
    """Batch-encode multiple images. Returns (N, EMBEDDING_DIM) float32 array.

    Batching gives a meaningful speedup (~3–5×) on MPS/CUDA.
    """
    import torch

    if not images:
        return np.zeros((0, EMBEDDING_DIM), dtype=np.float32)
    tensors = []
    for img in images:
        if img.mode != "RGB":
            img = img.convert("RGB")
        tensors.append(preprocess(img))
    batch = torch.stack(tensors).to(device)
    with torch.no_grad():
        features = model.encode_image(batch)
    return features.detach().cpu().numpy().astype(np.float32)


__all__ = [
    "CardImageIndex",
    "DEFAULT_MODEL_NAME",
    "DEFAULT_PRETRAINED",
    "EMBEDDING_DIM",
    "Match",
    "encode_image",
    "encode_image_bytes",
    "encode_images_batch",
    "_detect_device",
    "_load_clip_model",
]
