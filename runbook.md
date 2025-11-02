# Deployment Monitoring Runbook

## Alert Types

### 🔄 Failover Detected

**What happened:** Nginx switched traffic from one pool to another (e.g., blue → green)

**What to do:**

1. Check if this was planned maintenance
2. Check logs of the failed pool:
   ```bash
   docker-compose logs app_blue --tail=50
   ```
3. Verify the new pool is healthy:
   ```bash
   curl http://localhost:8080/healthz
   ```

**To restore the failed pool:**
```bash
# Restart the container
docker-compose restart app_blue

# Switch back if needed
# Edit .env: ACTIVE_POOL=blue
docker-compose restart nginx
```

---

### 🚨 High Error Rate

**What happened:** More than 2% of requests are returning 5xx errors

**What to do:**

1. Check which pool is affected (see alert message)
2. Check application logs:
   ```bash
   docker-compose logs app_blue --tail=50  # or app_green
   ```
3. Switch to the healthy pool:
   ```bash
   # Edit .env: ACTIVE_POOL=green
   docker-compose restart nginx
   ```

**Common causes:**
- Application crashed
- Database connection failed
- Out of memory
- Bad deployment

---

## Testing Alerts

**Test failover:**
```bash
docker-compose stop app_blue
for i in {1..10}; do curl http://localhost:8080/healthz; sleep 1; done
docker-compose start app_blue
```

**Test error rate:**
```bash
# Enable chaos mode
curl -X POST "http://localhost:8082/chaos/start?mode=error"

# Generate traffic
for i in {1..100}; do curl -s http://localhost:8080/version; sleep 0.1; done

# Stop chaos
curl -X POST "http://localhost:8082/chaos/stop"
```

---

## Maintenance Mode

**Suppress alerts during planned work:**
```bash
# Edit .env: MAINTENANCE_MODE=true
docker-compose restart alert_watcher

# When done: MAINTENANCE_MODE=false
docker-compose restart alert_watcher
```

---

## Configuration

Edit `.env` to tune alerts:

- `ERROR_RATE_THRESHOLD=2` - Alert when error rate exceeds 2%
- `WINDOW_SIZE=200` - Monitor last 200 requests
- `ALERT_COOLDOWN_SEC=300` - Wait 5 minutes between duplicate alerts