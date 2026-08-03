import gspread
import pandas as pd
import timetree_exporter
from google.oauth2.service_account import Credentials
import re
from datetime import datetime, date
import pandas as pd
from datetime import date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo
from icalendar import Calendar
import os
import subprocess
from pathlib import Path
import pprint

ICS_DIR = Path("ics_files")
CALENDARS = {
    "W3Ci1sHVqQ66": ICS_DIR / "output_ltw.ics",  # Lead The Way
    "YEW4rxEepkju": ICS_DIR / "output_men.ics",  # O/L/MA 1ST COY
}
STATUS_RE = re.compile(r"(?P<start>\d{6})\s*-\s*(?P<end>\d{6})")
RN_COLS = "B4:C61"
RSI_COLS = "D4:N61"
RSO_COLS = "P4:T61"

### HELPERS FOR STATUS EXTRACTION


def parse_ddmmyy(s: str) -> date:
    return datetime.strptime(s, "%d%m%y").date()


def is_active(cell, on: date) -> bool:
    if pd.isna(cell) or not str(cell).strip():
        return False
    m = STATUS_RE.search(str(cell))
    if not m:
        return False
    start = parse_ddmmyy(m.group("start"))
    end = parse_ddmmyy(m.group("end"))
    return start <= on <= end


def load_sheet(ws_name="HR"):
    SHEET_KEY = "1ZpPqkYcje4nB335yzqauN55nbjX_oO3TtLGGcnk0hcw"

    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]
    creds = Credentials.from_service_account_file("credentials.json", scopes=scopes)
    client = gspread.authorize(creds)
    sh = client.open_by_key(SHEET_KEY)
    temp = [ws.title for ws in list(sh.worksheets())]
    if ws_name not in temp:
        return False, f"NO WS FOUND. WS TITLES ARE {temp}"
    return True, sh.worksheet(ws_name)


def extract_rel_entries(sheet):
    ranges_data = sheet.batch_get([RN_COLS, RSO_COLS, RSI_COLS])
    rso_df = pd.concat(
        [pd.DataFrame(ranges_data[0]), pd.DataFrame(ranges_data[1])], axis=1
    )
    rsi_df = pd.concat(
        [pd.DataFrame(ranges_data[0]), pd.DataFrame(ranges_data[2])], axis=1
    )
    return rso_df, rsi_df


def clean_up(df):
    """Makes first row cols the col name, removes col row and first example, separate"""
    df.columns = df.iloc[0]
    clean_df = df.drop([0, 1])
    return clean_df


def get_active_status(df, on: date):
    status_cols = [col for col in df.columns if col not in ["RANK", "NAME"]]

    active = (
        df.assign(_id=df.index)
        .melt(
            id_vars=["_id", "RANK", "NAME"],
            value_vars=status_cols,
            var_name="col",
            value_name="status",
        )
        .loc[lambda d: d["status"].map(lambda x: is_active(x, on))]
    )

    # one row per person with all active statuses that day
    active_by_person = (
        active.groupby(["_id", "RANK", "NAME"])["status"]
        .apply(list)
        .reset_index(name="active_statuses")
    )
    return active_by_person


### HELPERS FOR TIMETREE MONITORING


def export_timetree_calendars():
    ICS_DIR.mkdir(exist_ok=True)
    for code, out_path in CALENDARS.items():
        subprocess.run(
            [
                "timetree-exporter",
                "-o",
                str(out_path),
                "-c",
                code,
            ],
            check=True,
            env=os.environ.copy(),  # needs TIMETREE_EMAIL + TIMETREE_PASSWORD
        )
        print(f"Exported {code} → {out_path}")


def event_occurs_on(component, day: date) -> bool:
    """True if the VEVENT overlaps `day` (local calendar date)."""
    start = component.decoded("dtstart")
    end = component.decoded("dtend")

    # All-day: DATE values; DTEND is exclusive in ICS
    if isinstance(start, date) and not isinstance(start, datetime):
        return start <= day < end

    # Timed: use the event's own timezone (or UTC if none)
    tz = start.tzinfo or ZoneInfo("UTC")
    day_start = datetime.combine(day, time.min, tzinfo=tz)
    day_end = day_start + timedelta(days=1)
    return start < day_end and end > day_start


# def filter_timetree(input):
# cal = Calendar.from_ical(input.read_bytes())
# filtered = Calendar()
# kept = []
# used_tzids = set()
# for component in cal.walk():
#     if component.name != "VEVENT":
#         continue
#     if event_occurs_on(component, TODAY):
#         kept.append(component)
#         dtstart = component.get("dtstart")
#         if dtstart is not None and "TZID" in dtstart.params:
#             used_tzids.add(dtstart.params["TZID"])

# for component in cal.walk():
#     if component.name == "VTIMEZONE" and str(component.get("tzid")) in used_tzids:
#         filtered.add_component(component)

# for event in kept:
#     filtered.add_component(event)

# for e in kept:
#     print("-", e.get("summary"), "|", e.get("dtstart"), "→", e.get("dtend"))


def filter_timetree(input_path, on: date):
    cal = Calendar.from_ical(input_path.read_bytes())
    events = []
    for component in cal.walk():
        if component.name != "VEVENT":
            continue
        if event_occurs_on(component, on):
            events.append(
                {
                    "summary": str(component.get("summary")),
                    "start": str(component.get("dtstart")),
                    "end": str(component.get("dtend")),
                }
            )
    return events


### MAIN FUNCTIONS


def status_monitoring(on: date | None = None):
    on = on or date.today()
    success, temp = load_sheet()
    if not success:
        return temp
    rso_df, rsi_df = extract_rel_entries(temp)
    clean_rso_df = clean_up(rso_df)
    clean_rsi_df = clean_up(rsi_df)
    rso_active_status, rsi_active_status = (
        get_active_status(clean_rso_df, on),
        get_active_status(clean_rsi_df, on),
    )
    rso_active_status.drop("_id", axis=1, inplace=True)
    rsi_active_status.drop("_id", axis=1, inplace=True)
    return rso_active_status, rsi_active_status


def timetree_monitoring(on: date | None = None):
    on = on or date.today()
    export_timetree_calendars()
    all_events = []
    for input_path in CALENDARS.values():
        events = filter_timetree(input_path, on)
        all_events.append((input_path, events))
    return all_events


def main():
    on = date.today()
    all_events = timetree_monitoring(on)
    rso_active, rsi_active = status_monitoring(on)
    rso = rso_active.to_dict(orient="records")
    rsi = rsi_active.to_dict(orient="records")
    summary = f"RSO: {rso}\n\nRSI: {rsi}\n\nTimetree events: {all_events}"
    pprint.pprint(summary, indent=2)


if __name__ == "__main__":
    main()
