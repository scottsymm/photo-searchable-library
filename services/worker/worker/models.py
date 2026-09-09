"""Local CLIP model wrapper."""

from __future__ import annotations

from collections.abc import Sequence

import torch
from PIL import Image
from transformers import CLIPModel, CLIPProcessor


class ClipEmbedder:
    def __init__(self, model_name: str):
        self.name = model_name
        self.model = CLIPModel.from_pretrained(model_name)
        self.processor = CLIPProcessor.from_pretrained(model_name)
        self.model.eval()

    @staticmethod
    def _tensor(output):
        return output.pooler_output if hasattr(output, "pooler_output") else output

    @torch.no_grad()
    def embed_images(self, images: Sequence[Image.Image]) -> list[list[float]]:
        inputs = self.processor(images=list(images), return_tensors="pt")
        features = self._tensor(self.model.get_image_features(**inputs))
        features = features / features.norm(dim=-1, keepdim=True)
        return features.cpu().numpy().tolist()

    @torch.no_grad()
    def embed_text(self, texts: Sequence[str]) -> list[list[float]]:
        inputs = self.processor(
            text=list(texts), return_tensors="pt", padding=True, truncation=True
        )
        features = self._tensor(self.model.get_text_features(**inputs))
        features = features / features.norm(dim=-1, keepdim=True)
        return features.cpu().numpy().tolist()
