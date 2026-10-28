"""Passages into vectors, offline.

The default model is ``intfloat/multilingual-e5-small`` (MIT, 384 dimensions, Portuguese and
English in one space), run with onnxruntime and tokenizers from files bundled in the image
(``DOCCRAFT_EMBEDDING_DIR``: ``model.onnx`` and ``tokenizer.json``). Nothing is downloaded at run
time. Without the files (a development checkout, the tests), ``HashEmbedder`` stands in: words
hashed into the same 384 dimensions, so search by words still works and every path is exercised.
"""

from __future__ import annotations

import hashlib
import logging
import re
from functools import lru_cache
from pathlib import Path
from typing import Protocol

import numpy as np

DIMENSIONS = 384
log = logging.getLogger(__name__)


class Embedder(Protocol):
    name: str

    def passages(self, texts: list[str]) -> np.ndarray: ...

    def query(self, text: str) -> np.ndarray: ...


class HashEmbedder:
    """A stand-in with no model: each word (and word pair) hashed into a signed bucket."""

    name = "hash-384"

    def _one(self, text: str) -> np.ndarray:
        vector = np.zeros(DIMENSIONS, dtype=np.float32)
        words = re.findall(r"\w+", text.lower())
        for gram in words + [f"{a} {b}" for a, b in zip(words, words[1:])]:
            digest = hashlib.blake2b(gram.encode(), digest_size=8).digest()
            bucket = int.from_bytes(digest[:4], "little") % DIMENSIONS
            vector[bucket] += 1.0 if digest[4] & 1 else -1.0
        norm = np.linalg.norm(vector)
        return vector / norm if norm else vector

    def passages(self, texts: list[str]) -> np.ndarray:
        return (
            np.stack([self._one(text) for text in texts])
            if texts
            else np.zeros((0, DIMENSIONS), np.float32)
        )

    def query(self, text: str) -> np.ndarray:
        return self._one(text)


class OnnxE5:
    """multilingual-e5-small in ONNX: "passage: " and "query: " prefixes, mean pooling, L2 norm."""

    name = "multilingual-e5-small"
    BATCH = 16
    MAX_TOKENS = 512

    def __init__(self, folder: Path, threads: int = 2):
        import onnxruntime
        from tokenizers import Tokenizer

        self.tokenizer = Tokenizer.from_file(str(folder / "tokenizer.json"))
        self.tokenizer.enable_truncation(self.MAX_TOKENS)
        self.tokenizer.enable_padding(pad_id=1, pad_token="<pad>")
        options = onnxruntime.SessionOptions()
        options.intra_op_num_threads = threads
        self.session = onnxruntime.InferenceSession(
            str(folder / "model.onnx"), options, providers=["CPUExecutionProvider"]
        )
        self.inputs = {item.name for item in self.session.get_inputs()}

    def _encode(self, texts: list[str]) -> np.ndarray:
        out = []
        for start in range(0, len(texts), self.BATCH):
            batch = self.tokenizer.encode_batch(texts[start : start + self.BATCH])
            ids = np.array([item.ids for item in batch], dtype=np.int64)
            mask = np.array([item.attention_mask for item in batch], dtype=np.int64)
            feed = {"input_ids": ids, "attention_mask": mask}
            if "token_type_ids" in self.inputs:
                feed["token_type_ids"] = np.zeros_like(ids)
            hidden = self.session.run(None, feed)[0]
            summed = (hidden * mask[:, :, None]).sum(axis=1)
            vectors = summed / np.clip(mask.sum(axis=1, keepdims=True), 1, None)
            out.append(vectors / np.linalg.norm(vectors, axis=1, keepdims=True))
        return (
            np.concatenate(out).astype(np.float32) if out else np.zeros((0, DIMENSIONS), np.float32)
        )

    def passages(self, texts: list[str]) -> np.ndarray:
        return self._encode([f"passage: {text}" for text in texts])

    def query(self, text: str) -> np.ndarray:
        return self._encode([f"query: {text}"])[0]


@lru_cache(maxsize=4)
def embedder(folder: str | None) -> Embedder:
    if (
        folder
        and (Path(folder) / "model.onnx").is_file()
        and (Path(folder) / "tokenizer.json").is_file()
    ):
        try:
            return OnnxE5(Path(folder))
        except Exception as error:  # a broken model file: search by words still works
            log.warning("embedding model in %s not loaded: %s", folder, error)
    return HashEmbedder()
