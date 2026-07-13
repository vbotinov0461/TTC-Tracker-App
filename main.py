import time, requests, threading, uvicorn, os
from contextlib import asynccontextmanager
from google.transit import gtfs_realtime_pb2
from fastapi import FastAPI

OCCUPANCY_MAP = {
    0: "EMPTY",
    1: "MANY_SEATS_AVAILABLE",
    2: "FEW_SEATS_AVAILABLE",
    3: "STANDING_ROOM_ONLY",
    4: "CRUSHED_STANDING_ROOM_ONLY",
    5: "FULL",
    6: "NOT_ACCEPTING_PASSENGERS"
}

TTC_URL = "https://bustime.ttc.ca/gtfsrt/vehicles"
ROUTES = [39, 36, 29, 110, 97]
WORKER_URL = 'http://localhost:8001/worker'

app = FastAPI()

def fetch_ttc_vehicles(route_id):
    response = requests.get(TTC_URL, timeout=10)
    response.raise_for_status()
    feed = gtfs_realtime_pb2.FeedMessage()
    feed.ParseFromString(response.content)

    # Fill vehicle manifest
    vehicles = []
    for entity in feed.entity:
        if entity.HasField("vehicle"):
            v = entity.vehicle
            if v.trip.route_id == str(route_id):
                vehicles.append({
                    "vehicle_id": v.vehicle.id,
                    "route": v.trip.route_id,
                    "lat": v.position.latitude,
                    "lon": v.position.longitude,
                    "timestamp": v.timestamp,
                    "bearing": v.position.bearing,
                    "occupancy_status": OCCUPANCY_MAP.get(v.occupancy_status, "UNKNOWN")
                })
    return vehicles


def tracker():
    print("TTC Tracker Started Running...")
    while True:
        try:
            route_vehicles = {}
            for route_id in ROUTES:
                vehicles = fetch_ttc_vehicles(route_id)
                route_vehicles[str(route_id)] = vehicles

            data = {"route_vehicles": route_vehicles}
            response = requests.put(WORKER_URL, json=data)
            print(f"Sent bus update. Status: {response.status_code}")
        except Exception as e: 
            print(f"Tracker error: {e}")
        time.sleep(30)

# The lifespan manager handles startup logic when Uvicorn boots up
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Start the background loop in a separate thread so it doesn't block FastAPI
    thread = threading.Thread(target=tracker, daemon=True)
    thread.start()
    yield
    # Any cleanup code would go here after yield

# Pass the lifespan manager into your FastAPI initialization
app = FastAPI(lifespan=lifespan)

    
