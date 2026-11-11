"""Download the embedding model into backend/models so it ships inside the deployment.

Vercel runs this as the Build Command (see vercel.json). At run time the app finds
backend/models and loads the model offline, because the file system there is read-only.

    python -m scripts.fetch_model
"""

import sys
import time

from app.core.config import BACKEND_DIR, get_settings


def main() -> int:
    settings = get_settings()
    target = BACKEND_DIR / "models"
    target.mkdir(exist_ok=True)
    start = time.perf_counter()
    from fastembed import TextEmbedding

    model = TextEmbedding(settings.embedding_model, cache_dir=str(target))
    dims = len(next(iter(model.query_embed(["check"]))))
    size_mb = sum(f.stat().st_size for f in target.rglob("*") if f.is_file()) / 1e6
    print(
        f"Model {settings.embedding_model} ready in {target} "
        f"({size_mb:.0f} MB, {dims} dimensions, {time.perf_counter() - start:.1f} s)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
