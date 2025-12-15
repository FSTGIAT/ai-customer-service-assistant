# ai-customer-service-assistant

AI-powered customer service call analysis and classification system.

## Overview

This system processes customer service call transcriptions using LLM (Ollama/DictaLM) to:
- Generate call summaries
- Classify calls into categories
- Extract sentiment and entities
- Identify action items and unresolved issues

## Recent Fix: Classification Error Resolution

See [CLASSIFICATION_FIX.md](./CLASSIFICATION_FIX.md) for details on fixing the "לא מסווג" (not classified) issue.

### Problem
The DictaLM model sometimes returns malformed JSON where the summary text becomes a JSON key instead of a value, causing all classification to fail.

### Solution
- Multi-strategy JSON extraction with fallback
- Keyword-based classification when LLM fails
- Never return "לא מסווג" if useful content can be extracted

## Architecture

```
┌─────────────┐     ┌──────────────────┐     ┌─────────────────┐
│  SQS Queue  │────▶│  LLM Orchestrator │────▶│  Ollama Service │
└─────────────┘     └──────────────────┘     └─────────────────┘
                            │                         │
                            ▼                         ▼
                    ┌──────────────┐          ┌──────────────┐
                    │   Fallback   │          │   DictaLM    │
                    │  Classification│        │    Model     │
                    └──────────────┘          └──────────────┘
```

## Files

- `src/services/ollama_service.py` - LLM integration and JSON parsing
- `src/services/llm_orchestrator.py` - Service coordination and fallback logic
- `src/services/ollama_service_fix.py` - Fixed JSON parsing implementation
