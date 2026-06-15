"""GeoIP — resolve IP to province/city code.

Priority: GeoLite2-City.mmdb > ip-api.com (free, HTTP) >
         ipapi.co > server self-locate (private IP only) > empty.
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

# ── English region name → province code (ip-api.com returns English names) ──
REGION_EN_TO_CODE: dict[str, str] = {
    "Beijing": "BJ", "Shanghai": "SH", "Tianjin": "TJ", "Chongqing": "CQ",
    "Guangdong": "GD", "Zhejiang": "ZJ", "Jiangsu": "JS",
    "Sichuan": "SC", "Hubei": "HB", "Hunan": "HN",
    "Shandong": "SD", "Fujian": "FJ", "Anhui": "AH",
    "Jiangxi": "JX", "Henan": "HA",
    "Hebei": "HE", "Shanxi": "SX", "Shaanxi": "SN",
    "Gansu": "GS", "Qinghai": "QH",
    "Yunnan": "YN", "Guizhou": "GZ", "Hainan": "HI",
    "Liaoning": "LN", "Jilin": "JL", "Heilongjiang": "HL",
    "Guangxi": "GX", "Inner Mongolia": "NM", "Ningxia": "NX",
    "Xinjiang": "XJ", "Tibet": "XZ",
    "Taiwan": "TW", "Hong Kong": "HK", "Macau": "MO",
}

# ── City code map (full Chinese name → abbreviation) ──
CITY_CODE: dict[str, str] = {
    "北京": "BJ", "上海": "SH", "天津": "TJ", "重庆": "CQ",
    "深圳": "SZ", "广州": "GZ", "东莞": "DG", "佛山": "FS",
    "珠海": "ZH", "惠州": "HZ", "中山": "ZS", "汕头": "ST",
    "杭州": "HZ", "宁波": "NB", "温州": "WZ", "嘉兴": "JX",
    "湖州": "HU", "绍兴": "SX", "金华": "JH",
    "南京": "NJ", "苏州": "SZ2", "无锡": "WX", "常州": "CZ",
    "南通": "NT", "徐州": "XZ", "扬州": "YZ",
    "成都": "CD", "绵阳": "MY", "德阳": "DY", "宜宾": "YB", "南充": "NC",
    "武汉": "WH", "宜昌": "YC", "襄阳": "XY", "荆州": "JZ", "黄石": "HS",
    "长沙": "CS", "株洲": "ZZ", "湘潭": "XT", "衡阳": "HY", "岳阳": "YY",
    "济南": "JN", "青岛": "QD", "烟台": "YT", "潍坊": "WF",
    "临沂": "LY", "淄博": "ZB",
    "福州": "FZ", "厦门": "XM", "泉州": "QZ", "漳州": "ZZ2", "莆田": "PT",
    "合肥": "HF", "芜湖": "WH2", "蚌埠": "BB", "马鞍山": "MAS", "安庆": "AQ",
    "南昌": "NC2", "九江": "JJ", "赣州": "GZ2", "景德镇": "JDZ",
    "郑州": "ZZ3", "洛阳": "LY2", "开封": "KF", "南阳": "NY", "新乡": "XX",
    "沈阳": "SY", "大连": "DL", "鞍山": "AS", "抚顺": "FS2",
    "长春": "CC", "吉林": "JL2", "四平": "SP",
    "哈尔滨": "HEB", "齐齐哈尔": "QQHE", "大庆": "DQ",
    "西安": "XA", "咸阳": "XY2", "宝鸡": "BJ2",
    "兰州": "LZ", "天水": "TS",
    "昆明": "KM", "大理": "DL2", "丽江": "LJ",
    "贵阳": "GY", "遵义": "ZY",
    "海口": "HK2", "三亚": "SY2",
    "南宁": "NN", "桂林": "GL", "柳州": "LZ2",
    "呼和浩特": "HHHT", "包头": "BT",
    "乌鲁木齐": "WLMQ",
    "拉萨": "LS",
    "台北": "TB", "高雄": "GX2", "台中": "TZ",
    "香港": "XG", "澳门": "AM",
    "石家庄": "SJZ", "太原": "TY", "大同": "DT",
    "唐山": "TS2", "邯郸": "HD", "保定": "BD",
    "西宁": "XN", "银川": "YC2",
    "连云港": "LYG", "镇江": "ZJ2", "台州": "TZ2",
    "舟山": "ZS2", "丽水": "LS2", "衢州": "QZ2",
}


def city_abbr(full_name: str) -> str:
    """Return city abbreviation from full Chinese name. Falls back to first 2 chars."""
    return CITY_CODE.get(full_name, full_name[:2])

# ── Cache ──
_cache: dict[str, tuple[tuple[str, str], float]] = {}  # ip → ((province, city), expire_ts)


async def lookup(ip: str) -> tuple[str, str]:
    """Return (province_code, city) or ("", "") on failure. Results cached 1h.

    For LAN/private IPs, falls back to the server's own public-IP geolocation —
    in on-premises deployments, the server's location is the user's location.
    """
    now = time.time()
    if ip in _cache and _cache[ip][1] > now:
        return _cache[ip][0]

    result = (
        await _from_geolite2(ip)
        or await _from_ipapicom(ip)
        or await _from_ipapi(ip)
    )
    if (not result or not result[0]) and _is_private(ip):
        result = await _server_self_locate() or ("", "")
    if not result:
        result = ("", "")
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


async def _from_ipapicom(ip: str) -> tuple[str, str] | None:
    """Try ip-api.com free HTTP API. 45 req/min, no key.
    
    Returns English region/city names — translated to Chinese via lookup tables.
    """
    try:
        async with httpx.AsyncClient() as client:
            r = await client.get(
                f"http://ip-api.com/json/{ip}",
                params={"fields": "status,countryCode,regionName,city"},
                timeout=5,
            )
            if r.status_code != 200:
                return None
            data = r.json()
        if data.get("status") != "success":
            return None
        if data.get("countryCode") != "CN":
            return None  # non-China IP — can't map province
        province = REGION_EN_TO_CODE.get(data.get("regionName", ""), "")
        city = _translate_city(data.get("city", ""))
        return (province, city) if province else None
    except Exception:
        return None


async def _from_ipapi(ip: str) -> tuple[str, str] | None:
    """Try ipapi.co free API. 1000 req/day, no key."""
    try:
        async with httpx.AsyncClient() as client:
            r = await client.get(f"https://ipapi.co/{ip}/json/", timeout=5)
            if r.status_code != 200:
                return None
            data = r.json()
        # ipapi.co returns error messages in HTML/text when rate-limited
        if "error" in data or not isinstance(data, dict):
            return None
        province = PROVINCE_MAP.get(data.get("region_code", "").upper(), "")
        city = _translate_city(data.get("city", ""))
        return (province, city) if province else None
    except Exception:
        return None


# ── City name translation (both ip-api.com and ipapi.co return English) ──
_CITY_EN2CN: dict[str, str] = {
    "Beijing": "北京", "Shanghai": "上海", "Tianjin": "天津", "Chongqing": "重庆",
    "Guangzhou": "广州", "Shenzhen": "深圳", "Dongguan": "东莞", "Foshan": "佛山",
    "Zhuhai": "珠海", "Huizhou": "惠州", "Zhongshan": "中山", "Shantou": "汕头",
    "Hangzhou": "杭州", "Ningbo": "宁波", "Wenzhou": "温州", "Jiaxing": "嘉兴",
    "Huzhou": "湖州", "Shaoxing": "绍兴", "Jinhua": "金华",
    "Nanjing": "南京", "Suzhou": "苏州", "Wuxi": "无锡", "Changzhou": "常州",
    "Nantong": "南通", "Xuzhou": "徐州", "Yangzhou": "扬州",
    "Chengdu": "成都", "Mianyang": "绵阳", "Deyang": "德阳", "Yibin": "宜宾",
    "Nanchong": "南充",
    "Wuhan": "武汉", "Yichang": "宜昌", "Xiangyang": "襄阳", "Jingzhou": "荆州",
    "Huangshi": "黄石",
    "Changsha": "长沙", "Zhuzhou": "株洲", "Xiangtan": "湘潭",
    "Hengyang": "衡阳", "Yueyang": "岳阳",
    "Jinan": "济南", "Qingdao": "青岛", "Yantai": "烟台", "Weifang": "潍坊",
    "Linyi": "临沂", "Zibo": "淄博",
    "Fuzhou": "福州", "Xiamen": "厦门", "Quanzhou": "泉州", "Zhangzhou": "漳州",
    "Putian": "莆田",
    "Hefei": "合肥", "Wuhu": "芜湖", "Bengbu": "蚌埠",
    "Maanshan": "马鞍山", "Anqing": "安庆",
    "Nanchang": "南昌", "Jiujiang": "九江", "Ganzhou": "赣州",
    "Jingdezhen": "景德镇",
    "Zhengzhou": "郑州", "Luoyang": "洛阳", "Kaifeng": "开封",
    "Nanyang": "南阳", "Xinxiang": "新乡",
    "Shenyang": "沈阳", "Dalian": "大连", "Anshan": "鞍山", "Fushun": "抚顺",
    "Changchun": "长春", "Jilin": "吉林", "Siping": "四平",
    "Harbin": "哈尔滨", "Qiqihar": "齐齐哈尔", "Daqing": "大庆",
    "Xian": "西安", "Xianyang": "咸阳", "Baoji": "宝鸡",
    "Lanzhou": "兰州", "Tianshui": "天水",
    "Kunming": "昆明", "Dali": "大理", "Lijiang": "丽江",
    "Guiyang": "贵阳", "Zunyi": "遵义",
    "Haikou": "海口", "Sanya": "三亚",
    "Nanning": "南宁", "Guilin": "桂林", "Liuzhou": "柳州",
    "Hohhot": "呼和浩特", "Baotou": "包头",
    "Urumqi": "乌鲁木齐",
    "Lhasa": "拉萨",
    "Taipei": "台北", "Kaohsiung": "高雄", "Taichung": "台中",
    "Hong Kong": "香港", "Macau": "澳门",
    "Shijiazhuang": "石家庄", "Taiyuan": "太原", "Datong": "大同",
    "Tangshan": "唐山", "Handan": "邯郸", "Baoding": "保定",
    "Xining": "西宁", "Yinchuan": "银川",
    "Lianyungang": "连云港", "Zhenjiang": "镇江", "Taizhou": "台州",
    "Zhoushan": "舟山", "Lishui": "丽水",
    "Quzhou": "衢州",
}


def _translate_city(raw: str) -> str:
    """Translate ipapi.co English city name to Chinese; pass through if unknown."""
    return _CITY_EN2CN.get(raw, raw)


import ipaddress

_PRIVATE_NETS = [
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("127.0.0.0/8"),
]

_SERVER_LOCATION: tuple[str, str] | None = None


def _is_private(ip: str) -> bool:
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return True  # malformed → treat as private, use server fallback
    return any(addr in net for net in _PRIVATE_NETS)


async def _server_self_locate() -> tuple[str, str] | None:
    """Geolocate the server's own public IP via ip-api.com. Cached forever."""
    global _SERVER_LOCATION
    if _SERVER_LOCATION is not None:
        return _SERVER_LOCATION
    # Try ip-api.com first (free), then ipapi.co
    for fetcher in (_from_ipapicom_self, _from_ipapi_self):
        result = await fetcher()
        if result and result[0]:
            _SERVER_LOCATION = result
            return _SERVER_LOCATION
    _SERVER_LOCATION = ("", "")  # mark as failed — don't retry
    return None


async def _from_ipapicom_self() -> tuple[str, str] | None:
    """Self-locate via ip-api.com (call with no IP → uses caller's address)."""
    try:
        async with httpx.AsyncClient() as client:
            r = await client.get(
                "http://ip-api.com/json/",
                params={"fields": "status,countryCode,regionName,city"},
                timeout=5,
            )
            if r.status_code != 200:
                return None
            data = r.json()
        if data.get("status") != "success":
            return None
        if data.get("countryCode") != "CN":
            return None
        province = REGION_EN_TO_CODE.get(data.get("regionName", ""), "")
        city = _translate_city(data.get("city", ""))
        return (province, city) if province else None
    except Exception:
        return None


async def _from_ipapi_self() -> tuple[str, str] | None:
    """Self-locate via ipapi.co."""
    try:
        async with httpx.AsyncClient() as client:
            r = await client.get("https://ipapi.co/json/", timeout=5)
            if r.status_code != 200:
                return None
            data = r.json()
        if "error" in data or not isinstance(data, dict):
            return None
        province = PROVINCE_MAP.get(data.get("region_code", "").upper(), "")
        city = _translate_city(data.get("city", ""))
        return (province, city) if province else None
    except Exception:
        return None
