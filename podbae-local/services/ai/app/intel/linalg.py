"""Dense products WITHOUT numpy's BLAS.

In the torch_gpu conda env, numpy's OpenBLAS is built against LLVM OpenMP (libomp.dll) while torch ships Intel OpenMP
(libiomp5md.dll). Once torch has run, a large numpy BLAS call aborts the process ("OMP: Error #15"); if numpy's BLAS runs
first, torch then fails to load (WinError 127 on fbgemm.dll). np.einsum with optimize=False uses numpy's own loops, never
BLAS, so the intelligence code uses these helpers for every matrix/vector product. Our sizes (<= a few hundred x 384) make
the speed difference irrelevant."""
from __future__ import annotations

import numpy as np


def mm(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """a @ b for 2-D a (n x k) and 2-D b (k x m), or 1-D b (k)."""
    return np.einsum("ij,j->i", a, b, optimize=False) if b.ndim == 1 else np.einsum("ij,jk->ik", a, b, optimize=False)


def gram(a: np.ndarray) -> np.ndarray:
    """a @ a.T"""
    return np.einsum("ij,kj->ik", a, a, optimize=False)


def dot(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.einsum("i,i->", a, b, optimize=False))


def norm(a: np.ndarray) -> float:
    return float(np.sqrt(np.einsum("i,i->", a, a, optimize=False)))
