import pandas as pd
import streamlit as st
import gspread
from gspread_dataframe import get_as_dataframe, set_with_dataframe
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime

# ------------------------------------------------------------------
# Google Sheets setup ------------------------------------------------
# ------------------------------------------------------------------
SHEET_NAME = "league-standings"          # Google Sheet workbook title
CREDENTIALS_FILE = "league-standings-credentials.json"  # service-account JSON (must be in repo)

scope = [
    "https://spreadsheets.google.com/feeds",
    "https://www.googleapis.com/auth/drive",
]
credentials = ServiceAccountCredentials.from_json_keyfile_name(CREDENTIALS_FILE, scope)
gc = gspread.authorize(credentials)
workbook = gc.open(SHEET_NAME)

# ------------------------------------------------------------------
# Helpers -----------------------------------------------------------
# ------------------------------------------------------------------

def ensure_sheet(title, columns):
    """Return a worksheet with given columns; create if missing."""
    try:
        ws = workbook.worksheet(title)
    except gspread.WorksheetNotFound:
        ws = workbook.add_worksheet(title=title, rows=1000, cols=len(columns) + 5)
        ws.append_row(columns)  # header
    return ws

# master sheets
leagues_ws = ensure_sheet("leagues", ["League"])
results_ws = ensure_sheet("raw_results", [
    "League", "Tournament", "Date", "NormalizedUID", "TeamPlayers1Name",
    "TeamPlayers1Username", "TeamPlayers1AsmoConnectId", "Points", "Rank"
])

# ------------------------------------------------------------------
# UID normalisation -------------------------------------------------
# ------------------------------------------------------------------

def create_uid(row):
    name = row["TeamPlayers1Name"]
    asmo = row["TeamPlayers1AsmoConnectId"]
    return f"{name}__{asmo}" if pd.notna(asmo) and str(asmo).strip() != "" else name


def normalize_ids(df):
    """Apply UID logic & map no-Asmo rows to Asmo rows when name matches."""
    df["PlayerUID"] = df.apply(create_uid, axis=1)

    # build mapping name -> list of uids
    mapping = {}
    for name, grp in df.groupby("TeamPlayers1Name"):
        uids = grp["PlayerUID"].unique().tolist()
        with_asmo = [u for u in uids if "__" in u]
        without_asmo = [u for u in uids if "__" not in u]
        if with_asmo and without_asmo:
            for wo in without_asmo:
                mapping[wo] = with_asmo[0]

    df["NormalizedUID"] = df["PlayerUID"].replace(mapping)
    return df

# ------------------------------------------------------------------
# League utilities --------------------------------------------------
# ------------------------------------------------------------------

def get_league_list():
    data = leagues_ws.col_values(1)[1:]  # skip header
    return sorted(list({l.strip() for l in data if l.strip()}))


def add_league(name):
    name = name.strip()
    if name == "":
        return False
    existing = get_league_list()
    if name in existing:
        return False
    leagues_ws.append_row([name])
    return True


def append_results(df, league, tourney_name, tourney_date):
    df = normalize_ids(df)
    df = df[[
        "NormalizedUID",
        "TeamPlayers1Name",
        "TeamPlayers1Username",
        "TeamPlayers1AsmoConnectId",
        "Points",
        "Rank",
    ]].copy()
    df["League"] = league
    df["Tournament"] = tourney_name
    df["Date"] = tourney_date
    # reorder to match sheet header
    df = df[[
        "League", "Tournament", "Date", "NormalizedUID", "TeamPlayers1Name",
        "TeamPlayers1Username", "TeamPlayers1AsmoConnectId", "Points", "Rank"
    ]]
    set_with_dataframe(results_ws, get_as_dataframe(results_ws).append(df, ignore_index=True), include_index=False, include_column_header=True, resize=True)


def load_results_for_league(league):
    df = get_as_dataframe(results_ws)
    if df.empty:
        return df
    df = df.dropna(subset=["League"]).fillna("")
    df = df[df["League"] == league]
    # ensure numeric Points
    df["Points"] = pd.to_numeric(df["Points"], errors="coerce").fillna(0)
    return df


def compute_standings(df):
    if df.empty:
        return pd.DataFrame(columns=["Player", "Total Points", "Rank"])
    # Participation bonus: +5 per tournament appearance
    participation = df.groupby("NormalizedUID").size().rename("Bonus") * 5
    totals = df.groupby(["NormalizedUID", "TeamPlayers1Name"]).agg({"Points": "sum"})
    totals = totals.join(participation)
    totals["Total Points"] = totals["Points"] + totals["Bonus"]
    standings = (
        totals.reset_index()
        .sort_values("Total Points", ascending=False)
        .reset_index(drop=True)
    )
    standings["Rank"] = standings["Total Points"].rank(method="min", ascending=False).astype(int)
    standings.rename(columns={"TeamPlayers1Name": "Player"}, inplace=True)
    return standings[["Rank", "Player", "Total Points"]]

# ------------------------------------------------------------------
# Streamlit UI ------------------------------------------------------
# ------------------------------------------------------------------
st.set_page_config(page_title="League Standings Manager", layout="wide")

st.sidebar.header("Leagues")
available_leagues = get_league_list()
selected_league = st.sidebar.selectbox("Select league", options=available_leagues)

# Add new league
with st.sidebar.expander("Create new league"):
    new_league_name = st.text_input("League name")
    if st.button("Add league"):
        if add_league(new_league_name):
            st.experimental_rerun()
        else:
            st.warning("League name invalid or already exists.")

st.title("League Standings Manager")

if selected_league:
    st.subheader(f"Current standings – {selected_league}")
    league_df = load_results_for_league(selected_league)
    standings_df = compute_standings(league_df)
    st.dataframe(standings_df, hide_index=True)
else:
    st.info("Please create or select a league in the sidebar.")

st.markdown("---")

st.header("Add tournament results")

uploaded_file = st.file_uploader("Upload Tournament Results CSV", type=["csv"])
col1, col2 = st.columns(2)
with col1:
    tourney_name = st.text_input("Tournament name")
with col2:
    tourney_date = st.date_input("Tournament date", value=datetime.today()).strftime("%Y-%m-%d")

if st.button("Add to league"):
    if not selected_league:
        st.error("Select a league first.")
    elif uploaded_file is None:
        st.error("Please upload a CSV file.")
    elif tourney_name.strip() == "":
        st.error("Enter a tournament name.")
    else:
        df_uploaded = pd.read_csv(uploaded_file)
        append_results(df_uploaded, selected_league, tourney_name.strip(), tourney_date)
        st.success("Results added! Standings updated.")
        st.experimental_rerun()
