ARG BASE_IMAGE=nvidia/cuda:12.6.3-cudnn-runtime-ubuntu24.04
FROM ${BASE_IMAGE}

ARG COMFYUI_COMMIT=7fe8a6138504f90ff7be82f3babf416da32876b1

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PIP_NO_INPUT=1 \
    PATH=/opt/venv/bin:$PATH \
    HF_HUB_ENABLE_HF_TRANSFER=1 \
    COMFY_HOST=127.0.0.1:8188

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential ffmpeg git libgl1 libglib2.0-0 libsm6 libxext6 libxrender1 \
    python3.12 python3.12-dev python3.12-venv wget \
    && rm -rf /var/lib/apt/lists/* \
    && python3.12 -m venv /opt/venv

RUN pip install --no-cache-dir --upgrade pip setuptools wheel \
    && pip install --no-cache-dir torch==2.11.0 torchvision==0.26.0 torchaudio==2.11.0 \
      --index-url https://download.pytorch.org/whl/cu126

RUN git clone https://github.com/Comfy-Org/ComfyUI.git /comfyui \
    && cd /comfyui \
    && git checkout "${COMFYUI_COMMIT}" \
    && grep -q 'class MiniMaxH3ReferenceToVideo' comfy_extras/nodes_minimax_h3.py \
    && grep -q 'class MiniMaxH3SigmaShift' comfy_extras/nodes_minimax_h3.py \
    && pip install --no-cache-dir -r requirements.txt

WORKDIR /app
COPY workers/h3/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt \
    && python -c "from transformers import CLIPTokenizer; import huggingface_hub"
COPY workers/h3/handler.py ./
COPY workers/h3/src ./src
RUN cp src/extra_model_paths.yaml /comfyui/extra_model_paths.yaml \
    && chmod +x src/start.sh
CMD ["/app/src/start.sh"]
