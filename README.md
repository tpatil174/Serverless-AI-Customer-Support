> Production-style serverless AI support system demonstrating real-world troubleshooting, automation, and escalation workflows using AWS.

AI Project is a **serverless, AI-powered customer support system** built entirely on AWS.
It handles customer queries automatically, maintains conversation memory, detects
dissatisfaction using **real AI intent classification** (not keyword matching), and
escalates critical issues to human support via email.

---

## 🎯 Why This Project

This project simulates a real-world customer support system where:

- Users raise issues via API
- AI understands intent and sentiment
- System responds automatically
- Critical cases are escalated to humans

It demonstrates practical skills in:
- Troubleshooting backend systems
- Handling production-level logging and monitoring
- Designing scalable serverless architectures
- Working with real-world support workflows
---

## Architecture

```
Customer / Frontend
        │
        ▼
Amazon API Gateway  ──  POST /chat
        │
        ▼
AWS Lambda  (AI conversion Core)
  ├── OpenAI API        →  Intent classification + response generation
  ├── Amazon DynamoDB   →  Conversation history (with auto-TTL cleanup)
  ├── Amazon SNS        →  Escalation email to admin
  └── CloudWatch Logs   →  Structured JSON logs (queryable with Insights)
        │
        ▼
Admin Email  (if escalation triggered)
```

---

## Key Features

| Feature | Original approach | This implementation |
|---|---|---|
| Intent detection | Hardcoded keyword list | AI classifies intent + sentiment |
| Error handling | None | Every AWS/OpenAI call wrapped |
| API key storage | Lambda env variable | AWS Secrets Manager |
| Conversation cleanup | Never deleted | DynamoDB TTL (30 days) |
| History overflow | Crashes at token limit | Trimmed to last 10 turns |
| Logging | None | Structured JSON → CloudWatch Insights |
| Frontend-ready | No (no CORS) | Yes (CORS headers + preflight) |
| Response payload | reply + escalation | + sentiment + category |

---

## 🧩 Skills Demonstrated

- Application Support & Incident Handling
- Log Analysis using CloudWatch
- API Debugging & Testing (Postman)
- SQL/NoSQL Data Handling (DynamoDB)
- Cloud Infrastructure (AWS)
- Automation & Escalation Systems
- Problem Solving & Root Cause Analysis
  
----

## AWS Services Used

| Service | Purpose |
|---|---|
| Amazon API Gateway | Exposes `POST /chat` REST endpoint |
| AWS Lambda | Core backend — AI orchestration |
| Amazon DynamoDB | Stores conversation history per user |
| Amazon SNS | Sends escalation alert emails to admin |
| Amazon CloudWatch | Structured JSON logs + monitoring |
| AWS Secrets Manager | Secure storage of OpenAI API key |
| IAM | Least-privilege role for Lambda |

---

## 🧪 Example Real Scenario

User: "I have contacted support twice and my issue is still unresolved"

System behavior:
- Detects negative sentiment
- Classifies issue as escalation-worthy
- Generates empathetic response
- Triggers SNS alert to admin
- Logs full request for analysis

This mirrors real IT support workflows.

----

## How It Works

1. Customer sends `POST /chat` with `user_id` and `message`
2. API Gateway forwards to Lambda
3. Lambda loads conversation history from DynamoDB
4. **AI intent classifier** analyses message + history → returns `escalate`, `sentiment`, `category`
5. AI generates a context-aware reply (tone adjusted for negative sentiment)
6. History is updated in DynamoDB (trimmed to last 10 turns, TTL = 30 days)
7. If escalation triggered → SNS sends structured email to admin
8. Structured JSON log written to CloudWatch
9. Response returned to customer

---

## API Usage

**Endpoint:**
```
POST https://<api-id>.execute-api.<region>.amazonaws.com/prod/chat
```

**Request body:**
```json
{
  "user_id": "customer_123",
  "message": "My order hasn't arrived and I've contacted you twice already"
}
```

**Response:**
```json
{
  "reply": "I'm really sorry to hear this — that's not the experience we want for you. Let me escalate this to our support team right away so someone can resolve it personally.",
  "escalation": true,
  "sentiment": "negative",
  "category": "order_issue"
}
```

**Response fields:**

| Field | Type | Description |
|---|---|---|
| `reply` | string | AI-generated customer-facing response |
| `escalation` | boolean | Whether a human agent was alerted |
| `sentiment` | string | `positive` / `neutral` / `negative` |
| `category` | string | `order_issue` / `billing` / `technical` / `feedback` / `general` / `abuse` |

---

## Setup Guide

### 1. DynamoDB table

- Table name: `AI-Conversations`
- Partition key: `user_id` (String)
- Billing mode: On-demand (PAY_PER_REQUEST)
- Enable TTL on attribute: `ttl`

### 2. SNS topic

- Create an SNS topic (Standard)
- Subscribe your admin email address
- Confirm the subscription from your inbox
- Copy the Topic ARN

### 3. Secrets Manager

```bash
aws secretsmanager create-secret \
  --name aiconversations/openai-api-key \
  --secret-string '{"OPENAI_API_KEY":"sk-your-key-here"}'
```

### 4. IAM role for Lambda

Attach a policy with these permissions:

```json
{
  "Effect": "Allow",
  "Action": [
    "dynamodb:GetItem",
    "dynamodb:PutItem",
    "sns:Publish",
    "secretsmanager:GetSecretValue",
    "logs:CreateLogGroup",
    "logs:CreateLogStream",
    "logs:PutLogEvents"
  ],
  "Resource": "*"
}
```

### 5. Package and deploy Lambda

```bash
cd lambda
pip install -r requirements.txt -t ./package
cp lambda_function.py ./package/
cd package
zip -r ../lambda.zip .
```

Upload `lambda.zip` in the AWS Lambda console.

### 6. Environment variables (Lambda console)

| Variable | Value |
|---|---|
| `DYNAMODB_TABLE` | `AI-Conversations` |
| `SNS_TOPIC_ARN` | Your SNS topic ARN |
| `OPENAI_SECRET_NAME` | `aiconversations/openai-api-key` |

### 7. API Gateway

- Create a REST API
- Add resource `/chat` with method `POST`
- Integration type: Lambda Function (proxy integration)
- Deploy to stage `prod`

---

## CloudWatch Insights queries

All logs are structured JSON. Example queries:

```sql
-- All escalated conversations today
fields @timestamp, user_id, category
| filter message = "Request completed" and escalation = true
| sort @timestamp desc

-- Sentiment breakdown
fields sentiment
| filter message = "Intent detected"
| stats count() by sentiment

-- Average response latency
fields @timestamp, @duration
| filter message = "Request completed"
| stats avg(@duration)
```

---

## Project Structure

```
AI-Conversations/
├── lambda/
│   ├── lambda_function.py   # Main Lambda handler
│   └── requirements.txt     # Python dependencies
├── docs/
│   └── architecture.md      # Detailed architecture notes
├── .gitignore
└── README.md
```

---

## Tech Stack

`AWS Lambda` · `Amazon API Gateway` · `Amazon DynamoDB` · `Amazon SNS` · `Amazon CloudWatch` · `AWS Secrets Manager` · `OpenAI API` · `Python 3.11`

---

## Future Improvements

- [ ] React / HTML frontend with chat UI
- [ ] Sentiment analytics dashboard (CloudWatch + QuickSight)
- [ ] WhatsApp / Telegram integration via Twilio
- [ ] Multi-tenant support (per-business routing)
- [ ] Amazon Cognito authentication
- [ ] CI/CD pipeline with GitHub Actions + AWS SAM

---

## Cost estimate (AWS Free Tier)

| Service | Free tier | Typical usage |
|---|---|---|
| Lambda | 1M requests/month | ~$0 |
| DynamoDB | 25 GB storage | ~$0 |
| API Gateway | 1M calls/month | ~$0 |
| SNS | 1000 emails/month | ~$0 |
| Secrets Manager | 30-day trial, then $0.40/secret/month | ~$0.40 |

**Total: effectively $0 on free tier.**

---

## Author

**Tushar Patil**  
IT Professional · Stuttgart, Germany  
[LinkedIn](https://linkedin.com/in/your-profile) · [GitHub](https://github.com/your-username)
