"""Meaning-based memory search plumbing (master plan S12). The real model is never loaded in tests."""
from pathlib import Path
import tempfile
import types
import unittest
from unittest.mock import patch

import numpy as np

from chutku import memory_index


class FakeTokenizer:
    def encode_batch(self, texts):
        return [types.SimpleNamespace(ids=[len(t) % 7, 3], attention_mask=[1, 1]) for t in texts]


class FakeSession:
    def __init__(self):
        self.calls = 0

    def get_inputs(self):
        return [types.SimpleNamespace(name="input_ids"), types.SimpleNamespace(name="attention_mask")]

    def run(self, _outputs, feeds):
        self.calls += 1
        ids = feeds["input_ids"]
        hidden = np.zeros((ids.shape[0], ids.shape[1], 4), dtype=np.float32)
        hidden[:, :, 0] = ids   # different texts -> different vectors
        hidden[:, :, 1] = 1.0
        return [hidden]


class EmbeddingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.session = FakeSession()
        patcher = patch.object(memory_index, "_load", return_value=(self.session, FakeTokenizer()))
        patcher.start()
        self.addCleanup(patcher.stop)

    def tearDown(self):
        self.temp.cleanup()

    def test_vectors_are_normalised_and_cached(self):
        first = memory_index.embed(["open notepad", "play lofi"], base=self.base)
        self.assertEqual(first.shape[0], 2)
        self.assertTrue(np.allclose(np.linalg.norm(first, axis=1), 1.0))
        calls = self.session.calls
        again = memory_index.embed(["open notepad", "play lofi"], base=self.base)
        self.assertEqual(self.session.calls, calls)   # read back from data/embeddings.sqlite, not recomputed
        self.assertTrue(np.allclose(first, again))

    def test_hindi_script_is_read_as_roman_first(self):
        seen = []
        tokenizer = FakeTokenizer()
        original = tokenizer.encode_batch
        tokenizer.encode_batch = lambda texts: seen.extend(texts) or original(texts)
        with patch.object(memory_index, "_load", return_value=(self.session, tokenizer)):
            memory_index.embed(["हाँ"], base=self.base)
        self.assertTrue(seen and seen[0].isascii())

    def test_rank_is_best_first(self):
        ranked = memory_index.rank("abc", ["abcdefg", "abc", "x"], base=self.base)
        self.assertEqual(sorted(i for _, i in ranked), [0, 1, 2])
        self.assertGreaterEqual(ranked[0][0], ranked[-1][0])

    def test_missing_model_is_reported_not_guessed(self):
        with patch.object(memory_index, "_load", side_effect=memory_index.EmbeddingsUnavailable("no model")):
            with self.assertRaises(memory_index.EmbeddingsUnavailable):
                memory_index.embed(["new text never seen"], base=self.base)


if __name__ == "__main__":
    unittest.main()
