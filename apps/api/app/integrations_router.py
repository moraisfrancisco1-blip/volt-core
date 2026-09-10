import os

from fastapi import APIRouter

# Single source of truth for which origins the frontend is trusted to call from --
# main.py's CORSMiddleware imports this too, so there's only one list to keep in sync.
VOLT_CORS_ORIGINS = ["https://volt-core.vercel.app", "https://volt-core-git-main-voltaris-os.vercel.app"]

router = APIRouter(prefix="/api", tags=["integrations"])


def twilio_configured() -> bool:
    # Shared with telegram.py's "status" command -- one place owns this condition.
    return bool(os.getenv("TWILIO_ACCOUNT_SID") and os.getenv("TWILIO_AUTH_TOKEN") and os.getenv("TWILIO_PHONE_NUMBER"))


@router.get("/integrations/status")
def integrations_status() -> list[dict]:
    # Presence only, never values -- same discipline as every credential check
    # elsewhere in this codebase (RAILWAY_TOKEN, GITHUB_TOKEN, etc.).
    #
    # This list covers every credential an agent actually depends on, not only the
    # platform ones. The dashboard's agent sheet cross-references these entries by
    # `name`, so a credential absent from here shows up as "the panel cannot tell",
    # which is a worse answer than "not set". Treat `name` as a stable identifier:
    # AgentSheet.jsx's CREDENTIALS map keys off it.
    return [
        # --- plataforma ---
        {"name": "railway", "label": "Railway", "configured": bool(os.getenv("RAILWAY_TOKEN"))},
        {"name": "github", "label": "GitHub", "configured": bool(os.getenv("GITHUB_TOKEN"))},
        # Vercel has no credential of its own in this backend -- the only inspectable
        # fact here is that CORS already trusts the Vercel origins, which is a code
        # fact, not a secret.
        {"name": "vercel", "label": "Vercel", "configured": any("vercel.app" in origin for origin in VOLT_CORS_ORIGINS)},
        # Reflects whether DATABASE_URL was explicitly set, not the hardcoded local
        # dev fallback in db.py.
        {"name": "postgres", "label": "Postgres", "configured": bool(os.getenv("DATABASE_URL"))},
        {"name": "twilio", "label": "Twilio", "configured": twilio_configured()},
        {"name": "anthropic", "label": "Anthropic API", "configured": bool(os.getenv("ANTHROPIC_API_KEY"))},

        # --- sistemas externos que os agentes leem ---
        # VoltarisOS: só a chave conta. VOLTARIS_BASE_URL tem um default que funciona
        # (ver voltaris_client.py), por isso a sua ausência não impede a ligação.
        {
            "name": "voltaris",
            "label": "VoltarisOS · chave de serviço",
            "configured": bool(os.getenv("VOLTARIS_SERVICE_KEY")),
        },
        # Dai Oakes precisa das duas: DAIOAKES_BASE_URL não tem default (fica ""), e
        # external_connector.get() recusa-se a sair com base_url vazio -- a chave
        # sozinha não liga a lado nenhum.
        {
            "name": "daioakes",
            "label": "Dai Oakes · chave de serviço",
            "configured": bool(os.getenv("VOLT_CORE_SERVICE_KEY_DAIOAKES") and os.getenv("DAIOAKES_BASE_URL")),
        },
        {"name": "entsoe", "label": "ENTSO-E · preços de energia", "configured": bool(os.getenv("ENTSOE_API_TOKEN"))},
        {"name": "resend", "label": "Resend · envio de email", "configured": bool(os.getenv("RESEND_API_KEY"))},

        # --- mapas por sistema ---
        # Aqui reporta-se a presença do MAPA, não das chaves que ele nomeia:
        # VOLT_SYSTEM_STRIPE guarda nomes de env vars e é o
        # stripe_config.resolve_stripe_key_env_var() que resolve cada uma em runtime.
        # Sem o mapa nada resolve; com ele, uma entrada pode na mesma apontar para uma
        # variável que não existe.
        {"name": "stripe", "label": "Stripe · mapa por sistema", "configured": bool(os.getenv("VOLT_SYSTEM_STRIPE"))},
        {"name": "system_repos", "label": "Mapa de repositórios", "configured": bool(os.getenv("VOLT_SYSTEM_REPOS"))},
        {
            "name": "system_railway",
            "label": "Mapa de serviços Railway",
            "configured": bool(os.getenv("VOLT_SYSTEM_RAILWAY")),
        },
    ]
