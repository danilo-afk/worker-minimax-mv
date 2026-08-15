ARG BASE_IMAGE=nvidia/cuda:12.6.3-cudnn-runtime-ubuntu24.04

FROM ${BASE_IMAGE}

ARG COMFYUI_COMMIT=7fe8a6138504f90ff7be82f3babf416da32876b1
ARG SONG_PLANNER_COMMIT=e46b13b722e460f6e393b917a5a9c289ee51e0c1

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PIP_NO_INPUT=1 \
    PATH=/opt/venv/bin:$PATH \
    HF_HUB_ENABLE_HF_TRANSFER=1 \
    COMFY_HOST=127.0.0.1:8188

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    ffmpeg \
    git \
    libgl1 \
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    libxrender1 \
    python3.12 \
    python3.12-dev \
    python3.12-venv \
    wget \
    && rm -rf /var/lib/apt/lists/* \
    && python3.12 -m venv /opt/venv

RUN pip install --no-cache-dir --upgrade pip setuptools wheel \
    && pip install --no-cache-dir \
      torch==2.11.0 torchvision==0.26.0 torchaudio==2.11.0 \
      --index-url https://download.pytorch.org/whl/cu126

RUN git clone https://github.com/Comfy-Org/ComfyUI.git /comfyui \
    && cd /comfyui \
    && git checkout "${COMFYUI_COMMIT}" \
    && pip install --no-cache-dir -r requirements.txt

RUN cd /comfyui/custom_nodes \
    && git clone https://github.com/danilo-afk/ComfyUI-MiniMax-M3-SongPlanner.git minimax-m3-planner \
    && cd minimax-m3-planner \
    && git checkout "${SONG_PLANNER_COMMIT}"

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
RUN python -c "from transformers import CLIPTokenizer; import huggingface_hub"

COPY handler.py ./
COPY src ./src
COPY workflows ./workflows
COPY test_input.json ./

RUN cp src/extra_model_paths.yaml /comfyui/extra_model_paths.yaml \
    && cp -R src/custom_nodes/worker_music3_output /comfyui/custom_nodes/worker_music3_output \
    && chmod +x src/start.sh

CMD ["/app/src/start.sh"]
