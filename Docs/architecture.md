# Architecture — PunAI

## Component responsibilities

### API Gateway
- Single resource: `POST /chat`
- Lambda proxy integration (passes full HTTP request to Lambda)
- CORS handled in Lambda code (not API Gateway config)
- Stage: `prod`

### Lambda — `lambda_function.py`

Three logical sections:

**1. Input validation**
Rejects requests missing `user_id` or `message`, or messages over 2000 characters.
Returns 400 with a clear error message.

**2. Intent classification (separate AI call)**
A dedicated prompt asks GPT-3.5-turbo to return JSON only:
```
{ escalate: bool, reason: str, sentiment: str, category: str }
```
`temperature=0` ensures deterministic classification.
The last 4 messages of conversation history are passed as context
so the classifier understands tone over time (e.g. repeated complaints).

**3. Response generation (main AI call)**
The system prompt is dynamically adjusted based on detected sentiment:
- `negative` → empathetic persona, acknowledge feeling first
- `neutral` / `positive` → standard helpful persona

Full conversation history (last 10 turns) is passed for context.

### DynamoDB

Table schema:
```
user_id      (String, Partition Key)
history      (List of {role, content} objects)
last_updated (ISO timestamp string)
ttl          (Number — Unix epoch, 30 days from last write)
```

History is trimmed to `MAX_HISTORY_TURNS * 2 = 20` messages before saving.
DynamoDB TTL silently deletes items after the `ttl` timestamp passes.

### SNS

Triggered only when `intent["escalate"] == True`.
Email subject includes the category for admin triage:
`[PunAI] Escalation — Order Issue`

Email body includes: user_id, sentiment, category, AI reason, original message, timestamp.

### Secrets Manager

OpenAI API key stored as:
```json
{ "OPENAI_API_KEY": "sk-..." }
```
Fetched once per cold start and cached in the module-level variable `_openai_key_cache`.
Subsequent warm invocations reuse the cached value (no extra API call).

### CloudWatch

Every significant event emits a structured JSON log via the `log()` helper:
```json
{
  "level": "info",
  "message": "Intent detected",
  "timestamp": "2026-04-22T10:30:00Z",
  "user_id": "customer_123",
  "escalate": true,
  "sentiment": "negative",
  "category": "order_issue"
}
```
This makes logs fully queryable with CloudWatch Insights without regex parsing.

## Error handling strategy

| Failure | Behaviour |
|---|---|
| Missing env variables | Log warning, skip that feature (e.g. no SNS) |
| DynamoDB read failure | Return empty history, continue answering |
| DynamoDB write failure | Log error, still return response to user |
| OpenAI rate limit (429) | Return HTTP 429 with retry message |
| OpenAI API error | Return HTTP 502 |
| Intent parse failure | Default to `escalate=False`, log warning |
| SNS publish failure | Log error, non-fatal |

The key principle: **no single AWS service failure should prevent the user from getting a response.**

## Security considerations

- OpenAI key in Secrets Manager, never in env variables or code
- IAM role uses least privilege (only the 6 actions it needs)
- No credentials committed to GitHub (`.gitignore` covers `.env`)
- Serverless = no EC2 attack surface
- CORS `Allow-Origin: *` — tighten to your domain in production
