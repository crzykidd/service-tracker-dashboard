FROM python:3.11-slim
WORKDIR /app
COPY . .

RUN pip install --no-cache-dir -r requirements.txt

# Add version info as a build argument
ARG APP_VERSION=dev
ARG GIT_COMMIT=unknown

# Create version file during build
RUN echo "version=${APP_VERSION}" > /app/version.txt && \
    echo "commit=${GIT_COMMIT}" >> /app/version.txt && \
    echo "build_time=$(date -u +"%Y-%m-%dT%H:%M:%SZ")" >> /app/version.txt
EXPOSE 8815
CMD ["sh", "-c", "alembic upgrade head && python app.py"]
