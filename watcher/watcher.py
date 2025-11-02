#!/usr/bin/env python3
"""
Simple Nginx log watcher:
- tails /var/log/nginx/access.log
- parses pool, release, status, upstream_status
- detects pool flips and elevated 5xx error rates
- posts to Slack webhook provided via SLACK_WEBHOOK_URL
"""

import os
import re
import time
import json
import queue
import threading
from collections import deque
from datetime import datetime, timedelta

import requests

LOG_PATH = "/var/log/nginx/access.log"
SLACK_WEBHOOK = os.getenv("SLACK_WEBHOOK_URL", "").strip()
ERROR_RATE_THRESHOLD = float(os.getenv("ERROR_RATE_THRESHOLD", "2"))  # percent
WINDOW_SIZE = int(os.getenv("WINDOW_SIZE", "200"))
ALERT_COOLDOWN_SEC = int(os.getenv("ALERT_COOLDOWN_SEC", "300"))
MAINTENANCE_MODE = os.getenv("MAINTENANCE_MODE", "false").lower() == "true"

# regex to extract fields created by nginx log_format stage_watch
LOG_RE = re.compile(
    r'.*status=(?P<status>\d+).*pool=(?P<pool>[^ ]+)\s+release=(?P<release>[^ ]+)\s+upstream_status=(?P<upstream_status>[^ ]+)\s+upstream_addr=(?P<upstream_addr>[^ ]+)\s+req_time=(?P<req_time>[^ ]+)\s+upstream_rt=(?P<upstream_rt>[^ ]+).*'
)

# rolling window for status codes (store ints)
window = deque(maxlen=WINDOW_SIZE)
last_pool = None
last_release = None  # Track previous release
last_alert = {}  # alert_type -> timestamp


def send_slack(title: str, text: str, color: str = "#d93025"):
    if not SLACK_WEBHOOK:
        print("[watcher] SLACK_WEBHOOK_URL not set, skipping alert:", title)
        return
    payload = {
        "attachments": [
            {
                "fallback": title,
                "color": color,
                "title": title,
                "text": text,
                "ts": int(time.time())
            }
        ]
    }
    try:
        r = requests.post(SLACK_WEBHOOK, json=payload, timeout=5)
        if r.status_code >= 400:
            print("[watcher] Slack returned", r.status_code, r.text)
    except Exception as e:
        print("[watcher] Slack send failed:", e)


def cooldown_allows(alert_key: str):
    now = time.time()
    last = last_alert.get(alert_key)
    if last and (now - last) < ALERT_COOLDOWN_SEC:
        return False
    last_alert[alert_key] = now
    return True


def process_log_line(line: str):
    global last_pool, last_release
    m = LOG_RE.match(line)
    if not m:
        return

    try:
        status = int(m.group("status"))
    except Exception:
        status = 0
    pool = m.group("pool")
    release = m.group("release")
    upstream_status = m.group("upstream_status")
    upstream_addr = m.group("upstream_addr")
    req_time = m.group("req_time")
    upstream_rt = m.group("upstream_rt")

    # rolling window update
    window.append(status)

    # failover detection: pool changed
    if last_pool is None:
        last_pool = pool
        last_release = release
    elif pool != last_pool:
        if not MAINTENANCE_MODE and cooldown_allows(f"failover:{last_pool}->{pool}"):
            title = f"🔄 Failover detected: {last_pool} → {pool}"
            # Show release transition: old -> new
            release_transition = f"{last_release} → {release}" if last_release else release
            text = (
                f"*Release (from→to)*: {release_transition}\n"
                f"*Upstream*: {upstream_addr}\n"
                f"*Upstream_status*: {upstream_status}\n"
                f"*Req_time*: {req_time}s\n"
                f"Time: {datetime.utcnow().isoformat()}Z"
            )
            send_slack(title, text, color="#ff9900")
        last_pool = pool
        last_release = release
    else:
        # Update release even if pool hasn't changed (for rolling updates within same pool)
        last_release = release

    # error-rate detection
    total = len(window)
    if total >= 10:  # only evaluate when some data exists
        errors = sum(1 for s in window if 500 <= s <= 599)
        error_rate = (errors / total) * 100.0
        if error_rate >= ERROR_RATE_THRESHOLD and not MAINTENANCE_MODE:
            if cooldown_allows("error_rate"):
                title = f"🚨 High upstream 5xx rate: {error_rate:.2f}% over last {total} reqs"
                text = (
                    f"Errors: {errors} of {total}\n"
                    f"Threshold: {ERROR_RATE_THRESHOLD}%\n"
                    f"Latest upstream: {upstream_addr}\n"
                    f"Latest pool: {pool}\n"
                    f"Latest release: {release}\n"
                    f"Time: {datetime.utcnow().isoformat()}Z"
                )
                send_slack(title, text, color="#d93025")


def tail_log(path, q: queue.Queue):
    # follow file; handle rotation by re-opening if inode changes
    with open(path, "r") as f:
        # seek to end
        f.seek(0, 2)
        inode = os.fstat(f.fileno()).st_ino
        while True:
            line = f.readline()
            if line:
                q.put(line)
            else:
                time.sleep(0.1)
                # check rotation
                try:
                    if os.stat(path).st_ino != inode:
                        f = open(path, "r")
                        inode = os.fstat(f.fileno()).st_ino
                except FileNotFoundError:
                    time.sleep(0.5)


def main():
    if not os.path.exists(LOG_PATH):
        print(f"[watcher] log path {LOG_PATH} does not exist yet - waiting...")
        while not os.path.exists(LOG_PATH):
            time.sleep(1)
    q = queue.Queue()
    t = threading.Thread(target=tail_log, args=(LOG_PATH, q), daemon=True)
    t.start()
    print("[watcher] started, monitoring", LOG_PATH)
    try:
        while True:
            try:
                line = q.get(timeout=1)
                process_log_line(line)
            except queue.Empty:
                continue
    except KeyboardInterrupt:
        print("[watcher] exiting")


if __name__ == "__main__":
    main()