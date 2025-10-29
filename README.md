# Blue-Green Deployment with Nginx (Failover Setup)

This project sets up a **Blue-Green deployment** using **Docker Compose** with **automatic failover** handled by Nginx.

---

## 📦 Services

- **Nginx Proxy** → Routes traffic to Blue (active) or Green (backup)
- **App Blue** → Primary Node.js service
- **App Green** → Backup Node.js service

---

## ⚙️ Environment Variables

Create a `.env` file in the project root:

```bash
BLUE_IMAGE=yimikaade/wonderful:devops-stage-two
GREEN_IMAGE=yimikaade/wonderful:devops-stage-two
ACTIVE_POOL=blue
RELEASE_ID_BLUE=v1.0.0
RELEASE_ID_GREEN=v1.0.1
PORT=8080
```

---

## 🚀 Running the Project

```bash
docker-compose up -d
```

Access the service at:

```
http://localhost:8080/version
```

Expected headers:

```
X-App-Pool: blue
X-Release-Id: v1.0.0
```

---

## 💥 Simulating Failover

Trigger downtime on Blue:

```bash
curl -X POST http://localhost:8081/chaos/start?mode=error
```

Nginx will automatically reroute to Green.
Check again:

```bash
curl -i http://localhost:8080/version
```

Expected headers:

```
X-App-Pool: green
X-Release-Id: v1.0.1
```

Stop chaos simulation:

```bash
curl -X POST http://localhost:8081/chaos/stop
```

---

## 🧩 Project Structure

```
.
├── docker-compose.yml
├── .env
├── nginx/
│   ├── nginx.conf.template
│   └── render-and-run.sh
└── README.md
```

---

## 🧰 Notes

* Nginx forwards all headers unchanged.
* Failover happens instantly (no client errors).
* Blue is active by default, Green is backup.
