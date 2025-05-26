# 🛰️ Service Tracker Dashboard

A lightweight Flask-based dashboard to track running Docker containers across hosts.  
It displays host, container name, URLs, last updated time, and links to container logs (via Dozzle).

---

## 🚀 Features

- Add and edit container records manually or via API
- Live filter and table sorting
- Auto-refresh support
- Tooltips for full container IDs

---

## 🖼️ Dashboard View

The main dashboard includes:

- Host and container name
- Internal / External URL buttons
- Last updated time (human readable)
- Tools (like Dozzle log viewer)
- Optional Stack column (shown only if any records use it)

---

## 📦 API Usage

### `POST /api/register`

Register or update a service entry from a container host.

#### Headers
```
Authorization: Bearer <your-api-token>
Content-Type: application/json
```

#### Example Payload
```json
{
  "host": "docker01",
  "container_name": "nginx",
  "container_id": "abc123...",
  "internalurl": "http://nginx:80",
  "externalurl": "https://nginx.example.com",
  "stack_name": "reverse-proxies"
}
```

- `host` and `container_name` are required
- Will **upsert** entries by container name

---

## ⚙️ Environment Variables

| Variable           | Default                | Description                        |
|--------------------|------------------------|------------------------------------|
| `API_TOKEN`        | `supersecrettoken`     | Bearer token for API auth          |
| `STD_DOZZLE_URL`   | `http://localhost:8888`| URL to your Dozzle container logs  |


---

## 🐳 Docker

### Build & Run Locally

```bash
docker build -t service-tracker-dashboard .
docker run -p 8815:8815 \
  -e API_TOKEN=your_token \
  -e STD_DOZZLE_URL=http://dozzle:8888 \
  -v $PWD/config:/config \
  service-tracker-dashboard
```


## 🧪 To Do / Ideas

- Add API `GET /services`
- Add API `DELETE` or TTL support
- Auto-discovery from docker events (via notifier)
- Websockets for real-time updates
- Add when containers go down.

---

## ✍️ License


