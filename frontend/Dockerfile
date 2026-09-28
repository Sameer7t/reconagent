# =============================================================================
# ReconAgent Frontend Dockerfile (Multi-stage Build)
# Production Container: Vite React App compiled & served via Nginx Reverse Proxy
# =============================================================================

# --- Stage 1: Build Vite React Application ---
FROM node:20-alpine AS build

WORKDIR /app

# Copy dependency manifests
COPY package.json package-lock.json* ./

# Install packages with clean install fallback
RUN if [ -f package-lock.json ]; then npm ci; else npm install; fi

# Copy frontend source files
COPY . .

# Compile TypeScript and Vite production bundle
RUN npm run build

# --- Stage 2: Serve via Nginx ---
FROM nginx:1.27-alpine

# Copy compiled static assets from build stage
COPY --from=build /app/dist /usr/share/nginx/html

# Copy custom Nginx configuration with API reverse proxy
COPY nginx.conf /etc/nginx/conf.d/default.conf

# Expose HTTP port 80
EXPOSE 80

# Healthcheck to verify Nginx webserver is serving HTML
HEALTHCHECK --interval=10s --timeout=5s --start-period=5s --retries=3 \
    CMD wget -q -O - http://localhost/ || exit 1

CMD ["nginx", "-g", "daemon off;"]
