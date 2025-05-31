
# 🧭 Service Tracker Dashboard

A simple Flask-based dashboard to track and display metadata, health, and status information for services running in Docker containers. Designed for home lab and small-scale infrastructure environments, this dashboard aggregates info via API or web form and offers health checks, image tracking, and status indicators.

---

## 🚀 Features

- Web dashboard to view and filter containers by group, stack, host, etc.
- REST API for registering/updating service metadata
- Internal and external health check monitoring
- Auto-download icons from [homarr-labs dashboard-icons](https://github.com/homarr-labs/dashboard-icons)
- SQLite-backed, persistent tracking
- Includes log rotation and optional Dozzle integration
- Image and status badge caching

---

## 🔧 Environment Variables

| Variable            | Description                                         | Default                |
|---------------------|-----------------------------------------------------|------------------------|
| `API_TOKEN`         | API bearer token required for `/api/register`       | `supersecrettoken`     |
| `STD_DOZZLE_URL`    | Optional: link to Dozzle logs for service containers| `http://localhost:8888`|
| `FLASK_DEBUG`       | Enable Flask debug mode                             | `0`                    |

---

## 🐳 Docker Compose

```yaml
services:
  service-tracker-dashboard:
    image: yourdockerhubuser/service-tracker-dashboard:latest
    container_name: service-tracker-dashboard
    ports:
      - 8815:8815
    environment:
      - API_TOKEN=supersecrettoken
      - STD_DOZZLE_URL=http://dozzle.local
      - FLASK_DEBUG=0
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock:ro
      - /etc/hostname:/etc/host_hostname:ro
      - ./config:/config
    restart: unless-stopped
```

> Replace `yourdockerhubuser/service-tracker-dashboard` with your actual Docker image.

---

## 📥 API Usage

### `POST /api/register`

Registers or updates a container entry.

**Headers:**
```http
Authorization: Bearer <API_TOKEN>
Content-Type: application/json
```

**Body Parameters (partial list):**
```json
{
  "host": "docker01",
  "container_name": "nginx",
  "container_id": "abc123...",
  "internalurl": "http://nginx:80",
  "externalurl": "https://my.domain.com",
  "stack_name": "frontend",
  "docker_status": "running",
  "image_name": "ghcr.io/user/nginx:latest",
  "group_name": "web",
  "internal_health_check_enabled": true,
  "external_health_check_enabled": true,
  "image_icon": "nginx.svg"
}
```

---

## 🔖 Labels (for automation tools)

Optional: Apply these labels to containers for automated tracking via companion tools.

```yaml
labels:
  - "dockernotifier.notifiers=service-tracker-dashboard"
```

---

## 📁 Files & Paths

- Database: `/config/services.db`
- Logs: `/config/std.log` (rotated)
- Icons: `/config/images/` (cached or downloaded from GitHub)

---

## 📊 UI Features

- Sortable and grouped table view
- Add/Edit/Delete records via form
- Real-time status display
- Cached icon and metadata rendering

---

## 🧪 Health Checks

- Runs every 60 seconds in a background thread
- Both internal and external URLs are probed
- Status and timestamp saved to the database

---

## 🛠 Dev Notes

- Logs show health check results and image icon fetches.
- Image names are parsed to extract registry, owner, name, and tag.
- Icons are pulled from:  
  `https://raw.githubusercontent.com/homarr-labs/dashboard-icons/main/svg/<image_icon>`

---

## 📍 Accessing

Open your browser to:  
[http://localhost:8815](http://localhost:8815)

- `/` → Dashboard  
- `/add` → Manual entry form  
- `/edit/<id>` → Edit entry  
- `/dbdump` → Raw DB list  
- `/api/register` → API endpoint  
- `/images/<filename>` → Cached icons
