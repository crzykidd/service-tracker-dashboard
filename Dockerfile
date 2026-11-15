FROM python:3.11-slim
WORKDIR /app
COPY . .

RUN pip install --no-cache-dir -r requirements.txt

# Build metadata. The app version comes from the VERSION file at the repo
# root (copied in above) -- there is intentionally no version build arg.
ARG GIT_COMMIT=unknown
# Set to "dockerhub" only for the deprecated Docker Hub image (shows the
# "moved to GHCR" banner). Empty for GHCR and local builds.
ARG REGISTRY_NOTICE=

# Create version file during build
RUN echo "version=$(tr -d '[:space:]' < /app/VERSION)" > /app/version.txt && \
    echo "commit=${GIT_COMMIT}" >> /app/version.txt && \
    echo "registry_notice=${REGISTRY_NOTICE}" >> /app/version.txt && \
    echo "build_time=$(date -u +"%Y-%m-%dT%H:%M:%SZ")" >> /app/version.txt
EXPOSE 8815

COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh


CMD ["/entrypoint.sh"]

