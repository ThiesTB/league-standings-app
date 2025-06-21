
import pandas as pd
import os
import streamlit as st

class LeagueManager:
    def __init__(self, league_file='league_standings.csv'):
        self.league_file = league_file
        if os.path.exists(self.league_file):
            self.league = pd.read_csv(self.league_file)
        else:
            self.league = pd.DataFrame(columns=['NormalizedUID', 'TeamPlayers1Name', 'TeamPlayers1DisplayName', 'Points'])

    def _create_uid(self, row):
        name = row['TeamPlayers1Name']
        asmo_id = row['TeamPlayers1AsmoConnectId']
        return f"{name}__{asmo_id}" if pd.notna(asmo_id) else name

    def _normalize_ids(self, df):
        df['PlayerUID'] = df.apply(self._create_uid, axis=1)

        name_to_uids = {}
        for _, row in df.iterrows():
            name = row['TeamPlayers1Name']
            uid = row['PlayerUID']
            if name not in name_to_uids:
                name_to_uids[name] = set()
            name_to_uids[name].add(uid)

        uid_mapping = {}
        for name, uids in name_to_uids.items():
            with_asmo = [u for u in uids if '__' in u]
            without_asmo = [u for u in uids if '__' not in u]
            if with_asmo and without_asmo:
                for wo in without_asmo:
                    uid_mapping[wo] = with_asmo[0]

        df['NormalizedUID'] = df['PlayerUID'].replace(uid_mapping)
        return df

    def add_tournament_results(self, df):
        df = self._normalize_ids(df)

        relevant_cols = ['NormalizedUID', 'TeamPlayers1Name', 'TeamPlayers1DisplayName', 'Points']
        df = df[relevant_cols]
        df['Points'] = pd.to_numeric(df['Points'], errors='coerce').fillna(0)

        combined = pd.concat([self.league, df])
        self.league = (
            combined.groupby(['NormalizedUID', 'TeamPlayers1Name', 'TeamPlayers1DisplayName'], as_index=False)
            .agg({'Points': 'sum'})
        )

        self.league.to_csv(self.league_file, index=False)

    def get_standings(self):
        standings = self.league.copy()
        standings['LeagueRank'] = standings['Points'].rank(method='min', ascending=False).astype(int)
        return standings.sort_values(by='Points', ascending=False).reset_index(drop=True)

# Streamlit UI
st.title("League Standings Manager")

uploaded_file = st.file_uploader("Upload Tournament Results CSV", type=["csv"])

if uploaded_file:
    df = pd.read_csv(uploaded_file)
    manager = LeagueManager()
    manager.add_tournament_results(df)
    standings = manager.get_standings()

    st.success("Tournament results added to league.")
    st.dataframe(standings)
