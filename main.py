import streamlit as st
import pandas as pd
import requests
import time
import string
from math import radians, sin, cos, sqrt, atan2, nan



def haversine(lat1, lon1, lat2, lon2):
    # Radius of the Earth in kilometers
    R = 6371.0

    # Convert latitude and longitude from degrees to radians
    lat1 = radians(lat1)
    lon1 = radians(lon1)
    lat2 = radians(lat2)
    lon2 = radians(lon2)

    # Difference in coordinates
    dlat = lat2 - lat1
    dlon = lon2 - lon1

    # Haversine formula
    a = sin(dlat / 2)**2 + cos(lat1) * cos(lat2) * sin(dlon / 2)**2
    c = 2 * atan2(sqrt(a), sqrt(1 - a))

    # Distance in kilometers
    distance = R * c
    return distance

def find_nearest_point(train_data, points):
    ref_lat, ref_lon = train_data['latitude'], train_data['longitude']
    min_distance = float('inf')
    
    for index, point in enumerate(points):
        lat, lon = point['stop_lat'], point['stop_lon']
        distance = haversine(ref_lat, ref_lon, lat, lon)
        
        if distance < min_distance:
            min_distance = distance
            nearest_point_index = index
    
    return nearest_point_index

# Set API endpoint
url = 'https://api.mtrec.name.my/api/position?agency=ktmb'

# # Function to fetch trains
dtype_spec = {
    "tripId" : "str",
    "latitude": "int64",
    "longitude": "int64",
    "bearing": "int64",
    "speed": "int64",
    "id": "str",
    "label": "str",
}

if "last_fetch_time" not in st.session_state:
    st.session_state.last_fetch_time = 0

@st.cache_data(ttl=60)
def fetch_trains():
    for _ in range(100):
        if time.time() - st.session_state.last_fetch_time > 60: 
            response = requests.get(url)
            print("Fetching data ...")
            if response.status_code == 200:
                st.session_state.last_fetch_time = time.time()
                json_data = response.json()
                data = pd.DataFrame(json_data['data'])

                # Write the DataFrame to an Excel file
                trip_df = pd.json_normalize(data['trip'])
                position_df = pd.json_normalize(data['position'])
                # timestamp_df = pd.DataFrame.from_dict(data['timestamp'], orient='index', columns=['timestamp'])
                vehicle_df = pd.json_normalize(data['vehicle'])

                # Concatenate all dataframes into one
                df = pd.concat([trip_df, position_df, vehicle_df], axis=1)
                df.astype(dtype_spec)
                print("Done fetching ...")
                return df
            else:
                time.sleep(10.0)
        else:
            print("Reuseing data ...")
            return st.session_state.train_df
    


trips_df = pd.read_csv('static_data/trips.txt')
routes_df = pd.read_csv('static_data/routes.txt')
stops_df = pd.read_csv('static_data/stops.txt')
stop_times_df = pd.read_csv('static_data/stop_times.txt')

routes_trip_df = pd.merge(trips_df, routes_df, how='inner')


# Streamlit app layout

if 'train_df' not in st.session_state:
    st.session_state.train_df = fetch_trains()

if 'active_tab' not in st.session_state:
    st.session_state.active_tab = 'Tab 1'

tab1, tab2 = st.tabs(["Route selection", "Train selection"])


with tab1:
    if st.session_state.active_tab != 'Tab 1':
        st.session_state.active_tab = 'Tab 1'
    st.title("Train Tracker")
    selected_line = st.selectbox("Select a route to track", options=routes_df['route_long_name'])
    direction_options = sorted(selected_line.replace("KTM ", "").replace("Intercity ", "").replace("Electric Train Service", "").split(" - "))
    selected_direction = st.selectbox('Train travel from', options=direction_options)

    routes_trip_df[['start_station', 'end_station']] = routes_trip_df['route_long_name'].str.replace("KTM ", "").str.split(' - ', expand=True)
    swap_condition = routes_trip_df['direction_id'] == 1
    routes_trip_df.loc[swap_condition, ['start_station', 'end_station']] = routes_trip_df.loc[swap_condition, ['end_station', 'start_station']].values
    first_match_trip = routes_trip_df.loc[routes_trip_df['start_station'] == selected_direction].iloc[0]

    train_stop_times = stop_times_df[stop_times_df['trip_id'] == first_match_trip['trip_id']] 
    station_df = pd.merge(train_stop_times, stops_df, on='stop_id', how='inner').copy()
    station_df['relative_distance'] = station_df['shape_dist_traveled'].diff()
    station_df['relative_distance'] = station_df['relative_distance'].fillna(0)

    station_df['arrival_time'] = pd.to_timedelta(station_df['arrival_time'])
    station_df['relative_time'] = station_df['arrival_time'].diff()
    station_df['relative_time'] = station_df['relative_time'].fillna(pd.Timedelta(seconds=0))


with tab2:
    if st.session_state.active_tab != 'Tab 2':
        st.session_state.active_tab = 'Tab 2'
    selected_train = st.selectbox('Train label', options=st.session_state.train_df.sort_values(by='label', ascending=False)['label'])
    placeholder = st.empty()
    while st.session_state.active_tab == 'Tab 2': 
        with placeholder.container():
            train_df = fetch_trains()

            train_data_df = train_df[train_df['label'] == selected_train]
            train_data_sequence = train_data_df.squeeze()
            st.write(train_data_df)


            # Find best trains to match the schedule
            df = pd.merge(st.session_state.train_df, routes_trip_df, left_on='tripId',right_on='trip_id', how='inner')
            df_train_candidates = df.loc[df['start_station'] == selected_direction]
            st.write('Best candidates')
            st.write(df_train_candidates[['label', 'latitude', 'longitude', 'speed', 'route_long_name']])

            train_data = train_data_sequence.to_dict()

            geo_df = station_df[['stop_lat', 'stop_lon']].copy()
            stations_lat_lon = geo_df.to_dict(orient='records')

            nearest_station_index = find_nearest_point(train_data, stations_lat_lon)

            if pd.isna(first_match_trip['route_color']):
                first_match_trip['route_color'] = 'FF0000'
            geo_df['color'] = f"#{first_match_trip['route_color']}"
            if first_match_trip['direction_id'] == 1:
                geo_df.iloc[:nearest_station_index, geo_df.columns.get_loc('color')] = '#00FF00'
            else:
                geo_df.iloc[nearest_station_index + 1:, geo_df.columns.get_loc('color')] = '#00FF00'

            geo_df['size'] = '100'
            geo_df = pd.concat(
                [pd.DataFrame([[train_data['latitude'], train_data['longitude'], '#FFFFFF',200]], columns=geo_df.columns), geo_df], ignore_index=True)
            st.map(geo_df, latitude='stop_lat', longitude='stop_lon', color='color')


            # # Display the stations on a straight line
            st.markdown(
                f"""
                <div style="text-align:right; display: flex; justfy-content: left">
                    <div style="width: 10rem;margin-right: 10px;white-space: normal;">Distance [km]</div>
                    <div style="width: 10rem;margin-right: 10px;white-space: normal;">Time estimated [min]</div>
                    <div style="width: 1rem;margin-right: 10px;white-space: normal;">Status</div>
                    <div style="width: 10rem;margin-right: 10px;white-space: normal;">Station</div>
                </div>
                """, 
                unsafe_allow_html=True)
            for station_id, station in enumerate(station_df['stop_name'].squeeze().to_list()):
                color = f"#{first_match_trip['route_color']}"
                if first_match_trip['direction_id'] == 1:
                    if station_id < nearest_station_index:
                        color = "#00FF00"
                    if station_id == nearest_station_index:
                        color = "#FFFFFF"

                else:
                    if station_id > nearest_station_index:
                        color = "#00FF00"
                    if station_id == nearest_station_index:
                        color = "#FFFFFF"

                st.markdown(
                    f"""
                    <div style="text-align:right; display: flex; justfy-content: left">
                        <div style="width: 10rem;margin-right: 10px;white-space: normal;">{station_df.loc[station_id, 'relative_time'].total_seconds() // 60}</div>
                        <div style="width: 10rem;margin-right: 10px;white-space: normal;">{round(station_df.loc[station_id, 'relative_distance'], 2)}</div>
                        <div style="width:1rem; height:1rem; margin:auto; background-color:{color}; border-radius:50%;"></div>
                        <div style="width: 10rem;margin-right: 10px;white-space: normal;">{string.capwords(station)}</div>
                    </div>
                    """, 
                    unsafe_allow_html=True)
            time.sleep(5)