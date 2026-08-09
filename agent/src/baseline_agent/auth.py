import hmac
import os

from langgraph_sdk import Auth


auth = Auth()


@auth.authenticate
async def authenticate(authorization: str | None) -> Auth.types.MinimalUserDict:
    expected = f"Bearer {os.environ['SPRING_TO_AGENT_TOKEN']}"
    if authorization is None or not hmac.compare_digest(authorization, expected):
        raise Auth.exceptions.HTTPException(status_code=401, detail="invalid service identity")
    return {"identity": "spring-backend", "is_authenticated": True}

