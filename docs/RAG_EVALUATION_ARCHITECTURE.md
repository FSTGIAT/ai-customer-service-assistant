# RAG Evaluation Infrastructure - Architecture Document

## Executive Summary

This document outlines the infrastructure for an enhanced RAG (Retrieval-Augmented Generation) system with evaluation capabilities for the Hebrew Call Analytics platform.

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────────────────────┐
│                           AWS PLAYGROUND ENVIRONMENT                                 │
│                                                                                      │
│  ┌─────────────────────────────────────────────────────────────────────────────┐   │
│  │                    AWS MANAGED OPENSEARCH SERVICE                            │   │
│  │                                                                              │   │
│  │  Domain: call-analytics-playground                                           │   │
│  │  Version: OpenSearch 2.11                                                    │   │
│  │  Instance: r5.large.search (2 vCPU, 16GB RAM)                               │   │
│  │                                                                              │   │
│  │  Features:                                                                   │   │
│  │  ├── Hybrid Search (BM25 + kNN)                                             │   │
│  │  ├── 99.9% SLA                                                              │   │
│  │  ├── Automated backups                                                       │   │
│  │  ├── Multi-AZ deployment                                                     │   │
│  │  └── Fine-grained access control                                            │   │
│  │                                                                              │   │
│  │  Indexes:                                                                    │   │
│  │  ├── call-summaries (summaries + 768-dim embeddings)                        │   │
│  │  ├── call-keypoints (individual keypoints + embeddings)                     │   │
│  │  └── rag-evaluations (query metrics + feedback)                             │   │
│  └─────────────────────────────────────────────────────────────────────────────┘   │
│                                                                                      │
│  ┌─────────────────────────────────────────────────────────────────────────────┐   │
│  │                    ECS CLUSTER (EC2 + GPU)                                   │   │
│  │                                                                              │   │
│  │  Instance: g4dn.xlarge (4 vCPU, 16GB RAM, 1x NVIDIA T4 16GB VRAM)          │   │
│  │                                                                              │   │
│  │  Services:                                                                   │   │
│  │  ├── ml-service (DictaLM + AlephBERT) - ~10GB VRAM                         │   │
│  │  ├── evaluation-service (query analysis + metrics) - ~2GB VRAM             │   │
│  │  └── api-service (Node.js, no GPU)                                          │   │
│  │                                                                              │   │
│  │  GPU Sharing: NVIDIA MPS (Multi-Process Service)                            │   │
│  └─────────────────────────────────────────────────────────────────────────────┘   │
│                                                                                      │
│  ┌─────────────────────────────────────────────────────────────────────────────┐   │
│  │                    SQS QUEUES                                                │   │
│  │                                                                              │   │
│  │  ├── summary-pipe-queue (existing)                                          │   │
│  │  ├── embedding-pipe-queue (existing)                                        │   │
│  │  ├── keypoint-pipe-queue (NEW)                                              │   │
│  │  ├── evaluation-pipe-queue (NEW)                                            │   │
│  │  └── feedback-pipe-queue (NEW)                                              │   │
│  └─────────────────────────────────────────────────────────────────────────────┘   │
│                                                                                      │
│  ┌─────────────────────────────────────────────────────────────────────────────┐   │
│  │                    EVALUATION FRAMEWORK                                      │   │
│  │                                                                              │   │
│  │  Metrics:                                                                    │   │
│  │  ├── Precision@K (K=5, 10, 20)                                              │   │
│  │  ├── Recall@K (K=5, 10, 20, 100)                                            │   │
│  │  ├── MRR (Mean Reciprocal Rank)                                             │   │
│  │  ├── NDCG (Normalized Discounted Cumulative Gain)                           │   │
│  │  └── User feedback rate (positive/negative)                                 │   │
│  │                                                                              │   │
│  │  A/B Testing Strategies:                                                     │   │
│  │  ├── Strategy A: Vector-only (kNN)                                          │   │
│  │  ├── Strategy B: BM25-only (keyword)                                        │   │
│  │  ├── Strategy C: Hybrid 70/30 (kNN/BM25)                                    │   │
│  │  └── Strategy D: Hybrid 50/50 (kNN/BM25)                                    │   │
│  └─────────────────────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────────────────┘
```

## Data Flow

```
┌──────────────┐     ┌──────────────┐     ┌──────────────────────────────────────┐
│  On-Premise  │     │  SQS Queue   │     │         ML Service (ECS)             │
│  Oracle CDC  │────▶│  summary-    │────▶│  ┌────────────┐  ┌────────────────┐ │
│              │     │  pipe-queue  │     │  │  DictaLM   │  │  AlephBERT     │ │
└──────────────┘     └──────────────┘     │  │  Summary   │  │  Embeddings    │ │
                                          │  └─────┬──────┘  └───────┬────────┘ │
                                          └────────┼─────────────────┼──────────┘
                                                   │                 │
                     ┌─────────────────────────────┼─────────────────┼──────────┐
                     │                             ▼                 ▼          │
                     │  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐   │
                     │  │ summary-pipe │  │ embedding-   │  │ keypoint-    │   │
                     │  │ -complete    │  │ pipe-queue   │  │ pipe-queue   │   │
                     │  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘   │
                     │         │                 │                 │           │
                     │         ▼                 ▼                 ▼           │
                     │  ┌─────────────────────────────────────────────────┐    │
                     │  │           AWS MANAGED OPENSEARCH                │    │
                     │  │                                                 │    │
                     │  │  call-summaries    call-keypoints    rag-evals │    │
                     │  └─────────────────────────────────────────────────┘    │
                     │                          │                              │
                     │                          ▼                              │
                     │  ┌─────────────────────────────────────────────────┐    │
                     │  │           EVALUATION SERVICE                    │    │
                     │  │                                                 │    │
                     │  │  Query Analysis → Metrics → CloudWatch          │    │
                     │  └─────────────────────────────────────────────────┘    │
                     └─────────────────────────────────────────────────────────┘
```

## Hybrid Search Implementation

```json
{
  "query": {
    "hybrid": {
      "queries": [
        {
          "match": {
            "keypoint_text": {
              "query": "בעיות 5G",
              "boost": 0.3
            }
          }
        },
        {
          "knn": {
            "keypoint_embedding": {
              "vector": [0.123, -0.456, ...],
              "k": 100,
              "boost": 0.7
            }
          }
        }
      ]
    }
  },
  "search_pipeline": "hybrid-search-pipeline"
}
```

## Recall/Precision Evaluation

### Ground Truth Dataset Structure

```json
{
  "query_id": "q001",
  "query_text": "כמה לקוחות דיברו על בעיות 5G?",
  "query_type": "count",
  "expected_results": ["call_123", "call_456", "call_789"],
  "expected_count": 52,
  "relevant_topics": ["5G", "רשת דור 5", "קליטה"],
  "created_at": "2024-01-15T10:00:00Z",
  "labeled_by": "human_reviewer"
}
```

### Metrics Calculation

| Metric | Formula | Use Case |
|--------|---------|----------|
| Precision@K | (Relevant in top K) / K | Quality of top results |
| Recall@K | (Relevant in top K) / Total relevant | Coverage of relevant docs |
| MRR | 1 / rank of first relevant | Finding relevant result quickly |
| NDCG | DCG / IDCG | Ranking quality with graded relevance |

## Cost Estimation (Playground)

| Resource | Type | Monthly Cost |
|----------|------|--------------|
| OpenSearch | r5.large.search | ~$180 |
| ECS (g4dn.xlarge) | GPU instance | ~$380 |
| SQS | Standard queues | ~$5 |
| CloudWatch | Logs + Metrics | ~$20 |
| ECR | Image storage | ~$5 |
| NAT Gateway | Data transfer | ~$50 |
| **Total** | | **~$640/month** |

## Implementation Phases

### Phase 1: Infrastructure (Week 1)
- [ ] Terraform modules for OpenSearch managed
- [ ] Terraform modules for ECS GPU cluster
- [ ] Terraform modules for SQS queues
- [ ] Networking (VPC, subnets, security groups)

### Phase 2: Services (Week 2)
- [ ] Evaluation service Docker + code
- [ ] OpenSearch index templates
- [ ] Hybrid search pipeline configuration

### Phase 3: Evaluation Framework (Week 3)
- [ ] Ground truth dataset creation
- [ ] Recall/Precision calculation logic
- [ ] CloudWatch dashboards
- [ ] A/B testing framework

### Phase 4: Integration (Week 4)
- [ ] Connect to existing ML service
- [ ] End-to-end testing
- [ ] Documentation

## Security Considerations

- OpenSearch in private subnet (no public access)
- Fine-grained access control with IAM
- Encryption at rest (KMS)
- Encryption in transit (TLS)
- VPC endpoints for AWS services
