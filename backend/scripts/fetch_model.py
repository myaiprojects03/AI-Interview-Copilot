"""Download the embedding model into backend/models so it ships inside the deployment.

Vercel runs this as the Build Command (see vercel.json). At run time the app finds
backend/models and loads the model offline, because the file system there is read-only.
The files are saved as plain files (no cache links), so nothing is bundled twice.

    python -m scripts.fetch_model
"""

import asyncio
import sys
import time

from app.core.config import BACKEND_DIR, get_settings
from app.providers.embeddings.local import LocalEmbeddings, download_model


def main() -> int:
    settings = get_settings()
    target = BACKEND_DIR / "models"
    start = time.perf_counter()
    folder = download_model(settings.embedding_model, target)
    vector = asyncio.run(LocalEmbeddings(settings.embedding_model, cache_dir=target)
                         .embed_query("check"))
    size_mb = sum(f.stat().st_size for f in folder.rglob("*") if f.is_file()) / 1e6
    print(
        f"Model {settings.embedding_model} ready in {folder} "
        f"({size_mb:.0f} MB, {len(vector)} dimensions, {time.perf_counter() - start:.1f} s)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
