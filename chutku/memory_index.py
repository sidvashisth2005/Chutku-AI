"""Meaning-based memory search (master plan S12): multilingual-e5-small, int8 ONNX, on the CPU, fully local.

Word overlap (Jaccard) misses "woh gaana lagao" vs "play that song" and Hindi script vs Roman spelling. Texts are
first read as Roman Hinglish (translit.roman), then embedded; vectors are cached in data/embeddings.sqlite by text
hash, so each text is embedded once. People's names are never matched this way (messages must reach the exact
person); that stays exact in chutku/mind.py.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sqlite3
import threading

from chutku.core.paths import home as _home
PROJECT_ROOT = _home()   # W2: Chutku's state root (the repo itself in a git checkout)
MAX_TOKENS = 128
_lock = threading.Lock()
_model = {"key": None, "session": None, "tokenizer": None}


class EmbeddingsUnavailable(OSError):
    pass


def _files(base):
    try:
        from chutku.core.paths import resource
        entry = json.loads(resource(base, "models/manifest.json").read_text(encoding="utf-8"))["embed"]
    except (OSError, ValueError, KeyError) as error:
        raise EmbeddingsUnavailable("No embedding model is set up.") from error
    from chutku.core import hashcache
    paths = {}
    for part in ("model", "tokenizer"):
        item = entry[part]
        from chutku.core.paths import model_file
        path = model_file(base, item["path"], nested=True)
        if path is None or not path.is_file():
            raise EmbeddingsUnavailable("The embedding model files are missing.")
        if not hashcache.matches(path, item["sha256"]):
            raise EmbeddingsUnavailable(f"{path.name} does not match its pinned hash; not loading it.")
        paths[part] = path
    return paths


def _load(base):
    paths = _files(base)
    key = (str(paths["model"]), str(paths["tokenizer"]))
    with _lock:
        if _model["key"] != key:
            import onnxruntime
            from tokenizers import Tokenizer
            options = onnxruntime.SessionOptions()
            options.intra_op_num_threads = 4
            session = onnxruntime.InferenceSession(str(paths["model"]), options, providers=["CPUExecutionProvider"])
            tokenizer = Tokenizer.from_file(str(paths["tokenizer"]))
            tokenizer.enable_truncation(MAX_TOKENS)
            tokenizer.enable_padding(pad_id=1, pad_token="<pad>")
            _model.update(key=key, session=session, tokenizer=tokenizer)
        return _model["session"], _model["tokenizer"]


def available(base=PROJECT_ROOT):
    try:
        _files(base)
        return True
    except EmbeddingsUnavailable:
        return False

def _text_key(kind, text):
    return hashlib.sha256(f"{kind}\0{text}".encode("utf-8")).hexdigest()


class _Cache:
    """data/embeddings.sqlite: (key -> vector bytes). Embedding is the slow part; reading back is instant."""

    def __init__(self, base):
        path = Path(base) / "data" / "embeddings.sqlite"
        path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(path)
        self.connection.execute("CREATE TABLE IF NOT EXISTS vectors (key TEXT PRIMARY KEY, vector BLOB NOT NULL)")

    def get(self, keys):
        found = {}
        for start in range(0, len(keys), 500):
            chunk = keys[start:start + 500]
            marks = ",".join("?" * len(chunk))   # only placeholders; the keys are bound parameters
            found.update(self.connection.execute(f"SELECT key, vector FROM vectors WHERE key IN ({marks})", chunk))  # nosec B608
        return found

    def put(self, rows):
        self.connection.executemany("INSERT OR REPLACE INTO vectors VALUES (?, ?)", rows)
        self.connection.commit()

    def close(self):
        self.connection.close()


def embed(texts, kind="passage", base=PROJECT_ROOT):
    """L2-normalised vectors (numpy, one row per text). kind is "query" or "passage" (e5's two roles)."""
    import numpy as np
    from chutku.translit import roman
    clean = [" ".join(roman(str(text)).split())[:600] for text in texts]
    keys = [_text_key(kind, text) for text in clean]
    cache = _Cache(base)
    try:
        known = cache.get(keys)
        missing = [(key, text) for key, text in zip(keys, clean) if key not in known]
        if missing:
            session, tokenizer = _load(base)
            new_rows = []
            for start in range(0, len(missing), 32):
                batch = missing[start:start + 32]
                encoded = tokenizer.encode_batch([f"{kind}: {text}" for _key, text in batch])
                ids = np.array([e.ids for e in encoded], dtype=np.int64)
                mask = np.array([e.attention_mask for e in encoded], dtype=np.int64)
                feeds = {"input_ids": ids, "attention_mask": mask}
                if any(i.name == "token_type_ids" for i in session.get_inputs()):
                    feeds["token_type_ids"] = np.zeros_like(ids)
                hidden = session.run(None, feeds)[0]
                pooled = (hidden * mask[..., None]).sum(1) / np.maximum(mask.sum(1, keepdims=True), 1)
                pooled /= np.maximum(np.linalg.norm(pooled, axis=1, keepdims=True), 1e-9)
                new_rows += [(key, vector.astype(np.float32).tobytes()) for (key, _t), vector in zip(batch, pooled)]
            cache.put(new_rows)
            known.update(dict(new_rows))
        return np.stack([np.frombuffer(known[key], dtype=np.float32) for key in keys]) if keys else np.zeros((0, 384))
    finally:
        cache.close()


def rank(query, passages, base=PROJECT_ROOT):
    """[(score, index)] best first: cosine similarity of the query to each passage."""
    if not passages:
        return []
    import numpy as np
    vectors = embed(passages, "passage", base)
    scores = vectors @ embed([query], "query", base)[0]
    order = np.argsort(-scores)
    return [(float(scores[i]), int(i)) for i in order]
