# TCF AI Tutor → LLM Inference Gateway + ML Pipeline 升级计划

## 给 Claude Code 的 Prompt

> 把以下内容作为 Claude Code 的 project context 或直接在对话开头贴给它。

---

### 项目背景和目标

我有一个现有的 AI Tutor 项目（TCF AI Tutor），目前是用 FastAPI + LLM API 调用做的学习助手。我现在要把它**升级改造成一个 AI Infra / Model Serving / MLOps 方向的showcase项目**，AI Tutor 的对话功能只是上层的一个 workload，**简历重点全部在下面的基础设施层**。

现有 repo: https://github.com/YaoyiW27/tcf-ai-tutor

### 改造目标架构

改造后的项目应该包含以下层级：

```
┌─────────────────────────────────────┐
│  Application Layer (AI Tutor)       │  ← 这层只是 demo workload，不是重点
│  FastAPI + conversation UI          │
├─────────────────────────────────────┤
│  Inference Gateway                  │  ← 重点 1
│  Request routing, rate limiting,    │
│  token counting, cost tracking,     │
│  request queuing                    │
├─────────────────────────────────────┤
│  Model Serving (vLLM / SGLang)      │  ← 重点 2
│  Self-hosted open-source LLM        │
│  (Mistral 7B or similar)            │
│  Continuous batching, KV cache,     │
│  quantization (AWQ/GPTQ)            │
├─────────────────────────────────────┤
│  Observability                      │  ← 重点 3
│  Prometheus + Grafana               │
│  Metrics: QPS, P50/P95/P99 latency, │
│  TTFT, GPU util%, VRAM, KV cache    │
│  hit rate, tokens/sec, queue depth  │
├─────────────────────────────────────┤
│  Orchestration & Deployment         │  ← 重点 4
│  Kubernetes (local k3s or kind)     │
│  GPU-aware HPA autoscaling          │
│  Helm charts or Kustomize           │
├─────────────────────────────────────┤
│  ML Pipeline (Argo Workflows)       │  ← 重点 5
│  Model eval benchmark workflow      │
│  Auto rolling update on pass        │
│  Model registry (simple version)    │
└─────────────────────────────────────┘
```

### 分阶段实施计划

#### Phase 1: Self-Host LLM with vLLM（最高优先级）

目标：替换掉第三方 API 调用，用 vLLM self-host 一个开源模型。

具体任务：
1. 选一个开源模型（建议 Mistral-7B-Instruct-v0.3 或 Qwen2.5-7B-Instruct），用 vLLM 起 OpenAI-compatible API server
2. 修改现有 FastAPI 代码，把 LLM 调用从 Anthropic/OpenAI SDK 换成指向本地 vLLM 的 OpenAI-compatible client
3. 保留原有 API 作为 fallback（环境变量切换 `INFERENCE_BACKEND=vllm|api`）
4. 做一个简单的 benchmark 脚本：固定 prompt 集 → 测量 TTFT、total latency、tokens/sec
5. 测试至少两种量化配置（FP16 vs AWQ-4bit），记录性能差异

交付物：
- vLLM serving 可以跑起来并响应请求
- benchmark 脚本和结果数据（CSV 或 JSON）
- README 里写清楚怎么启动和复现 benchmark

#### Phase 2: Inference Gateway Layer

目标：在 vLLM 和应用层之间加一个 gateway，体现"系统设计"能力。

具体任务：
1. 在 FastAPI 里加一个 inference gateway 模块（或独立服务），职责包括：
   - Request validation 和 token counting（用 tiktoken 估算）
   - Rate limiting（per-user token bucket）
   - Request queuing（当 vLLM 并发满时排队）
   - Cost tracking（per-request 记录 input/output tokens、latency、model used）
   - Streaming 支持（SSE）
2. 所有 metrics 暴露为 Prometheus 格式 (`/metrics` endpoint)
3. 支持多 model backend 路由（虽然可能只有一个 vLLM 实例，但架构上要支持切换）

交付物：
- Gateway 服务代码
- Prometheus metrics endpoint
- 简单的 cost/usage tracking dashboard 数据

#### Phase 3: Kubernetes Deployment + Observability

目标：把整个系统容器化部署到 K8s，加完整的 monitoring。

具体任务：
1. Dockerfiles：FastAPI app、vLLM server（或用官方镜像）、gateway
2. K8s manifests（Helm chart 或 Kustomize）：
   - vLLM Deployment with GPU resource requests
   - FastAPI Deployment
   - Prometheus + Grafana（用 kube-prometheus-stack helm chart）
   - ConfigMap for model config、环境变量
3. GPU-aware HPA：基于自定义 Prometheus metric（如 `vllm:gpu_utilization` 或 `vllm:queue_depth`）做 autoscaling
4. Grafana dashboard 包含：
   - Inference performance panel: QPS, P50/P95/P99 latency, TTFT
   - Resource panel: GPU utilization %, VRAM usage, KV cache utilization
   - Business panel: tokens served, cost per request, error rate
5. Alerting rules: GPU OOM risk, latency spike, error rate threshold

交付物：
- 完整的 K8s manifests
- Grafana dashboard JSON export
- 部署文档（README）

#### Phase 4: ML Pipeline with Argo Workflows

目标：自动化 model evaluation 和 deployment。

具体任务：
1. 安装 Argo Workflows 到 K8s cluster
2. 写一个 workflow 包含以下 steps：
   - Pull model weights（从 HuggingFace 或 S3）
   - Run evaluation benchmark（一组标准问题 + 期望输出，计算 BLEU/ROUGE 或自定义 accuracy metric）
   - Compare against current production model's baseline metrics
   - If pass → trigger rolling update（更新 vLLM deployment 的 model path）
   - If fail → notify（Slack webhook 或简单的日志告警）
3. 用 CronWorkflow 定期检查是否有新模型版本
4. 简单的 model registry：一个 JSON/SQLite 记录 model version、eval scores、deployment timestamp

交付物：
- Argo Workflow YAML
- Evaluation benchmark 脚本
- Model registry 实现

### 关键原则

1. **每一步都要产出可度量的数据**：不是"我部署了vLLM"，而是"FP16 QPS=X, AWQ-4bit QPS=Y, latency差异Z%"
2. **先跑通再优化**：Phase 1 能工作就推进 Phase 2，不要在某一步上过度打磨
3. **README 是简历素材的来源**：每个 phase 完成后更新 README，写清楚架构图、benchmark 数据、设计决策和为什么这么选
4. **代码质量要过关**：有 type hints、有 docstrings、有基本测试。这个 repo 会被招聘官看

### 技术栈总结

- Serving: vLLM (or SGLang)
- Model: Mistral-7B-Instruct (or Qwen2.5-7B-Instruct)
- Backend: FastAPI + Python 3.12
- Container: Docker
- Orchestration: Kubernetes (k3s/kind for local dev)
- Observability: Prometheus + Grafana + OpenTelemetry
- Pipeline: Argo Workflows
- Quantization: AWQ / GPTQ (via vLLM built-in support)
- CI/CD: GitHub Actions

### 现有代码需要保留的

- FastAPI 的基本结构和路由
- Tutor 的对话逻辑（作为 demo workload）
- 任何已有的测试

### 现有代码需要改的

- LLM 调用层：从直接调 API 改成通过 inference gateway 调 vLLM
- 配置管理：加环境变量控制 inference backend
- 项目结构：可能需要拆分成 monorepo（`/app`, `/gateway`, `/serving`, `/infra`, `/benchmarks`, `/pipeline`）

---

## 给 Claude Code 的启动 Prompt

```
我要把我的 TCF AI Tutor 项目升级成一个 AI Infra / Model Serving 方向的 showcase 项目。
请先阅读我的升级计划文档（tcf-ai-tutor-upgrade-plan.md），然后：

1. 先看一下现有代码结构，理解当前 LLM 调用是怎么做的
2. 从 Phase 1 开始：帮我设置 vLLM serving，修改代码让 LLM 调用指向本地 vLLM server
3. 每完成一个 phase 之前，先跟我确认设计方案再动手写代码

注意：
- 我的目标不是做一个更好的 AI tutor 产品，而是展示 AI infra 能力
- 每一步都要产出可度量的 benchmark 数据
- 代码要有 type hints、docstrings、基本测试
- 要同时更新 README
```
