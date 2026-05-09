# Deployment Guide

## Docker (Single Container)

The simplest deployment — one container, one command.

```bash
docker run -d \
  --name copilot-gateway \
  --restart unless-stopped \
  -p 3001:3001 \
  -e COPILOT_GITHUB_TOKEN=ghp_your_token_here \
  copilot-gateway:latest
```

To use a config file:

```bash
docker run -d \
  --name copilot-gateway \
  --restart unless-stopped \
  -p 3001:3001 \
  -e COPILOT_GITHUB_TOKEN=ghp_your_token_here \
  -v /path/to/config.yaml:/config/config.yaml:ro \
  copilot-gateway:latest
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
      - "3001:3001"
    environment:
      - COPILOT_GITHUB_TOKEN=${COPILOT_GITHUB_TOKEN}
    volumes:
      - ./config.yaml:/config/config.yaml:ro
```

```bash
# Create .env file
echo "COPILOT_GITHUB_TOKEN=ghp_your_token_here" > .env

# Start
docker compose up -d

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
       image: copilot-gateway:latest
       container_name: copilot-gateway
       restart: unless-stopped
       ports:
         - "3001:3001"
       environment:
         - COPILOT_GITHUB_TOKEN=ghp_your_token_here
       volumes:
         - ./config.yaml:/config/config.yaml:ro
         - ./custom-tools:/custom-tools:ro
   ```
4. Copy your `config.yaml` to the same directory.
5. Start it:
   ```bash
   docker compose up -d
   ```

### Option 2: TrueNAS Custom App

1. Go to **Apps** → **Discover Apps** → **Custom App**.
2. Fill in:
   - **Image:** `copilot-gateway:latest` (or your registry URL)
   - **Port:** 3001 → 3001
   - **Environment Variables:** `COPILOT_GITHUB_TOKEN=ghp_xxx`
   - **Storage:** Mount your config file to `/config/config.yaml`

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

> **Important:** If exposing publicly, add authentication via Cloudflare Access or another auth layer. The gateway itself has no built-in auth.

## Security Considerations

- **copilot-gateway has no built-in authentication.** Anyone who can reach the endpoint can use your Copilot subscription.
- For local/Docker-internal use, this is fine — just don't expose the port publicly.
- For public access, always put it behind an auth layer:
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
