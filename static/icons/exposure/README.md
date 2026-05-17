# Exposure Layer Brand Icons

SVG icons used for the exposure layer badges on the tiled dashboard.
All sourced from official brand channels only.

| File | Brand | Source | Date Sourced | Notes |
|------|-------|--------|--------------|-------|
| `traefik.svg` | Traefik Proxy | [traefik/traefik](https://github.com/traefik/traefik) — `docs/content/assets/img/traefikproxy-vertical-logo-color.svg` | 2026-05-17 | viewBox cropped to `0 0 209 165` — teal geometric symbol only; black wordmark at y>165 excluded |
| `cloudflare.svg` | Cloudflare | cloudflare.com — `img/logo-cloudflare-dark.svg` | 2026-05-17 | viewBox cropped to `54 0 55 41` — orange/white cloud symbol only; dark text at x<54 excluded |
| `dockflare.svg` | DockFlare (Cloudflare Tunnel) | Same as `cloudflare.svg` | 2026-05-17 | DockFlare is a Cloudflare Tunnel automation wrapper; uses Cloudflare brand per project identity |
| `nginx.svg` | nginx | nginx.org — `img/nginx_logo.svg` | 2026-05-17 | viewBox cropped to `0 0 155 183` — green N emblem only; dark wordmark at x>155 excluded |
| `caddy.svg` | Caddy | [caddyserver/website](https://github.com/caddyserver/website) — `src/old/resources/images/caddy-circle-lock.svg` | 2026-05-17 | viewBox `0 0 401 401` (1:1 ratio); teal circle + padlock icon; includes embedded base64 PNG textures |

## Usage

Icons are rendered at 18×18 px with `object-fit: contain` in the exposure icon row on each service tile.
The `.exposure-icon-img` CSS class handles sizing and display.

## License Note

These are brand/trademark assets. Usage is purely for identifying which reverse proxy or tunnel
technology is in use on the operator's own infrastructure. No modification to colors or shapes
has been made beyond viewBox cropping to isolate the icon portion of compound logo files.
