# Fix for "לא מסווג" Classification Error

## Problem Description

The system is incorrectly classifying calls as "לא מסווג" (not classified) when the LLM returns malformed JSON responses.

### Log Analysis

From the logs dated 2025-12-15:

```
Raw Ollama response: {
"Thank you for considering a switch to our network...":
{
"name": "Switching to a Better Network"
}
```

**Issues identified:**

1. **Malformed JSON Structure**: The LLM returned JSON where the summary text is a **key** instead of a **value**
2. **Wrong Language**: Response is in English despite Hebrew prompt and Hebrew call
3. **Missing Required Fields**: No `summary`, `classifications`, `main_category` fields
4. **JSON Parsing Succeeds but Field Extraction Fails**: The system correctly parses the JSON but can't find expected fields

### Error Chain

```
1. Ollama receives Hebrew transcription
        ↓
2. DictaLM generates malformed response (summary as JSON key)
        ↓
3. JSON parsing succeeds (syntactically valid)
        ↓
4. Field extraction fails ("summary" field not found)
        ↓
5. System falls back to "לא מסווג" classification
        ↓
6. Call marked as failed, queued for retry
```

## Root Causes

### 1. Prompt Engineering Issue
The LLM isn't strictly following the JSON schema. Possible causes:
- Prompt too long / complex
- DictaLM model limitations with JSON structure
- Temperature setting too high

### 2. No Robust Fallback
Current system has no fallback when JSON extraction fails - it immediately falls back to "לא מסווג".

### 3. No Keyword-Based Classification
When LLM fails, there's no secondary classification mechanism.

## Solution

### Changes to `src/services/ollama_service.py`

See `ollama_service_fix.py` for the complete implementation.

#### Key Changes:

1. **Multi-Strategy JSON Extraction** (`extract_json_with_fallback`)
   ```python
   # Strategy 1: Direct JSON parsing
   # Strategy 2: Regex extraction for JSON with summary field
   # Strategy 3: Individual field extraction using regex
   # Strategy 4: Handle malformed "key as summary" pattern
   ```

2. **Keyword-Based Fallback Classification** (`classify_by_keywords`)
   ```python
   KEYWORD_CLASSIFICATIONS = {
       "תמיכה טכנית": ["תמיכה טכנית", "תקלה", "VoLTE", "4G", ...],
       "מכשירים": ["מכשיר", "טלפון", "IMEI", ...],
       # ... more categories
   }
   ```

3. **Never Return "לא מסווג" If Content Extractable**
   - If JSON fails but we can extract the summary from malformed structure, use it
   - If all JSON fails but keywords match, use keyword classification
   - Only return empty classification (for retry) if absolutely nothing works

### Example Fix in Action

**Before (current behavior):**
```
Input: Malformed JSON with summary as key
Output: {"main_category": "לא מסווג", "success": false}
```

**After (fixed behavior):**
```
Input: Malformed JSON with summary as key
Output: {"main_category": "תמיכה טכנית", "success": true,
         "classification_method": "keyword_fallback"}
```

## Implementation Steps

### Step 1: Update `ollama_service.py`

Replace the JSON parsing logic in `parse_ollama_response()` with the fixed version from `ollama_service_fix.py`.

### Step 2: Add Keyword Classifications

Add the `KEYWORD_CLASSIFICATIONS` dictionary with Hebrew categories and keywords.

### Step 3: Update `llm_orchestrator.py`

In the orchestrator, when receiving a result with empty `main_category`:
- Don't immediately set "לא מסווג"
- Allow retry mechanisms to kick in first
- Only use "לא מסווג" as absolute last resort after all retries

### Step 4: Prompt Improvements (Optional)

Consider simplifying the JSON schema in the prompt:
```python
# Simpler JSON schema that DictaLM can follow more reliably
SIMPLE_SCHEMA = '''
תחזיר JSON בפורמט הזה בדיוק:
{
  "summary": "סיכום קצר של השיחה",
  "main_category": "הקטגוריה הראשית",
  "sentiment": מספר 1-5
}
'''
```

## Testing

Run the fix against the malformed response:

```bash
python -m src.services.ollama_service_fix
```

Expected output:
```
Success: True
Main Category: תמיכה טכנית
Classifications: ['תמיכה טכנית', 'מכשירים']
```

## Monitoring

After deploying the fix, monitor for:
1. Reduction in "לא מסווג" classifications
2. `classification_method: keyword_fallback` occurrences (indicates LLM issues)
3. Overall classification accuracy

## Files Modified

- `src/services/ollama_service.py` - JSON parsing and fallback logic
- `src/services/llm_orchestrator.py` - Error handling for empty classifications
