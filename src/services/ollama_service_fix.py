"""
Fix for the "לא מסווג" (not classified) issue in Ollama service.

PROBLEM:
The LLM (DictaLM) sometimes returns malformed JSON where the summary text
becomes a JSON key instead of a value, causing classification to fail.

SOLUTION:
1. Add fallback JSON extraction using regex patterns
2. Add keyword-based classification fallback
3. Extract meaningful content even from malformed responses
"""

import re
import json
import logging
from typing import Dict, Any, Optional, List, Tuple

logger = logging.getLogger(__name__)

# Hebrew keyword-based classification mapping
KEYWORD_CLASSIFICATIONS = {
    "תמיכה טכנית": [
        "תמיכה טכנית", "תקלה", "לא עובד", "בעיה", "תיקון",
        "הגדרות", "VoLTE", "וולטה", "4G", "5G", "אינטרנט",
        "רשת", "חיבור", "סיסמה", "אפליקציה", "עדכון"
    ],
    "מכשירים": [
        "מכשיר", "טלפון", "סמארטפון", "אייפון", "סמסונג",
        "וואווי", "Huawei", "IMEI", "דגם", "מסך", "סוללה",
        "מטען", "אוזניות", "מגן"
    ],
    "חשבונות וחיובים": [
        "חשבון", "חיוב", "תשלום", "חשבונית", "יתרה",
        "חוב", "זיכוי", "החזר", "כסף", "שקל"
    ],
    "חבילות ותוכניות": [
        "חבילה", "תוכנית", "מסלול", "גלישה", "דקות",
        "SMS", "הודעות", "גיגה", "MB", "GB", "אנלימיטד"
    ],
    "ניוד": [
        "ניוד", "מעבר", "לעבור", "חברה אחרת", "מספר",
        "להעביר", "פורט"
    ],
    "שירות לקוחות": [
        "שירות", "נציג", "תלונה", "מנהל", "פנייה",
        "בקשה", "עזרה"
    ],
}


def extract_json_with_fallback(raw_response: str) -> Tuple[Optional[Dict], str]:
    """
    Extract JSON from response with multiple fallback strategies.

    Returns:
        Tuple of (parsed_json or None, extraction_method used)
    """
    # Strategy 1: Direct JSON parsing
    try:
        data = json.loads(raw_response)
        if isinstance(data, dict) and "summary" in data:
            return data, "direct_parse"
    except json.JSONDecodeError:
        pass

    # Strategy 2: Extract JSON object using regex
    json_patterns = [
        r'\{[^{}]*"summary"\s*:\s*"[^"]*"[^{}]*\}',  # Simple object with summary
        r'\{(?:[^{}]|\{[^{}]*\})*"summary"(?:[^{}]|\{[^{}]*\})*\}',  # Nested with summary
    ]

    for pattern in json_patterns:
        match = re.search(pattern, raw_response, re.DOTALL)
        if match:
            try:
                data = json.loads(match.group())
                if "summary" in data:
                    return data, "regex_extract"
            except json.JSONDecodeError:
                continue

    # Strategy 3: Look for individual fields using regex
    extracted = {}

    # Extract summary
    summary_match = re.search(r'"summary"\s*:\s*"([^"]*)"', raw_response)
    if summary_match:
        extracted["summary"] = summary_match.group(1)

    # Extract classifications array
    class_match = re.search(r'"classifications"\s*:\s*\[([^\]]*)\]', raw_response)
    if class_match:
        try:
            classifications = json.loads(f"[{class_match.group(1)}]")
            extracted["classifications"] = classifications
        except:
            pass

    # Extract main_category
    main_cat_match = re.search(r'"main_category"\s*:\s*"([^"]*)"', raw_response)
    if main_cat_match:
        extracted["main_category"] = main_cat_match.group(1)

    # Extract sentiment
    sentiment_match = re.search(r'"sentiment"\s*:\s*(\d+)', raw_response)
    if sentiment_match:
        extracted["sentiment"] = int(sentiment_match.group(1))

    if extracted.get("summary"):
        return extracted, "field_extraction"

    # Strategy 4: Handle malformed response where text is a key
    # This is the specific bug pattern: {"Some long text...": {"name": "..."}}
    try:
        data = json.loads(raw_response)
        if isinstance(data, dict):
            for key, value in data.items():
                # If key is very long (>50 chars), it's likely the summary text
                if len(key) > 50:
                    logger.warning(f"Detected malformed JSON with summary as key")
                    extracted["summary"] = key
                    if isinstance(value, dict) and "name" in value:
                        extracted["main_category"] = value.get("name", "")
                    return extracted, "key_as_summary"
    except:
        pass

    return None, "failed"


def classify_by_keywords(transcript: str) -> Tuple[str, List[str]]:
    """
    Fallback classification using keyword matching.

    Returns:
        Tuple of (main_category, list of matching categories)
    """
    transcript_lower = transcript.lower()
    matches = []
    scores = {}

    for category, keywords in KEYWORD_CLASSIFICATIONS.items():
        score = 0
        for keyword in keywords:
            if keyword.lower() in transcript_lower:
                score += 1
        if score > 0:
            scores[category] = score
            matches.append(category)

    if scores:
        # Return category with highest score
        main_category = max(scores, key=scores.get)
        return main_category, matches

    return "", []


def parse_ollama_response_fixed(
    raw_response: str,
    transcript: str = "",
    call_id: str = ""
) -> Dict[str, Any]:
    """
    Fixed version of parse_ollama_response that handles malformed JSON.

    Key improvements:
    1. Multiple JSON extraction strategies
    2. Keyword-based fallback classification
    3. Never returns "לא מסווג" if we can extract any useful info
    """
    result = {
        "success": False,
        "error": None,
        "summary": "",
        "callId": call_id,
        "metadata": {}
    }

    logger.info(f"Raw Ollama response length: {len(raw_response)}")

    # Try to extract JSON with fallback strategies
    parsed_data, method = extract_json_with_fallback(raw_response)

    if parsed_data:
        logger.info(f"JSON extracted successfully using: {method}")

        result["success"] = True
        result["summary"] = parsed_data.get("summary", "")
        result["metadata"] = {
            "classifications": parsed_data.get("classifications", []),
            "main_category": parsed_data.get("main_category", ""),
            "secondary_category": parsed_data.get("secondary_category", ""),
            "sentiment": parsed_data.get("sentiment", 3),
            "entities": parsed_data.get("entities", {}),
            "action_items": parsed_data.get("action_items", []),
            "customer_satisfaction": parsed_data.get("customer_satisfaction", 3),
            "unresolved_issues": parsed_data.get("unresolved_issues", ""),
            "threats": parsed_data.get("threats", ""),
        }

        # If we extracted but missing classification, try keyword fallback
        if not result["metadata"]["main_category"] or result["metadata"]["main_category"] == "לא מסווג":
            if transcript:
                main_cat, classifications = classify_by_keywords(transcript)
                if main_cat:
                    logger.info(f"Using keyword classification fallback: {main_cat}")
                    result["metadata"]["main_category"] = main_cat
                    result["metadata"]["classifications"] = classifications

        return result

    # All JSON extraction failed - use pure keyword classification
    logger.warning(f"All JSON extraction methods failed for call {call_id}")

    if transcript:
        main_cat, classifications = classify_by_keywords(transcript)
        if main_cat:
            logger.info(f"Using pure keyword classification: {main_cat}")
            result["success"] = True
            result["summary"] = "סיכום לא זמין - סיווג לפי מילות מפתח"  # Summary unavailable - classified by keywords
            result["metadata"] = {
                "classifications": classifications,
                "main_category": main_cat,
                "secondary_category": classifications[1] if len(classifications) > 1 else "",
                "sentiment": 3,
                "entities": {},
                "action_items": [],
                "customer_satisfaction": 3,
                "unresolved_issues": "",
                "threats": "",
                "classification_method": "keyword_fallback"
            }
            return result

    # Last resort - still don't return "לא מסווג", return with error for retry
    result["error"] = "json_extraction_failed"
    result["metadata"] = {
        "classifications": [],
        "main_category": "",  # Empty, not "לא מסווג" - let orchestrator decide
        "secondary_category": "",
        "sentiment": 3,
        "entities": {},
        "action_items": [],
        "customer_satisfaction": 3,
        "unresolved_issues": "",
        "threats": "",
    }

    return result


# Example usage demonstrating the fix
if __name__ == "__main__":
    # The malformed response from the logs
    malformed_response = '''{
"Thank you for considering a switch to our network, and I'm glad to assist you in exploring the benefits of joining us. As discussed, we offer an exceptional service that includes a 4G LTE network with 900MB data per month, unlimited calls, and texts. We also provide additional features such as a personalized control center for your account, mobile protection plans, and more. Our customer support team is always available to assist you with any inquiries or issues that may arise. If you have further questions or require more information about our services, please don't hesitate to reach out to us.":
{
"name": "Switching to a Better Network"
}}'''

    # The transcript from the call
    transcript = """שלום איך אני יכולה לעזור
לתמיכה טכנית
כן איך אני יכולה לעזור ראובן
שלום אני רציתי פשוט להתייעץ
אנחנו רחש שכמה טלפונים והחברה אצלנו שהם של חברה שנקראת אם סיני מכירה
עכשיו אני רוצה לדעת איך אני יכול לדעת אם זה מוחק לי אחרי הראשון לראשון בוידאו L D
..."""

    result = parse_ollama_response_fixed(
        raw_response=malformed_response,
        transcript=transcript,
        call_id="3692397191945650236"
    )

    print(f"Success: {result['success']}")
    print(f"Main Category: {result['metadata']['main_category']}")
    print(f"Classifications: {result['metadata']['classifications']}")
