"""PCA projection — flatten onto the plane of greatest variance.

SVD of the centred point cloud; take the two principal directions as
the 2D basis. Structure-aligned — the rune's dominant spread always
lies along the canvas X axis.
"""

import numpy as np
from pipeline.rune_map import RuneMap
from pipeline.output.project_methods._util import normalize


def project(rune_map: RuneMap) -> np.ndarray:
    pts          = rune_map.blended
    pts_centered = pts - pts.mean(axis=0)

    _, _, vh = np.linalg.svd(pts_centered, full_matrices=False)
    basis    = vh[:2].T                        # (3, 2)
    proj     = pts_centered @ basis

    return normalize(proj)
