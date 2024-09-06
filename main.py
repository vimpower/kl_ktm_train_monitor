import streamlit as st
import pandas as pd
import requests
import time
import string
import zipfile
import io
import pytz
import datetime
from math import radians, sin, cos, sqrt, atan2
from streamlit_autorefresh import st_autorefresh

st_autorefresh(interval=60000, key="data_refresh")

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


@st.cache_data(max_entries=2, ttl=60, show_spinner=True)
def fetch_trains():
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
    while True: 
        response = requests.get(url)
        print("Fetching train data ...")
        if response.status_code == 200:
            json_data = response.json()
            data = pd.DataFrame(json_data['data'])
            
            if len(data) > 0:
                # Write the DataFrame to an Excel file
                trip_df = pd.json_normalize(data['trip'])
                position_df = pd.json_normalize(data['position'])
                timestamp_df = pd.DataFrame(data['timestamp'])
                timezone = pytz.timezone('Asia/Kuala_Lumpur')
                timestamp_df['localtime'] = timestamp_df['timestamp'].apply(lambda x : datetime.datetime.fromtimestamp(int(x)).replace(tzinfo=pytz.utc).astimezone(timezone))
                vehicle_df = pd.json_normalize(data['vehicle'])

                # Concatenate all dataframes into one
                df = pd.concat([trip_df, position_df, vehicle_df, timestamp_df], axis=1)
                df.astype(dtype_spec)
                print("Done fetching ...")
                return df
            else:
                return None
        elif response.status_code == 429:
            # Rate limit reset
            print("Too many request wait for 10 seconds")
            time.sleep(10.5)
        else:
            print(f"Other error with status code {response.status_code} coldown in 10 seconds")
            time.sleep(10.5)


@st.cache_data(max_entries=2, ttl=3600, show_spinner=True)
def fetch_static():
    while True:
        print("Fetching static data ...")
        url = 'https://api.data.gov.my/gtfs-static/ktmb'
        response = requests.get(url) 
        if response.status_code == 200:
            # Use the BytesIO object to read the binary content
            zip_file = io.BytesIO(response.content)
            
            # Open the ZIP file
            with zipfile.ZipFile(zip_file, 'r') as zip_ref:
                # Extract all files in the current directory
                zip_ref.extractall('./static_data')

            # Define Malaysia timezone
            malaysia_tz = pytz.timezone('Asia/Kuala_Lumpur')

            # Get today's date in Malaysia timezone
            today_date = datetime.datetime.now(malaysia_tz).date()

            def time_with_overflow_to_datetime(time_str):
                # Split the time into hours, minutes, and seconds
                hours, minutes, seconds = map(int, time_str.split(':'))
                
                # Calculate the timedelta based on hours, minutes, and seconds
                time_delta = datetime.timedelta(hours=hours, minutes=minutes, seconds=seconds)
                
                # Add the timedelta to today's date
                new_datetime = datetime.datetime.combine(today_date, datetime.datetime.min.time(), malaysia_tz) + time_delta
                
                return new_datetime
            trips_df = pd.read_csv('static_data/trips.txt')
            routes_df = pd.read_csv('static_data/routes.txt')
            stops_df = pd.read_csv('static_data/stops.txt')
            stop_times_df = pd.read_csv('static_data/stop_times.txt')
            stop_times_df['arrival_time'] = stop_times_df['arrival_time'].apply(time_with_overflow_to_datetime)
            stop_times_df['departure_time'] = stop_times_df['departure_time'].apply(time_with_overflow_to_datetime)
            return trips_df, routes_df, stops_df, stop_times_df
        elif response.status_code == 429:
            # Rate limit reset
            print("Too many request wait for 10 seconds")
            time.sleep(10.5)
        else:
            print(f"Other error with status code {response.status_code} coldown in 10 seconds")
            time.sleep(10.5)


trips_df, routes_df, stops_df, stop_times_df = fetch_static()
routes_trip_df = pd.merge(trips_df, routes_df, how='inner')

if 'active_tab' not in st.session_state:
    st.session_state.active_tab = 'Tab 1'

tab1, tab2 = st.tabs(["Route selection", "Train selection"])


train_df = fetch_trains()
with tab1:
    if st.session_state.active_tab != 'Tab 1':
        st.session_state.active_tab = 'Tab 1'

    # Streamlit app layout
    selected_line = st.selectbox("Select a route to track", key='line', options=routes_df['route_long_name'], index=1)

    route_id = routes_df.loc[routes_df['route_long_name'] == selected_line, 'route_id'].values[0]
    route_long_name = routes_df.loc[routes_df['route_id'] == route_id, 'route_long_name'].values[0]

    endpoint_names = route_long_name.replace("KTM ", "").replace("Intercity ", "").replace("Electric Train Service", "").split(" - ")
    selected_direction = st.selectbox('Train travel from', key='direction', options=sorted(endpoint_names))

    direction_id = endpoint_names.index(selected_direction)
    trips = routes_trip_df[(routes_trip_df['route_id'] == route_id) & (routes_trip_df['direction_id'] == direction_id)] 
    trip_stops = pd.merge(stop_times_df, trips, on="trip_id").groupby(by="trip_id").agg({'arrival_time' : 'mean'}).reset_index()

    train_trip_df = pd.merge(train_df, trips_df, left_on='tripId', right_on='trip_id')
    # st.write(pd.merge(train_trip_df, routes_df)[['route_long_name', 'label', 'direction_id']])
    train_trip_df['color'] = "#FF0000"
    train_trip_df.loc[(train_trip_df['route_id'] == route_id) & (train_trip_df['direction_id'] == direction_id), 'color'] = "#00FF00"
    st.title("Train radars 📡")
    st.map(train_trip_df, color='color', size=500)



with tab2:
    if st.session_state.active_tab != 'Tab 2':
        st.session_state.active_tab = 'Tab 2'

    if train_df is not None:
        trip_stops['delta_time'] = trip_stops['arrival_time'] - train_df['localtime'].median()
        potential_trip = trip_stops[(trip_stops['delta_time'] < datetime.timedelta(hours=8)) & (trip_stops['delta_time'] > -datetime.timedelta(hours=8))]
        active_trips = pd.merge(potential_trip, train_df, left_on="trip_id", right_on="tripId") 
        selected_train = st.selectbox('Train label', key='train', options=active_trips.sort_values(by='label', ascending=False)['label'] if active_trips is not None else [])

        train_data = train_df[train_df['label'] == selected_train].squeeze().to_dict()
        train_stops = pd.merge(stop_times_df[stop_times_df['trip_id'] == train_data['tripId']], stops_df, on="stop_id")

        # Select station to board
        if len(train_stops) > 0:
            board_station = st.selectbox("Boarding station", key="station", options=train_stops['stop_name'])
            # Geo data
            stations_lat_lon = train_stops[['stop_lat', 'stop_lon']].to_dict(orient='records')
            nearest_station_index = find_nearest_point(train_data, stations_lat_lon)
            selected_station_index = train_stops['stop_name'].squeeze().tolist().index(board_station)


            lat_train, lon_train = train_data['latitude'], train_data['longitude']
            geo_df = train_stops[['stop_lat', 'stop_lon', 'stop_name']].copy()
            geo_df['color'] = "#FF0000"
            if direction_id == 1:
                geo_df.iloc[:nearest_station_index, geo_df.columns.get_loc('color')] = '#00FF00'
            else:
                geo_df.iloc[nearest_station_index + 1:, geo_df.columns.get_loc('color')] = '#00FF00'
            geo_df.loc[geo_df['stop_name'] == board_station, 'color'] = '#FFA500'
            geo_df['size'] = '100'
            geo_df = pd.concat(
                [pd.DataFrame([[lat_train, lon_train, 'train','#FFFFFF',200]], columns=geo_df.columns), geo_df], ignore_index=True)
            st.map(geo_df, latitude='stop_lat', longitude='stop_lon', color='color')

            st.markdown(
                f"""
                <div style="text-align:right; display: flex; justfy-content: left;">
                    <div style="width: 10rem;margin-right: 10px;white-space: normal;">Station</div>
                </div>
                """, 
                unsafe_allow_html=True)
            for station_id, station in enumerate(train_stops['stop_name'].squeeze().to_list()):
                color = "#FF0000"
                if direction_id == 1:
                    if station_id < nearest_station_index:
                        color = "#016620"
                    if station_id == nearest_station_index:
                        color = "#999999"
                else:
                    if station_id > nearest_station_index:
                        color = "#016620"
                    if station_id == nearest_station_index:
                        color = "#999999"
                if station == board_station:
                    color = "#FFA500"
                st.markdown(
                    f"""
                    <div style="text-align:right; display: flex; justfy-content: left; background-color:{color};">
                        <div style="width: 50%;">{station}</div>
                    </div>
                    """, 
                    unsafe_allow_html=True)




