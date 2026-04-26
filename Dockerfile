# lorscan — Docker image for self-hosting (NAS, home server, etc.)
#
# Targets x86_64 (Synology Plus models, generic Intel/AMD home servers).
# CPU-only PyTorch keeps the image ~800 MB instead of ~3 GB CUDA wheels
# we'd never use on a NAS.

FROM python:3.12-slim-bookworm

# Runtime system deps:
#   libglib2.0-0  — required by opencv-python-headless at import time
#   libheif1      — pillow-heif decodes iPhone HEIC photos through this
#   ca-certificates — TLS for the lorcana-api.com sync
RUN apt-get update && apt-get install -y --no-install-recommends \
        libglib2.0-0 \
        libheif1 \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install CPU-only PyTorch *before* the rest, so the regular `pip install .`
# resolution sees torch as already-satisfied and won't pull the default
# CUDA wheel from PyPI.
RUN pip install --no-cache-dir \
        --index-url https://download.pytorch.org/whl/cpu \
        torch

# Copy only what's needed to install the package (better layer caching).
COPY pyproject.toml README.md ./
COPY src/ ./src/

RUN pip install --no-cache-dir .

# Lorscan stores DB + embeddings + image cache here. Mount a volume to
# persist across container rebuilds.
ENV LORSCAN_DATA_DIR=/data
VOLUME ["/data"]

# Thread tuning for low-core NAS CPUs (J4025 = 2 cores / 2 threads).
# Capping these prevents PyTorch from oversubscribing and starving DSM
# of CPU during a scan, and lowers peak memory on a 2 GB box.
ENV OMP_NUM_THREADS=2
ENV MKL_NUM_THREADS=2
ENV TOKENIZERS_PARALLELISM=false

EXPOSE 8000

COPY docker/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

ENTRYPOINT ["/entrypoint.sh"]
CMD ["serve"]
