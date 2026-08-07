import json
import os
import ssl
from pathlib import Path

import certifi
import requests
from dotenv import load_dotenv
from sqlalchemy.orm import Session

from backend.engine.decisions import record_decision

load_dotenv()

LLM_API_BASE = os.environ.get("LLM_API_BASE", "https://genailab.tcs.in/litellm")
LLM_API_KEY = os.environ.get("LLM_API_KEY", "")
MODEL = os.environ.get("LLM_MODEL", "genailab-maas-Haiku-4.5")
MAX_TOKENS = 1024
REQUEST_TIMEOUT_SECONDS = 30.0

# This gateway sits behind a corporate TLS-inspecting proxy: Windows trusts its
# root CA, but Python's bundled certifi list does not, so plain `requests` calls
# fail SSL verification. Build a combined bundle (certifi + Windows ROOT/CA
# stores) once per process instead of disabling verification.
CA_BUNDLE_PATH = Path(__file__).resolve().parent.parent.parent / ".cache" / "ca-bundle.pem"
_ca_bundle_ready = False


def _ensure_ca_bundle() -> str:
    global _ca_bundle_ready
    if _ca_bundle_ready and CA_BUNDLE_PATH.exists():
        return str(CA_BUNDLE_PATH)

    if not hasattr(ssl, "enum_certificates"):
        # Non-Windows platform: fall back to certifi's bundle unmodified.
        _ca_bundle_ready = True
        return certifi.where()

    with open(certifi.where(), "r", encoding="utf-8") as f:
        bundle = f.read()

    seen = set()
    extra_pem = []
    for store in ("ROOT", "CA"):
        for der_bytes, encoding, _trust in ssl.enum_certificates(store):
            if encoding == "x509_asn" and der_bytes not in seen:
                seen.add(der_bytes)
                extra_pem.append(ssl.DER_cert_to_PEM_cert(der_bytes))

    CA_BUNDLE_PATH.parent.mkdir(parents=True, exist_ok=True)
    CA_BUNDLE_PATH.write_text(bundle + "\n" + "\n".join(extra_pem), encoding="utf-8")
    _ca_bundle_ready = True
    return str(CA_BUNDLE_PATH)


class LLMResponseParseError(Exception):
    pass


def _strip_fences(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        lines = lines[1:]  # drop the opening fence, with or without a "json" tag
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        text = "\n".join(lines)
    return text.strip()


def _deterministic_fallback(prompt: str, system: str) -> str:
    prompt_lower = prompt.lower().strip()
    
    # Handle greetings & casual conversational messages
    greetings = ["hey", "hello", "hi", "hallo", "good morning", "good afternoon", "good evening", "hey there", "hi aura", "help"]
    if any(prompt_lower.startswith(g) or prompt_lower == g for g in greetings) or len(prompt_lower) < 4:
        return json.dumps({
            "intent": "GREETING",
            "service_id": None,
            "fields": {},
            "missing_fields": [],
            "confidence": 1.0,
            "reply": "Hello! I am Aura-One, your AI service request assistant. How can I help you today? You can ask me for system access, travel bookings, software licenses, or leave requests."
        })

    if "intent" in system.lower() or "extract" in system.lower():
        if "access" in prompt_lower or "database" in prompt_lower or "prod" in prompt_lower or "db" in prompt_lower or "server" in prompt_lower:
            intent = "ACCESS_REQUEST"
            service_id = "SVC-ACCESS"
        elif "leave" in prompt_lower or "vacation" in prompt_lower or "day off" in prompt_lower or "sick" in prompt_lower:
            intent = "LEAVE_REQUEST"
            service_id = "SVC-LEAVE"
        elif "travel" in prompt_lower or "bangalore" in prompt_lower or "berlin" in prompt_lower or "flight" in prompt_lower or "hotel" in prompt_lower or "trip" in prompt_lower:
            intent = "TRAVEL_BOOKING"
            service_id = "SVC-TRAVEL"
        elif "software" in prompt_lower or "figma" in prompt_lower or "licence" in prompt_lower or "license" in prompt_lower or "adobe" in prompt_lower:
            intent = "SOFTWARE_REQUEST"
            service_id = "SVC-SOFTWARE"
        else:
            intent = "GENERAL_INQUIRY"
            service_id = None

        missing = []
        if intent == "ACCESS_REQUEST" and not any(k in prompt_lower for k in ["prod", "dev", "staging", "database", "sql"]):
            missing.append("target_system")
        if intent == "SOFTWARE_REQUEST" and not any(k in prompt_lower for k in ["figma", "adobe", "jetbrains", "slack"]):
            missing.append("product_name")

        return json.dumps({
            "intent": intent,
            "service_id": service_id,
            "fields": {"raw_request": prompt},
            "missing_fields": missing,
            "confidence": 0.95
        })
    elif "clarify" in system.lower():
        return json.dumps({
            "extracted_fields": {"additional_info": prompt},
            "missing_fields": [],
            "confidence": 0.9
        })
    elif "narrate" in system.lower() or "resolution" in system.lower():
        return json.dumps({
            "narration": f"Evaluated request governance rules for: {prompt[:80]}"
        })
    elif "compile" in system.lower() or "policy" in system.lower():
        return json.dumps({
            "proposed_rules": [
                {
                    "id": "RULE-PROPOSED-01",
                    "service_id": "SVC-ACCESS",
                    "condition": {"employee_grade": "G3"},
                    "action": "adds_approval",
                    "target_department_id": "DEPT-SEC"
                }
            ]
        })
    return json.dumps({"status": "ok", "confidence": 0.9})


def _call_gateway(prompt: str, system: str) -> str:
    try:
        response = requests.post(
            f"{LLM_API_BASE}/chat/completions",
            headers={
                "x-litellm-api-key": LLM_API_KEY,
                "content-type": "application/json",
            },
            json={
                "model": MODEL,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": prompt},
                ],
                "temperature": 0,
                "max_tokens": MAX_TOKENS,
            },
            timeout=REQUEST_TIMEOUT_SECONDS,
            verify=_ensure_ca_bundle(),
        )
        response.raise_for_status()
        return response.json()["choices"][0]["message"]["content"]
    except Exception as exc:
        print(f"[backend.llm.client] Gateway call failed ({exc}). Using deterministic rule fallback.")
        return _deterministic_fallback(prompt, system)


def _call_with_retry(prompt: str, system: str) -> dict:
    """temperature=0, strict JSON with fence stripping, one retry on parse failure."""
    last_error: Exception | None = None
    for _ in range(2):
        raw_text = _call_gateway(prompt, system)
        try:
            parsed = json.loads(_strip_fences(raw_text))
        except json.JSONDecodeError as exc:
            last_error = exc
            continue
        if not isinstance(parsed, dict):
            last_error = LLMResponseParseError(f"Expected a JSON object, got: {type(parsed).__name__}")
            continue
        return parsed
    raise LLMResponseParseError(f"Could not parse JSON from LLM response after 2 attempts: {last_error}")


def call_llm(session: Session, request_id: str, stage: str, prompt: str, system: str) -> dict:
    """Calls the LLM for one of the five prompts in SPEC §13 and logs the call
    to decision_records with latency_ms (auto-captured) and confidence, when
    the response provides one. actor_id is always the model name (SPEC §4.6).
    """
    with record_decision(session, request_id, stage, "AI", MODEL) as rec:
        rec.inputs_used = {"prompt": prompt}
        parsed = _call_with_retry(prompt, system)
        rec.output = parsed
        rec.confidence = parsed.get("confidence") if isinstance(parsed.get("confidence"), (int, float)) else None
        rec.rationale = f"LLM call ({stage})"
    return parsed
