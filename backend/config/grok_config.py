"""
Grok AI Configuration for AI Mentor feature.
API key loaded from environment variables (GitHub Actions secrets).
"""

import os
from functools import lru_cache
from pathlib import Path


@lru_cache(maxsize=1)
def get_static_skill_text() -> str:
    """Load the mentor skill once and reuse it for every request."""
    skill_path = Path(__file__).with_name("mentor_skill.txt")
    try:
        return skill_path.read_text(encoding="utf-8").strip()
    except OSError:
        return (
            "You are Sarah, the AlphaSync AI Mentor. Help only with AlphaSync usage, "
            "Indian market learning, and safe trading practices."
        )


class GrokConfig:
    """Grok AI API configuration."""

    # Provider defaults
    XAI_API_URL: str = "https://api.x.ai/v1/chat/completions"
    GROQ_API_URL: str = "https://api.groq.com/openai/v1/chat/completions"
    XAI_DEFAULT_MODEL: str = "grok-3-mini"
    GROQ_DEFAULT_MODEL: str = "llama-3.3-70b-versatile"
    DEFAULT_PROVIDER: str = (
        os.getenv("MENTOR_AI_PROVIDER", "auto").strip().lower() or "auto"
    )
    # Backward-compat constants
    API_URL: str = os.getenv("GROK_API_URL", XAI_API_URL)
    DEFAULT_MODEL: str = XAI_DEFAULT_MODEL
    # Legacy attribute retained for compatibility with existing imports.
    MODEL: str = os.getenv("GROK_MODEL", "") or os.getenv(
        "GROQ_MODEL", GROQ_DEFAULT_MODEL
    )

    # Mentor system prompt
    MENTOR_SYSTEM_PROMPT: str = """You are Sarah, the official AI Mentor for AlphaSync.

STRICT MISSION (NON-NEGOTIABLE):
You can teach ONLY:
1) AlphaSync app usage and feature navigation
2) Indian stock market learning (NSE/BSE context)

You must refuse everything else.

STRICT ALLOWED TOPICS:
- AlphaSync sections, workflows, button paths, and route guidance
- Indian market basics: NSE, BSE, NIFTY 50, SENSEX, delivery/intraday, MIS/CNC (high level)
- Safe trading habits: stop-loss, position sizing, max daily loss, discipline

STRICTLY FORBIDDEN TOPICS:
- Any non-Indian-market content (US stocks, international markets, forex, crypto-only calls)
- Any unrelated domains (coding, entertainment, politics, religion, medicine, legal, etc.)
- AlphaSync source code, backend/internal architecture, databases, APIs, tokens, secrets, credentials
- Any personal/private AlphaSync user data (phone, email, KYC, account identifiers, balances of specific users)

ALPHASYNC KNOWLEDGE POLICY:
- You should behave as a complete product mentor for public AlphaSync usage.
- You must not invent hidden features.
- If a feature/path is uncertain, clearly say it may vary by app version and offer the closest verified route.

NAVIGATION ASSISTANT MODE (MANDATORY):
When user asks where/how to do something in AlphaSync:
1) Always start with EXACT route format:
     Route: Sidebar → Section → Tab/Panel → Action
2) Then give 2-5 short steps.
3) If two valid paths exist, show both.

KNOWN ROUTE EXAMPLES:
- Add or reset capital:
    Route: Sidebar → Settings → Trading → Capital Management → Add Capital / Reset Capital
- Reset account:
    Route: Sidebar → Settings → Trading → Account Reset → Reset Account
- View holdings/P&L:
    Route: Sidebar → Portfolio
- Check orders:
    Route: Sidebar → Orders
- Open market watch:
    Route: Sidebar → Market
- Ask AI Mentor:
    Route: Sidebar → AI Mentor

REFUSAL STYLE:
If request is out of scope or sensitive, reply briefly:
"I can only help with AlphaSync feature usage and Indian stock market learning. I can’t assist with that request."
Then offer one relevant AlphaSync/Indian-market alternative.

RESPONSE STYLE:
- Simple Indian-English, beginner-friendly, concise
- Short bullets/steps preferred
- INR examples when useful
- No profit guarantees
"""

    # Override legacy inline prompt with the cached static skill file.
    MENTOR_SYSTEM_PROMPT: str = get_static_skill_text()
    FINAL_INSTRUCTION: str = (
        "Answer concisely. Reference the user_context where relevant. Adapt tone using Mindset rules. "
        "If you cannot answer, refuse and offer the nearest in-scope alternative."
    )

    # API parameters
    MAX_TOKENS: int = 900
    TEMPERATURE: float = 0.7
    TOP_P: float = 0.95

    @classmethod
    def get_api_key(cls) -> str:
        """Read API key from env at runtime (supports both key names)."""
        return (
            os.getenv("GROK_API_KEY", "").strip()
            or os.getenv("GROK_API", "").strip()
            or os.getenv("GROQ_API_KEY", "").strip()
            or os.getenv("XAI_API_KEY", "").strip()
        )

    @classmethod
    def get_provider(cls, api_key: str = "") -> str:
        """Resolve active provider: groq or xai."""
        forced = cls.DEFAULT_PROVIDER
        if forced in {"groq", "xai"}:
            return forced

        key = (api_key or cls.get_api_key() or "").strip().lower()
        if key.startswith("gsk_"):
            return "groq"
        return "xai"

    @classmethod
    def get_api_url(cls, api_key: str = "") -> str:
        """Resolve provider API URL (override-aware)."""
        explicit = (
            os.getenv("MENTOR_AI_API_URL", "").strip()
            or os.getenv("GROK_API_URL", "").strip()
        )
        if explicit:
            return explicit
        provider = cls.get_provider(api_key)
        return cls.GROQ_API_URL if provider == "groq" else cls.XAI_API_URL

    @classmethod
    def is_configured(cls) -> bool:
        """Check if Grok API is properly configured."""
        return bool(cls.get_api_key())

    @classmethod
    def get_model(cls, api_key: str = "") -> str:
        """Resolve the best model for the selected provider."""
        provider = cls.get_provider(api_key)
        configured = (
            os.getenv("GROK_MODEL", "").strip() or os.getenv("GROQ_MODEL", "").strip()
        )
        if configured:
            lowered = configured.lower()
            if provider == "xai":
                # Guard against Groq model names when xAI endpoint is selected.
                if any(
                    token in lowered
                    for token in ["llama", "mixtral", "gemma", "versatile"]
                ):
                    return cls.XAI_DEFAULT_MODEL
            if provider == "groq" and lowered.startswith("grok"):
                return cls.GROQ_DEFAULT_MODEL
            return configured

        return cls.GROQ_DEFAULT_MODEL if provider == "groq" else cls.XAI_DEFAULT_MODEL

    @classmethod
    def validate(cls) -> tuple[bool, str]:
        """Validate configuration."""
        if not cls.get_api_key():
            return (
                False,
                "AI Mentor provider is not configured.",
            )
        return True, "AI Mentor provider configured"


# Export config instance
grok_config = GrokConfig()
