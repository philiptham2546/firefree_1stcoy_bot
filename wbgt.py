import re
from datetime import datetime
import requests
from bs4 import BeautifulSoup
import json
import re

CHANNELS = {"wbgt": "https://t.me/s/armynaws", "cat": "https://t.me/s/ArmyCAT1_v2"}


# FOR WBGT AND CAT
def get_latest_message(channel):
    url = channel

    html = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}).text

    soup = BeautifulSoup(html, "html.parser")

    # Get all messages
    messages = soup.select(".tgme_widget_message_text")

    # Latest message
    latest_message = messages[-1].get_text("\n", strip=True)
    return latest_message


def extract_wbgt(text: str, camp: str = "Sungei Gedong Camp") -> dict | None:
    # Extract update timestamp
    header_match = re.search(
        r"WBGT Update\s*-\s*(\d{2}\s+[A-Za-z]{3}\s+\d{4}\s+\d{4})hrs",
        text,
    )

    update_time = header_match.group(1) if header_match else None

    # Extract the camp's WBGT
    camp_pattern = re.compile(
        rf"•\s*{re.escape(camp)},\s*(\d+(?:\.\d+)?)℃",
        flags=re.IGNORECASE,
    )

    camp_match = camp_pattern.search(text)

    if not camp_match:
        return None

    # Find the most recent colour heading before the camp
    preceding_text = text[: camp_match.start()]

    headings = re.findall(
        r"^(CUTOFF|BLACK|RED|YELLOW|GREEN|WHITE)\s+---",
        preceding_text,
        flags=re.MULTILINE,
    )

    return {
        "camp": camp,
        "wbgt": float(camp_match.group(1)),
        "category": headings[-1] if headings else None,
        "updated_at": update_time,
    }


def get_cat_status(message: str, target_sector: str = "3N") -> dict:
    target_sector = target_sector.upper().strip()

    # Special case: All sectors clear
    m = re.search(
        r"All\s+Sectors\s+Clear\s*\((\d{4})-(\d{4})\)",
        message,
        re.IGNORECASE,
    )
    if m:
        return {
            "sector": target_sector,
            "status": "CAT 3",
            "start": m.group(1),
            "end": m.group(2),
        }

    # CAT 1 / CAT 2 sections
    section_pattern = re.compile(
        r"CAT\s*([12])\s*:\s*(.*?)(?=CAT\s*[12]\s*:|\Z)",
        re.IGNORECASE | re.DOTALL,
    )

    block_pattern = re.compile(r"\((\d{4})-(\d{4})\)\s*\n+([A-Za-z0-9,\s]+)")

    for cat, section in section_pattern.findall(message):
        for start, end, raw_sectors in block_pattern.findall(section):
            sectors = {s.strip().upper() for s in raw_sectors.split(",") if s.strip()}

            # Exact match (3N != 13N)
            if target_sector in sectors:
                return {
                    "sector": target_sector,
                    "status": f"CAT {cat}",
                    "start": start,
                    "end": end,
                }

    # Sector wasn't mentioned, so it's CAT 3.
    return {
        "sector": target_sector,
        "status": "CAT 3",
        "start": None,
        "end": None,
    }


# FOR PSI
def get_psi_north():
    resp = requests.get("https://api-open.data.gov.sg/v2/real-time/api/psi")
    resp_clean = json.loads(resp.text)
    psi = resp_clean["data"]["items"][0]["readings"]["psi_twenty_four_hourly"]["north"]
    time = resp_clean["data"]["items"][0]["timestamp"]
    return "North", time, psi


def get_info(camp: str = "Sungei Gedong Camp", sector: str = "3N"):
    info = {}
    for k, v in CHANNELS.items():
        temp = get_latest_message(v)
        info[k] = (
            extract_wbgt(temp, camp=camp)
            if k == "wbgt"
            else get_cat_status(temp, target_sector=sector)
        )
    info["psi"] = get_psi_north()
    return info


if __name__ == "__main__":
    result = get_info()
    print(result)
