FROM nvidia/cuda:12.2.0-runtime-ubuntu22.04

ARG BLENDER_VERSION=5.1.2
ARG BLENDER_SERIES=5.1
ARG PYTHON_VERSION=3.11
ARG UV_VERSION=0.11.3

# uv binary (pinned to match local toolchain)
COPY --from=ghcr.io/astral-sh/uv:0.11.3 /uv /uvx /usr/local/bin/

ENV DEBIAN_FRONTEND=noninteractive
ENV BLENDER_PATH=/opt/blender/blender
ENV NVIDIA_DRIVER_CAPABILITIES=all
ENV NVIDIA_VISIBLE_DEVICES=all

# System dependencies (including EGL for GPU headless rendering)
RUN apt-get update && apt-get install -y --no-install-recommends \
    python${PYTHON_VERSION} \
    python${PYTHON_VERSION}-venv \
    libgl1-mesa-glx \
    libegl1-mesa \
    libgles2-mesa \
    libglib2.0-0 \
    libsm6 \
    libxrender1 \
    libxext6 \
    libxi6 \
    libxkbcommon0 \
    libxxf86vm1 \
    libegl1 \
    libglvnd0 \
    libglvnd-dev \
    wget \
    xz-utils \
    && rm -rf /var/lib/apt/lists/*

# Install Blender
RUN wget -q "https://download.blender.org/release/Blender${BLENDER_SERIES}/blender-${BLENDER_VERSION}-linux-x64.tar.xz" \
    && tar -xf "blender-${BLENDER_VERSION}-linux-x64.tar.xz" \
    && mv "blender-${BLENDER_VERSION}-linux-x64" /opt/blender \
    && rm "blender-${BLENDER_VERSION}-linux-x64.tar.xz" \
    && ln -s /opt/blender/blender /usr/local/bin/blender

    
# Set up Python (use system python, not Blender's bundled one)
RUN update-alternatives --install /usr/bin/python3 python3 /usr/bin/python${PYTHON_VERSION} 1

# Install robin with uv
WORKDIR /app
COPY pyproject.toml .
COPY uv.lock .
COPY blender_robin/ blender_robin/
COPY robin_config.json .
COPY robin_interactive.py .

ENV UV_SYSTEM_PYTHON=1
RUN uv pip install --system --no-cache -e .

# Default config: point to blender in container
RUN python3 -c "import json; \
    cfg = json.load(open('robin_config.json')); \
    cfg['blender_path'] = '/opt/blender/blender'; \
    json.dump(cfg, open('robin_config.json', 'w'), indent=2)"

# Volumes for models and output
VOLUME ["/models", "/output"]

ENTRYPOINT ["robin"]
CMD ["--help"]
