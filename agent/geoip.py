"""GeoIP — resolve IP to province/city code.

Priority: local GeoLite2-City.mmdb > ipapi.co API > empty.
"""
import asyncio
import time
import httpx
from pathlib import Path

# ── Province code map (ISO 3166-2 region_code → abbreviation) ──
PROVINCE_MAP: dict[str, str] = {
    "BJ": "BJ", "SH": "SH", "TJ": "TJ", "CQ": "CQ",
    "GD": "GD", "ZJ": "ZJ", "JS": "JS", "SC": "SC", "HB": "HB", "HN": "HN",
    "SD": "SD", "FJ": "FJ", "AH": "AH", "JX": "JX", "HA": "HA",
    "HE": "HE", "HL": "HL", "JL": "JL", "LN": "LN", "SX": "SX", "SN": "SN",
    "GS": "GS", "QH": "QH", "YN": "YN", "GZ": "GZ", "HI": "HI",
    "TW": "TW", "HK": "HK", "MO": "MO", "NM": "NM", "NX": "NX",
    "XJ": "XJ", "XZ": "XZ", "GX": "GX",
}

# ── Cache ──
_cache: dict[str, tuple[tuple[str, str], float]] = {}  # ip → ((province, city), expire_ts)


async def lookup(ip: str) -> tuple[str, str]:
    """Return (province_code, city) or ("", "") on failure. Results cached 1h."""
    now = time.time()
    if ip in _cache and _cache[ip][1] > now:
        return _cache[ip][0]

    result = await _from_geolite2(ip) or await _from_ipapi(ip) or ("", "")
    _cache[ip] = (result, now + 3600)
    return result


async def _from_geolite2(ip: str) -> tuple[str, str] | None:
    """Try local GeoLite2-City.mmdb. Returns None if db missing."""
    db_path = Path(__file__).parent.parent / "data" / "GeoLite2-City.mmdb"
    if not db_path.exists():
        return None
    try:
        import geoip2.database
        def _query():
            with geoip2.database.Reader(str(db_path)) as reader:
                resp = reader.city(ip)
                province = PROVINCE_MAP.get(
                    (resp.subdivisions.most_specific.iso_code or "").upper(), ""
                )
                city = resp.city.name or ""
                return (province, city)
        return await asyncio.to_thread(_query)
    except Exception:
        return None


async def _from_ipapi(ip: str) -> tuple[str, str] | None:
    """Try ipapi.co free API. 1000 req/day, no key."""
    try:
        async with httpx.AsyncClient() as client:
            r = await client.get(f"https://ipapi.co/{ip}/json/", timeout=3)
            if r.status_code != 200:
                return None
            data = r.json()
        province = PROVINCE_MAP.get(data.get("region_code", "").upper(), "")
        city = data.get("city", "")
        return (province, city) if province else None
    except Exception:
        return None
