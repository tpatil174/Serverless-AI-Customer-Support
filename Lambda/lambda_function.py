"""
AI Project - Improved Lambda Function
Author: Tushar Patil (improved version)

Improvements over original:
  - Real AI-based intent detection (no hardcoded keywords)
  - Structured error handling throughout
  - Conversation history trimming (prevents token overflow)
  - Secrets Manager for API key (production best practice)
  - Structured CloudWatch logging (JSON)
  - Graceful DynamoDB failure handling
  - CORS headers for frontend readiness
  - TTL field on DynamoDB items (auto-cleanup old sessions)
"""

import json
import boto3
import openai
import os
import logging
import time
from datetime import datetime, timezone
from botocore.exceptions import ClientError

# ── Logging (structured JSON for CloudWatch Insights) ──────────────────────
logger = logging.getLogger()
logger.setLevel(logging.INFO)

def log(level, message, **kwargs):
    """Emit a structured JSON log entry."""
    entry = {"level": level, "message": message, "timestamp": datetime.now(timezone.utc).isoformat()}
    entry.update(kwargs)
    getattr(logger, level)(json.dumps(entry))


# ── AWS Clients ─────────────────────────────────────────────────────────────
dynamodb  = boto3.resource("dynamodb")
sns       = boto3.client("sns")
secrets   = boto3.client("secretsmanager")

TABLE_NAME    = os.environ.get("DYNAMODB_TABLE", "PunAI-Conversations")
SNS_TOPIC_ARN = os.environ.get("SNS_TOPIC_ARN", "")
SECRET_NAME   = os.environ.get("OPENAI_SECRET_NAME", "punai/openai-api-key")

# Max messages kept in DynamoDB history (prevents token overflow & keeps costs low)
MAX_HISTORY_TURNS = 10   # 10 user+assistant pairs = 20 messages


# ── Fetch OpenAI key from Secrets Manager (cached across warm invocations) ──
_openai_key_cache = None

def get_openai_key():
    global _openai_key_cache
    if _openai_key_cache:
        return _openai_key_cache
    try:
        secret = secrets.get_secret_value(SecretId=SECRET_NAME)
        data   = json.loads(secret["SecretString"])
        _openai_key_cache = data["OPENAI_API_KEY"]
        return _openai_key_cache
    except ClientError as e:
        log("error", "Failed to fetch OpenAI key from Secrets Manager", error=str(e))
        raise


# ── DynamoDB helpers ─────────────────────────────────────────────────────────
def get_history(user_id: str) -> list:
    """Load conversation history for user. Returns [] on miss or error."""
    try:
        table    = dynamodb.Table(TABLE_NAME)
        response = table.get_item(Key={"user_id": user_id})
        return response.get("Item", {}).get("history", [])
    except ClientError as e:
        log("error", "DynamoDB get_item failed", user_id=user_id, error=str(e))
        return []   # Degrade gracefully — still answer, just without history


def save_history(user_id: str, history: list):
    """
    Persist updated history. Trims to MAX_HISTORY_TURNS pairs.
    Sets a TTL of 30 days so old sessions are cleaned up automatically.
    """
    # Keep only the last N turns (each turn = 1 user + 1 assistant message)
    if len(history) > MAX_HISTORY_TURNS * 2:
        history = history[-(MAX_HISTORY_TURNS * 2):]

    ttl = int(time.time()) + (30 * 24 * 60 * 60)   # 30 days from now

    try:
        table = dynamodb.Table(TABLE_NAME)
        table.put_item(Item={
            "user_id":      user_id,
            "history":      history,
            "last_updated": datetime.now(timezone.utc).isoformat(),
            "ttl":          ttl
        })
    except ClientError as e:
        log("error", "DynamoDB put_item failed", user_id=user_id, error=str(e))
        # Non-fatal — response still goes back to user


# ── Intent detection via AI (replaces keyword matching) ─────────────────────
def detect_intent(client, message: str, history: list) -> dict:
    """
    Ask the AI to classify the intent and sentiment of the message.

    Returns a dict like:
      {
        "escalate":  true,
        "reason":    "Customer reports missing order and sounds frustrated",
        "sentiment": "negative",
        "category":  "order_issue"
      }

    Categories: order_issue | billing | technical | feedback | general | abuse
    """
    system_prompt = """You are an intent classifier for a customer support system.

Analyse the customer message and conversation context, then respond with ONLY a JSON object.
No preamble, no explanation, no markdown — raw JSON only.

JSON schema:
{
  "escalate":  <boolean — true if a human agent should be involved>,
  "reason":    <string — one sentence explaining your decision>,
  "sentiment": <"positive" | "neutral" | "negative">,
  "category":  <"order_issue" | "billing" | "technical" | "feedback" | "general" | "abuse">
}

Escalate when: customer is clearly frustrated/angry, reports a serious issue
(missing order, fraud, refund needed, safety concern, repeated same complaint),
or is being abusive. Do NOT escalate for routine questions."""

    # Give the classifier recent context (last 4 messages) so it understands tone
    context = history[-4:] if len(history) >= 4 else history
    messages = [
        {"role": "system",    "content": system_prompt},
        *context,
        {"role": "user",      "content": message}
    ]

    try:
        response = client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=messages,
            max_tokens=150,
            temperature=0     # Deterministic for classification
        )
        raw    = response.choices[0].message.content.strip()
        intent = json.loads(raw)

        # Validate required keys
        required = {"escalate", "reason", "sentiment", "category"}
        if not required.issubset(intent.keys()):
            raise ValueError(f"Missing keys in intent response: {raw}")

        return intent

    except (json.JSONDecodeError, ValueError) as e:
        log("warning", "Intent detection parse failed, defaulting to no-escalate", error=str(e))
        return {"escalate": False, "reason": "Parse error", "sentiment": "neutral", "category": "general"}
    except Exception as e:
        log("error", "Intent detection API call failed", error=str(e))
        return {"escalate": False, "reason": "API error", "sentiment": "neutral", "category": "general"}


# ── Main response generation ─────────────────────────────────────────────────
def generate_response(client, message: str, history: list, intent: dict) -> str:
    """Generate the customer-facing reply using full conversation context."""

    # Tailor system persona based on sentiment — warmer for negative sentiment
    if intent["sentiment"] == "negative":
        persona = (
            "You are a warm, empathetic customer support agent. "
            "The customer seems frustrated — acknowledge their feeling first, "
            "then help resolve the issue. Be concise (3-4 sentences max)."
        )
    else:
        persona = (
            "You are a helpful, friendly customer support agent. "
            "Answer clearly and concisely (3-4 sentences max)."
        )

    messages = [
        {"role": "system", "content": persona},
        *history,
        {"role": "user",   "content": message}
    ]

    response = client.chat.completions.create(
        model="gpt-3.5-turbo",
        messages=messages,
        max_tokens=300,
        temperature=0.7
    )
    return response.choices[0].message.content.strip()


# ── SNS escalation ───────────────────────────────────────────────────────────
def send_escalation(user_id: str, message: str, intent: dict):
    """Notify admin via SNS with structured alert."""
    if not SNS_TOPIC_ARN:
        log("warning", "SNS_TOPIC_ARN not set — escalation skipped")
        return

    alert_body = (
        f"PunAI Escalation Alert\n"
        f"{'=' * 40}\n"
        f"User ID:   {user_id}\n"
        f"Sentiment: {intent['sentiment']}\n"
        f"Category:  {intent['category']}\n"
        f"Reason:    {intent['reason']}\n"
        f"Message:   {message}\n"
        f"Time:      {datetime.now(timezone.utc).isoformat()}\n"
        f"{'=' * 40}\n"
        f"Action required: Please follow up with this customer."
    )

    try:
        sns.publish(
            TopicArn=SNS_TOPIC_ARN,
            Subject=f"[PunAI] Escalation — {intent['category'].replace('_', ' ').title()}",
            Message=alert_body
        )
        log("info", "Escalation sent via SNS", user_id=user_id, category=intent["category"])
    except ClientError as e:
        log("error", "SNS publish failed", user_id=user_id, error=str(e))


# ── Response builder ─────────────────────────────────────────────────────────
def build_response(status_code: int, body: dict) -> dict:
    """Build API Gateway-compatible HTTP response with CORS headers."""
    return {
        "statusCode": status_code,
        "headers": {
            "Content-Type":                "application/json",
            "Access-Control-Allow-Origin": "*",    # Lock down to your domain in production
            "Access-Control-Allow-Methods": "POST, OPTIONS",
            "Access-Control-Allow-Headers": "Content-Type"
        },
        "body": json.dumps(body)
    }


# ── Lambda handler ───────────────────────────────────────────────────────────
def lambda_handler(event, context):
    """
    Entry point.

    Expected request body:
      { "user_id": "customer_123", "message": "My order hasn't arrived" }

    Response body:
      {
        "reply":      "I'm sorry to hear that ...",
        "escalation": true,
        "sentiment":  "negative",
        "category":   "order_issue"
      }
    """

    # ── Handle CORS preflight ────────────────────────────────────────────────
    if event.get("httpMethod") == "OPTIONS":
        return build_response(200, {})

    # ── Parse & validate input ───────────────────────────────────────────────
    try:
        body    = json.loads(event.get("body") or "{}")
        user_id = str(body.get("user_id", "")).strip()
        message = str(body.get("message", "")).strip()

        if not user_id or not message:
            return build_response(400, {"error": "Both 'user_id' and 'message' are required."})

        if len(message) > 2000:
            return build_response(400, {"error": "Message too long (max 2000 characters)."})

    except (json.JSONDecodeError, TypeError) as e:
        log("error", "Invalid request body", error=str(e))
        return build_response(400, {"error": "Invalid JSON in request body."})

    log("info", "Request received", user_id=user_id, message_length=len(message))

    # ── Initialise OpenAI client ─────────────────────────────────────────────
    try:
        openai_client = openai.OpenAI(api_key=get_openai_key())
    except Exception as e:
        log("error", "OpenAI client init failed", error=str(e))
        return build_response(500, {"error": "Service configuration error. Please try again later."})

    # ── Load conversation history ────────────────────────────────────────────
    history = get_history(user_id)

    # ── AI intent classification ─────────────────────────────────────────────
    intent = detect_intent(openai_client, message, history)
    log("info", "Intent detected", user_id=user_id, **intent)

    # ── Generate reply ───────────────────────────────────────────────────────
    try:
        reply = generate_response(openai_client, message, history, intent)
    except openai.RateLimitError:
        log("error", "OpenAI rate limit hit", user_id=user_id)
        return build_response(429, {"error": "Service is busy. Please try again in a moment."})
    except openai.APIError as e:
        log("error", "OpenAI API error", user_id=user_id, error=str(e))
        return build_response(502, {"error": "AI service unavailable. Please try again later."})
    except Exception as e:
        log("error", "Unexpected error generating response", user_id=user_id, error=str(e))
        return build_response(500, {"error": "An unexpected error occurred."})

    # ── Persist updated history ──────────────────────────────────────────────
    history.append({"role": "user",      "content": message})
    history.append({"role": "assistant", "content": reply})
    save_history(user_id, history)

    # ── Escalate if needed ───────────────────────────────────────────────────
    if intent["escalate"]:
        send_escalation(user_id, message, intent)

    # ── Return response ──────────────────────────────────────────────────────
    log("info", "Request completed", user_id=user_id, escalated=intent["escalate"])

    return build_response(200, {
        "reply":      reply,
        "escalation": intent["escalate"],
        "sentiment":  intent["sentiment"],
        "category":   intent["category"]
    })
