# VOLT CORE Staging

This environment is for real service validation without connecting production systems.

## 1. Create local environment file

Copy `.env.staging.example` to `.env.staging` and replace every placeholder with long random secrets.

Never commit `.env.staging`.

## 2. Start

```bash
docker compose --env-file .env.staging -f docker-compose.staging.yml up --build -d
```

## 3. Check health

```bash
curl http://127.0.0.1:8000/health
```

Expected response includes `status: online` and `database: postgresql`.

## 4. Stop

```bash
docker compose --env-file .env.staging -f docker-compose.staging.yml down
```

Use `down -v` only when you intentionally want to erase staging data.
