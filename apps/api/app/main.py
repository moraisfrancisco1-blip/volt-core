from fastapi import FastAPI

app = FastAPI(title="VOLT CORE", version="0.1.0")


@app.get("/health")
def health() -> dict:
    return {"status": "online", "service": "volt-core"}


@app.get("/api/v1/status")
def status() -> dict:
    return {
        "core": "online",
        "mode": "observe",
        "production_write": False,
    }
