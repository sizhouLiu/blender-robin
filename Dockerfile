FROM nvidia/cuda:12.2.0-runtime-ubuntu22.04

ARG BLENDER_VERSION=4.2.0
ARG PYTHON_VERSION=3.11

ENV DEBIAN_FRONTEND=noninteractive
ENV BLENDER_PATH=/opt/blender/blender
ENV NVIDIA_DRIVER_CAPABILITIES=all
ENV NVIDIA_VISIBLE_DEVICES=all

# System dependencies (including EGL for GPU headless rendering)
RUN apt-get update && apt-get install -y --no-install-recommends \
    python${PYTHON_VERSION} \
    python${PYTHON_VERSION}-venv \
    python3-pip \
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
RUN wget -q "https://download.blender.org/release/Blender4.2/blender-${BLENDER_VERSION}-linux-x64.tar.xz" \
    && tar -xf "blender-${BLENDER_VERSION}-linux-x64.tar.xz" \
    && mv "blender-${BLENDER_VERSION}-linux-x64" /opt/blender \
    && rm "blender-${BLENDER_VERSION}-linux-x64.tar.xz" \
    && ln -s /opt/blender/blender /usr/local/bin/blender

# Set up Python (use system python, not Blender's bundled one)
RUN update-alternatives --install /usr/bin/python3 python3 /usr/bin/python${PYTHON_VERSION} 1 \
    && python3 -m pip install --no-cache-dir --upgrade pip setuptools

# Install robin
WORKDIR /app
COPY pyproject.toml .
COPY blender_robin/ blender_robin/
COPY robin_config.json .
COPY robin_interactive.py .

RUN pip install --no-cache-dir -e .

# Default config: point to blender in container
RUN python3 -c "import json; \
    cfg = json.load(open('robin_config.json')); \
    cfg['blender_path'] = '/opt/blender/blender'; \
    json.dump(cfg, open('robin_config.json', 'w'), indent=2)"

# Volumes for models and output
VOLUME ["/models", "/output"]

ENTRYPOINT ["robin"]
CMD ["--help"]
