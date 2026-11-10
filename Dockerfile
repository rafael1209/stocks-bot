# syntax=docker/dockerfile:1

# 1) the React dashboard
FROM node:22-alpine AS web
WORKDIR /web
COPY dashboard/package.json dashboard/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY dashboard/ ./
RUN npm run build

# 2) the bot + dashboard server (one image, two containers – see docker-compose.yml)
FROM python:3.13-slim
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 MPLBACKEND=Agg TZ=America/New_York
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY *.py config.yaml ./
COPY setups/ setups/
COPY --from=web /web/dist dashboard/dist
RUN mkdir -p state charts
EXPOSE 8787
CMD ["python", "main.py"]
