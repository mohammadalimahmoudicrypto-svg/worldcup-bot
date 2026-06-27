import httpx
from datetime import datetime, timedelta, timezone

BASE_URL = "https://api.football-data.org/v4"


def _headers(api_key: str) -> dict:
    return {"X-Auth-Token": api_key}


def team_name(team: dict) -> str:
    return team.get("shortName") or team.get("name") or "TBD"


def parse_utc(date_str: str) -> datetime:
    return datetime.fromisoformat(date_str.replace("Z", "+00:00")).astimezone(timezone.utc)


async def fetch_scheduled(api_key: str, competition: str) -> list[dict]:
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{BASE_URL}/competitions/{competition}/matches",
            headers=_headers(api_key),
            params={"status": "SCHEDULED,TIMED"},
            timeout=15.0,
        )
        resp.raise_for_status()
        return resp.json().get("matches", [])


async def fetch_recent_finished(api_key: str, competition: str, days_back: int = 7) -> list[dict]:
    now = datetime.now(timezone.utc)
    date_from = (now - timedelta(days=days_back)).strftime("%Y-%m-%d")
    date_to = (now + timedelta(days=1)).strftime("%Y-%m-%d")

    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{BASE_URL}/competitions/{competition}/matches",
            headers=_headers(api_key),
            params={"status": "FINISHED", "dateFrom": date_from, "dateTo": date_to},
            timeout=15.0,
        )
        resp.raise_for_status()
        return resp.json().get("matches", [])
