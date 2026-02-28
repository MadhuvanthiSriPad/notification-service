# Testing Notification Service

## Overview
The notification-service receives webhook events (pr_opened, recovery_complete) from api-core and creates Jira tickets + Slack messages for downstream remediation PRs.

## Devin Secrets Needed
- `NOTIF_SLACK_BOT_TOKEN` — Slack bot token (xoxb-...)
- `NOTIF_SLACK_CHANNEL` — Slack channel ID (e.g. C0AHVM3HNTW)
- `NOTIF_JIRA_API_TOKEN` — Jira Cloud API token
- `NOTIF_JIRA_USER_EMAIL` — Jira user email for Basic auth
- `NOTIF_JIRA_BASE_URL` — e.g. https://yourorg.atlassian.net
- `NOTIF_JIRA_PROJECT_KEY` — Jira project key (e.g. TEST)

## Running Locally
```bash
cd ~/repos/notification-service
source .venv/bin/activate
export NOTIF_SLACK_BOT_TOKEN="$NOTIF_SLACK_BOT_TOKEN"
export NOTIF_SLACK_CHANNEL="$NOTIF_SLACK_CHANNEL"
export NOTIF_JIRA_API_TOKEN="$NOTIF_JIRA_API_TOKEN"
export NOTIF_JIRA_USER_EMAIL="$NOTIF_JIRA_USER_EMAIL"
export NOTIF_JIRA_BASE_URL="$NOTIF_JIRA_BASE_URL"
export NOTIF_JIRA_PROJECT_KEY=TEST
uvicorn src.main:app --port 8002 --host 0.0.0.0
```

Health check: `curl http://localhost:8002/health`

## Running Tests
```bash
cd ~/repos/notification-service && source .venv/bin/activate && pytest tests/ -v
```

## E2E Test: pr_opened Webhook
```bash
curl -s -X POST http://localhost:8002/api/v1/webhooks/pr-opened \
  -H "Content-Type: application/json" \
  -d '{
    "event_type": "pr_opened",
    "change_id": 1,
    "job_id": 9999,
    "timestamp": "2026-01-01T00:00:00Z",
    "target_repo": "https://github.com/MadhuvanthiSriPad/billing-service",
    "target_service": "billing-service",
    "pr_url": "https://github.com/MadhuvanthiSriPad/billing-service/pull/42",
    "devin_session_url": "https://app.devin.ai/sessions/test-session",
    "severity": "high",
    "is_breaking": true,
    "summary": "Test change summary",
    "changed_routes": ["POST /api/v1/sessions"]
  }'
```

**Important:** Use a unique `job_id` for each test run — the service deduplicates on `pr_opened:{job_id}`. If you get `"status": "already_processed"`, increment the job_id.

## E2E Test: recovery_complete Webhook
```bash
curl -s -X POST http://localhost:8002/api/v1/webhooks/recovery-complete \
  -H "Content-Type: application/json" \
  -d '{
    "event_type": "recovery_complete",
    "change_id": 1,
    "timestamp": "2026-01-01T01:00:00Z",
    "severity": "high",
    "is_breaking": true,
    "summary": "Test recovery summary",
    "affected_services": ["billing-service"],
    "changed_routes": ["POST /api/v1/sessions"],
    "total_jobs": 1,
    "jobs": [{"job_id": 9999, "target_repo": "https://github.com/MadhuvanthiSriPad/billing-service", "target_service": "billing-service", "pr_url": "https://github.com/MadhuvanthiSriPad/billing-service/pull/42"}],
    "mttr_seconds": 1800
  }'
```

## Verifying Jira Tickets
```bash
curl -s -u "$NOTIF_JIRA_USER_EMAIL:$NOTIF_JIRA_API_TOKEN" \
  -H "Accept: application/json" \
  "$NOTIF_JIRA_BASE_URL/rest/api/3/issue/TEST-{N}?fields=summary,description" | python3 -m json.tool
```

## Common Pitfalls

### Slack bot "not_in_channel"
The Slack bot must be explicitly invited to the channel. The Slack API returns HTTP 200 even when the bot can't post — it signals failure via `{"ok": false, "error": "not_in_channel"}` in the response body. The service now correctly raises on this (as of the SlackClient fix), so you'll see `slack_sent: false` in the webhook response.

**Fix:** Have the channel owner type `/invite @BotName` in the Slack channel.

To test if the bot has access:
```bash
curl -s -X POST https://slack.com/api/chat.postMessage \
  -H "Authorization: Bearer $NOTIF_SLACK_BOT_TOKEN" \
  -H "Content-Type: application/json" \
  -d "{\"channel\": \"$NOTIF_SLACK_CHANNEL\", \"text\": \"Bot access test\"}" | python3 -m json.tool
```

### Idempotency / "already_processed" responses
The service deduplicates on `pr_opened:{job_id}` and `recovery_complete:{change_id}`. If re-testing, either:
- Use a new job_id / change_id
- Delete the local `notification.db` file and restart the service

### SQLite DB location
By default the service creates `notification.db` in the repo root. Delete it to reset state between test runs.
