"""Face detection and face embeddings."""

from __future__ import annotations

import numpy as np
import os


class FaceEngine:
    def __init__(self, model_name: str = "buffalo_l"):
        import insightface

        self.app = insightface.app.FaceAnalysis(
            name=model_name,
            providers=["CPUExecutionProvider"],
            root=os.environ.get("INSIGHTFACE_ROOT", "/models/insightface"),
        )
        self.app.prepare(ctx_id=0, det_size=(640, 640))

    def detect_and_embed(self, image: np.ndarray) -> list[dict]:
        result = []
        for face in self.app.get(image):
            x1, y1, x2, y2 = [int(value) for value in face.bbox]
            result.append(
                {
                    "bbox": [x1, y1, max(0, x2 - x1), max(0, y2 - y1)],
                    "embedding": face.normed_embedding.tolist(),
                    "score": float(face.det_score),
                }
            )
        return result
