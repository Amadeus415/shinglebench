"""Image generation: one provider shared by every model under test.

The mock draws a deterministic, clearly labeled placeholder so layouts and ad specs can be
checked offline. OpenAIImages calls the Images API when OPENAI_API_KEY is set.
"""

from __future__ import annotations

import base64
import hashlib
import io
import textwrap

import httpx
from PIL import Image, ImageDraw, ImageFont

SIZES = {"square": (1080, 1080), "portrait": (1080, 1350), "landscape": (1200, 628), "hero": (1600, 900)}


def _font(size: int) -> ImageFont.ImageFont:
    for name in ("DejaVuSans.ttf", "Arial.ttf", "/System/Library/Fonts/Supplemental/Arial.ttf", "/System/Library/Fonts/Helvetica.ttc"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default(size)


class MockImages:
    name = "mock-images-v1"

    def generate(self, prompt: str, size: str = "square", seed: int = 0) -> bytes:
        w, h = SIZES[size]
        digest = hashlib.sha256(f"{prompt}|{seed}".encode()).digest()
        c1 = tuple(60 + b % 160 for b in digest[:3])
        c2 = tuple(60 + b % 160 for b in digest[3:6])
        img = Image.new("RGB", (w, h), c1)
        d = ImageDraw.Draw(img)
        for y in range(h):  # vertical gradient
            t = y / h
            d.line([(0, y), (w, y)], fill=tuple(int(c1[i] * (1 - t) + c2[i] * t) for i in range(3)))
        # simple deterministic shapes so different prompts look different
        for i in range(3):
            b = digest[6 + i * 4: 10 + i * 4]
            x, y, r = b[0] / 255 * w, b[1] / 255 * h, 60 + b[2] / 255 * min(w, h) / 3
            d.ellipse([x - r, y - r, x + r, y + r], outline=(255, 255, 255), width=4)
        pad = int(w * 0.07)
        d.rectangle([pad, h - pad - int(h * 0.36), w - pad, h - pad], fill=(255, 255, 255))
        f_small, f_big = _font(max(18, w // 45)), _font(max(24, w // 30))
        d.text((pad + 20, h - pad - int(h * 0.36) + 16), "PLACEHOLDER · mock image generator", fill=(150, 30, 30), font=f_small)
        lines = textwrap.wrap(prompt, width=max(20, w // (f_big.size // 1 + 4) * 2))[:6]
        y = h - pad - int(h * 0.36) + 16 + f_small.size + 18
        for line in lines:
            d.text((pad + 20, y), line, fill=(20, 20, 20), font=f_big)
            y += f_big.size + 8
        buf = io.BytesIO()
        img.save(buf, format="PNG", optimize=True)
        return buf.getvalue()


class OpenAIImages:
    name = "openai-gpt-image-1"

    def __init__(self, key: str):
        self.http = httpx.Client(base_url="https://api.openai.com/v1", headers={"Authorization": f"Bearer {key}"}, timeout=180)

    def generate(self, prompt: str, size: str = "square", seed: int = 0) -> bytes:
        api_size = {"square": "1024x1024", "portrait": "1024x1536", "landscape": "1536x1024", "hero": "1536x1024"}[size]
        r = self.http.post("/images/generations", json={"model": "gpt-image-1", "prompt": prompt, "size": api_size, "n": 1})
        r.raise_for_status()
        raw = base64.b64decode(r.json()["data"][0]["b64_json"])
        # normalize to our canonical aspect so ad specs are identical across providers
        img = Image.open(io.BytesIO(raw)).convert("RGB")
        w, h = SIZES[size]
        img = _cover(img, w, h)
        buf = io.BytesIO()
        img.save(buf, format="PNG", optimize=True)
        return buf.getvalue()


def _cover(img: Image.Image, w: int, h: int) -> Image.Image:
    scale = max(w / img.width, h / img.height)
    img = img.resize((int(img.width * scale + 0.5), int(img.height * scale + 0.5)))
    left, top = (img.width - w) // 2, (img.height - h) // 2
    return img.crop((left, top, left + w, top + h))


def make_images(provider: str, key: str | None):
    if provider == "openai" and key:
        return OpenAIImages(key)
    return MockImages()
