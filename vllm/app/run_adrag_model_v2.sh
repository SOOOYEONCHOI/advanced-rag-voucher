#!/bin/bash
set -e

source /opt/vllm/.venv_flash/bin/activate
source /opt/vllm/app/env.sh

export CUDA_VISIBLE_DEVICES=0

export VLLM_USE_FLASHINFER_SAMPLER=0
export VLLM_MEMORY_PROFILER_ESTIMATE_CUDAGRAPHS=0
export VLLM_DISABLE_FLASHINFER=1
export PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True

mkdir -p /opt/vllm/logs

echo "Starting Qwen3.5-9B LLM server (8001)..."

vllm serve /opt/vllm/models/gen/Qwen3.5-9B \
  --served-model-name Qwen3.5-9B \
  --host 0.0.0.0 \
  --port 8001 \
  --dtype bfloat16 \
  --max-model-len 24576 \
  --max-num-seqs 16 \
  --gpu-memory-utilization 0.49 \
  --tensor-parallel-size 1 \
  --attention-backend FLASH_ATTN \
  --trust-remote-code \
  --api-key "$VLLM_API_KEY" \
  > /opt/vllm/logs/vllm_qwen35_9b.log 2>&1 &

sleep 40

echo "Starting Embedding server (8002)..."

vllm serve /opt/vllm/models/embedding/Qwen3-Embedding-4B \
  --served-model-name Qwen3-Embedding-4B \
  --runner pooling \
  --host 0.0.0.0 \
  --port 8002 \
  --dtype auto \
  --gpu-memory-utilization 0.12 \
  --max-model-len 2048 \
  --attention-backend FLASH_ATTN \
  --trust-remote-code \
  --api-key "$VLLM_API_KEY" \
  > /opt/vllm/logs/vllm_embedding_v2.log 2>&1 &

sleep 40

echo "Starting Reranker server (8003)..."

vllm serve /opt/vllm/models/reranker/bge-reranker-v2-m3 \
  --served-model-name bge-reranker-v2-m3 \
  --runner pooling \
  --host 0.0.0.0 \
  --port 8003 \
  --dtype float16 \
  --gpu-memory-utilization 0.05 \
  --attention-backend FLASH_ATTN \
  --api-key "$VLLM_API_KEY" \
  > /opt/vllm/logs/vllm_reranker.log 2>&1 &

echo "All services started."