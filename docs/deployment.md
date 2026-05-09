# Deployment Guide

## Authentication

copilot-gateway uses the Copilot CLI's built-in OAuth authentication (device flow). After starting the container for the first time, you must log in once:

```bash
docker exec -it copilot-gateway copilot auth login
```

This prints a URL and code. Open the URL in your browser, enter the code, and authorize. Credentials are stored in `/home/appuser/.copilot` inside the container — mount a volume there to persist them across restarts.

## Docker (Single Container)

The simplest deployment — one container, one command.

```bash
docker run -d \
  --name copilot-gateway \
  --restart unless-stopped \
  -p 127.0.0.1:3001:3001 \
  -v copilot-cli-data:/home/appuser/.copilot \
  copilot-gateway:latest
```

To enable API key authentication:

```bash
docker run -d \
  --name copilot-gateway \
  --restart unless-stopped \
  -p 127.0.0.1:3001:3001 \
  -v copilot-cli-data:/home/appuser/.copilot \
  -e COPILOT_API_KEY=sk-your-secret-key \
  copilot-gateway:latest
```

To use a config file:

```bash
docker run -d \
  --name copilot-gateway \
  --restart unless-stopped \
  -p 127.0.0.1:3001:3001 \
  -v copilot-cli-data:/home/appuser/.copilot \
  -v /path/to/config.yaml:/config/config.yaml:ro \
  copilot-gateway:latest
```

After the container starts, run the one-time authentication:

```bash
docker exec -it copilot-gateway copilot auth login
```

## Docker Compose

```yaml
# docker-compose.yml
services:
  copilot-gateway:
    build: .
    image: copilot-gateway:latest
    container_name: copilot-gateway
    restart: unless-stopped
    ports:
      - "127.0.0.1:3001:3001"
    environment:
      - COPILOT_API_KEY=${COPILOT_API_KEY:-}
    volumes:
      - copilot-cli-data:/home/appuser/.copilot
      - ./config.yaml:/config/config.yaml:ro

volumes:
  copilot-cli-data:
```

```bash
# Start
docker compose up -d

# First-time setup: authenticate with GitHub
docker exec -it copilot-gateway copilot auth login

# View logs
docker compose logs -f

# Stop
docker compose down
```

## TrueNAS Scale

TrueNAS Scale supports Docker containers. Here's how to deploy copilot-gateway:

### Option 1: Docker Compose via SSH

1. SSH into your TrueNAS box.
2. Create a directory for the deployment:
   ```bash
   mkdir -p /mnt/pool/apps/copilot-gateway
   cd /mnt/pool/apps/copilot-gateway
   ```
3. Create `docker-compose.yml`:
   ```yaml
   services:
     copilot-gateway:
       image: ghcr.io/kenanpashaiev/copilot-gateway:latest
       container_name: copilot-gateway
       restart: unless-stopped
       ports:
         - "127.0.0.1:3001:3001"
       environment:
         - COPILOT_API_KEY=sk-your-secret-key  # optional
       volumes:
         - copilot-cli-data:/home/appuser/.copilot
         - ./config.yaml:/config/config.yaml:ro
         - ./custom-tools:/custom-tools:ro

   volumes:
     copilot-cli-data:
   ```
4. Copy your `config.yaml` to the same directory (optional).
5. Start it:
   ```bash
   docker compose up -d
   ```
6. Authenticate (first time only):
   ```bash
   docker exec -it copilot-gateway copilot auth login
   ```

### Option 2: TrueNAS Custom App

1. Go to **Apps** → **Discover Apps** → **Custom App**.
2. Fill in:
   - **Image:** `ghcr.io/kenanpashaiev/copilot-gateway:latest`
   - **Port:** 3001 → 3001
   - **Environment Variables:** `COPILOT_API_KEY=sk-xxx` (optional)
   - **Storage:** Mount a volume to `/home/appuser/.copilot` for credential persistence
3. After the app starts, SSH into TrueNAS and authenticate:
   ```bash
   docker exec -it <container_id> copilot auth login
   ```

## Behind a Reverse Proxy

If you're exposing the gateway through a reverse proxy (Nginx, Caddy, Traefik):

### Nginx

```nginx
server {
    listen 443 ssl;
    server_name api.yourdomain.com;

    ssl_certificate /path/to/cert.pem;
    ssl_certificate_key /path/to/key.pem;

    location / {
        proxy_pass http://127.0.0.1:3001;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        # Required for SSE streaming
        proxy_buffering off;
        proxy_cache off;
        proxy_read_timeout 300s;
    }
}
```

### Caddy

```
api.yourdomain.com {
    reverse_proxy 127.0.0.1:3001
}
```

Caddy handles SSL automatically and has no buffering issues with SSE.

## Cloudflare Tunnel

Expose the gateway securely without opening ports:

```bash
# Install cloudflared
# Linux: apt install cloudflared / brew install cloudflared
# Or run as Docker sidecar (see below)

# Create tunnel
cloudflared tunnel create copilot-gateway
cloudflared tunnel route dns copilot-gateway api.yourdomain.com

# Run
cloudflared tunnel run copilot-gateway
```

Config (`~/.cloudflared/config.yml`):
```yaml
tunnel: <TUNNEL_ID>
credentials-file: ~/.cloudflared/<TUNNEL_ID>.json

ingress:
  - hostname: api.yourdomain.com
    service: http://localhost:3001
  - service: http_status:404
```

### As a Docker sidecar

```yaml
services:
  copilot-gateway:
    image: copilot-gateway:latest
    # ... (same as above)

  cloudflared:
    image: cloudflare/cloudflared:latest
    restart: unless-stopped
    command: tunnel run
    environment:
      - TUNNEL_TOKEN=${CLOUDFLARE_TUNNEL_TOKEN}
```

> **Important:** If exposing publicly, consider enabling the built-in API key authentication (`COPILOT_API_KEY`) and/or adding an additional auth layer via Cloudflare Access or another provider.

## Security Considerations

- **API key authentication** — Set `COPILOT_API_KEY` (env var) or `server.api_key` (YAML) to require a Bearer token on all requests except `/health`. This uses constant-time comparison to prevent timing attacks.
- **Localhost binding** — Docker Compose binds to `127.0.0.1` by default. Remove the prefix to expose on all interfaces.
- **Non-root container** — The container runs as a non-root `appuser` for defense in depth.
- For public access, consider adding additional layers:
  - **Cloudflare Access** (free for up to 50 users)
  - **Nginx basic auth**
  - **OAuth2 proxy**
  - **Your application's own auth**

## Building the Image

```bash
# Build locally
docker build -t copilot-gateway:latest .

# Tag and push to a registry
docker tag copilot-gateway:latest ghcr.io/youruser/copilot-gateway:latest
docker push ghcr.io/youruser/copilot-gateway:latest
```
