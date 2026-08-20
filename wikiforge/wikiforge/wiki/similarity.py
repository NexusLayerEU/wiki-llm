"""Local lexical similarity, used where the spec used provider embeddings.

SwitchBoard serves no embeddings endpoint (`/v1/embeddings` 404s for the NVIDIA
model, and no embedding model is listed), and ModelRouter never had one. Rather
than add a vector service for one pre-filter, cross-linking scores pages with
TF-IDF cosine computed in-process.

The trade-off is honest: this matches on shared vocabulary, not meaning, so it
will miss two pages that discuss the same thing in different words. It is a
*pre-filter* — the LLM crosslink stage still judges the candidates it produces,
which is where semantic understanding enters. Swapping this for real embeddings
means reimplementing `score_against` alone.
"""
import math
import re
from collections import Counter

import numpy as np

_TOKEN = re.compile(r"[A-Za-zÀ-ɏͰ-ϿЀ-ӿ][\wÀ-ɏͰ-ϿЀ-ӿ-]{2,}")

#: Words too common to carry signal. Deliberately short — a domain stop-word list
#: would have to be per-corpus, and IDF already suppresses frequent terms.
_STOP = frozenset("""
the and for that with this from are was were will has have had not but you your его
they their its into out over under more most other such only own same than then once
here there when where which while who whom why how all any both each few nor own too
very can just should now also may might must shall would could about above after
""".split())

_VECTOR_SIZE = 512  # Hashed dimensionality; keeps every page vector the same shape.


def tokenise(text: str) -> list[str]:
    return [
        token.lower()
        for token in _TOKEN.findall(text or "")
        if token.lower() not in _STOP
    ]


def vectorise(text: str) -> np.ndarray:
    """Hash tokens into a fixed-width L2-normalised term-frequency vector.

    Hashing rather than a learned vocabulary means a page can be vectorised on its
    own, without a corpus pass — which matters because pages are published one at a
    time and must be comparable to pages written weeks earlier.
    """
    counts = Counter(tokenise(text))
    vector = np.zeros(_VECTOR_SIZE, dtype="float32")
    if not counts:
        return vector
    for token, count in counts.items():
        # Sublinear term frequency: a word used 50 times is not 50x as informative.
        vector[hash(token) % _VECTOR_SIZE] += 1.0 + math.log(count)
    norm = float(np.linalg.norm(vector))
    return vector if norm == 0.0 else vector / norm


def to_bytes(vector: np.ndarray) -> bytes:
    return np.asarray(vector, dtype="float32").tobytes()


def from_bytes(raw: bytes | None) -> np.ndarray | None:
    if not raw:
        return None
    vector = np.frombuffer(raw, dtype="float32")
    return vector if vector.size == _VECTOR_SIZE else None


def cosine(left: np.ndarray, right: np.ndarray) -> float:
    """Both inputs are already normalised, so this is a dot product."""
    if left is None or right is None or left.size != right.size:
        return 0.0
    return float(np.clip(np.dot(left, right), -1.0, 1.0))
