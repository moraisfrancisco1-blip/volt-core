import os

from fastapi import APIRouter

# Single source of truth for which origins the frontend is trusted to call from --
# main.py's CORSMiddleware imports this too, so there's only one list to keep in sync.
VOLT_CORS_ORIGINS = ["https://volt-core.vercel.app", "https://volt-core-git-main-voltaris-os.vercel.app"]

router = APIRouter(prefix="/api", tags=["integrations"])


@router.get("/integrations/status")
def integrations_status() -> list[dict]:
    # Presence only, never values -- same discipline as every credential check
    # elsewhere in this codebase (RAILWAY_TOKEN, GITHUB_TOKEN, etc.).
    twilio_configured = bool(
        os.getenv("TWILIO_ACCOUNT_SID") and os.getenv("TWILIO_AUTH_TOKEN") and os.getenv("TWILIO_PHONE_NUMBER")
    )
    return [
        {"name": "railway", "label": "Railway", "configured": bool(os.getenv("RAILWAY_TOKEN"))},
        {"name": "github", "label": "GitHub", "configured": bool(os.getenv("GITHUB_TOKEN"))},
        # Vercel has no credential of its own in this backend -- the only inspectable
        # fact here is that CORS already trusts the Vercel origins, which is a code
        # fact, not a secret.
        {"name": "vercel", "label": "Vercel", "configured": any("vercel.app" in origin for origin in VOLT_CORS_ORIGINS)},
        # Reflects whether DATABASE_URL was explicitly set, not the hardcoded local
        # dev fallback in db.py.
        {"name": "postgres", "label": "Postgres", "configured": bool(os.getenv("DATABASE_URL"))},
        {"name": "twilio", "label": "Twilio", "configured": twilio_configured},
        {"name": "anthropic", "label": "Anthropic API", "configured": bool(os.getenv("ANTHROPIC_API_KEY"))},
    ]
