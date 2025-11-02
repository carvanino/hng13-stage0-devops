# Blue-Green Deployment with Monitoring

A blue-green deployment system with automated failover detection and error rate monitoring. Alerts are sent to Slack when issues are detected.

## Features

- Blue-green deployment with automatic failover
- Real-time monitoring of upstream health
- Slack alerts for failovers and high error rates
- Chaos testing endpoints for validation
- Zero-downtime deployments

---

## Setup

### 1. Configure Environment Variables

Create a `.env` file:

```bash
# Deployment configuration
ACTIVE_POOL=blue
BLUE_IMAGE=myapp:blue
GREEN_IMAGE=myapp:green
RELEASE_ID_BLUE=v1.0.0
RELEASE_ID_GREEN=v1.1.0

# Slack alerting
SLACK_WEBHOOK_URL=https://hooks.slack.com/services/YOUR/WEBHOOK/URL

# Alert thresholds
ERROR_RATE_THRESHOLD=2
WINDOW_SIZE=200
ALERT_COOLDOWN_SEC=300
MAINTENANCE_MODE=false
```

### 2. Start Services

```bash
docker-compose up -d
```

### 3. Verify Everything is Running

```bash
# Check all containers are up
docker-compose ps

# Test the application
curl http://localhost:8080/version
curl http://localhost:8080/healthz
```

---

## Testing Alerts

### Test Error Rate Detection

Use the chaos endpoint to generate 5xx errors:

```bash
# Start error mode on green pool
curl -X POST "http://localhost:8082/chaos/start?mode=error"

# Generate traffic through nginx
for i in {1..100}; do 
  curl -s http://localhost:8080/version
  sleep 0.1
done

# Check Slack for error rate alert

# Stop chaos mode
curl -X POST "http://localhost:8082/chaos/stop"
```

### Test Failover Detection

Use timeout mode to trigger health check failures:

```bash
# Start timeout mode on blue pool (if blue is active)
curl -X POST "http://localhost:8081/chaos/start?mode=timeout"

# Make requests - health checks will fail and trigger failover
for i in {1..20}; do 
  curl -s http://localhost:8080/healthz
  sleep 1
done

# Check Slack for failover alert

# Stop chaos mode
curl -X POST "http://localhost:8081/chaos/stop"
```

---

## Viewing Logs

```bash
# View watcher logs
docker-compose logs -f alert_watcher

# View nginx logs
docker-compose exec nginx tail -f /var/log/nginx/access.log

# View application logs
docker-compose logs -f app_blue
docker-compose logs -f app_green
```

---

## Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `ACTIVE_POOL` | `blue` | Which pool receives traffic |
| `ERROR_RATE_THRESHOLD` | `2` | Error rate % to trigger alert |
| `WINDOW_SIZE` | `200` | Number of requests to monitor |
| `ALERT_COOLDOWN_SEC` | `300` | Seconds between duplicate alerts |
| `MAINTENANCE_MODE` | `false` | Suppress alerts during maintenance |
