import time
import requests
import threading
import uvicorn
from contextlib import asynccontextmanager
from google.transit import gtfs_realtime_pb2
from fastapi import FastAPI
import os

OCCUPANCY_MAP = {
    0: "EMPTY",
    1: "MANY_SEATS_AVAILABLE",
    2: "FEW_SEATS_AVAILABLE",
    3: "STANDING_ROOM_ONLY",
    4: "CRUSHED_STANDING_ROOM_ONLY",
    5: "FULL",
    6: "NOT_ACCEPTING_PASSENGERS"
}

URL = "https://bustime.ttc.ca/gtfsrt/vehicles"
ROUTES = [39, 36, 29, 110, 97]
worker_url = os.getenv("REMOTE_WORKER_URL")

app = FastAPI(lifespan=lifespan)


# Commit loop logic to lifespan of Web Service
@asynccontextmanager
async def lifespan(app: FastAPI):
    # This code runs when the server starts
    print("Background thread starting...")
    thread = threading.Thread(target=bus_logic_loop, daemon=True)
    thread.start()
    yield
    # This code runs when the server shuts down
    print("Shutting down...")


@app.api_route("/", methods=["GET", "HEAD"])
def health_check():
    return {"status": "running"}


def fetch_ttc_vehicles(route_id):
    response = requests.get(URL, timeout=10)
    response.raise_for_status()

    feed = gtfs_realtime_pb2.FeedMessage()
    feed.ParseFromString(response.content)

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


def bus_logic_loop():
    print("main running...")

    while True:
        try:
            route_vehicles = {}
            for route_id in ROUTES:
                vehicles = fetch_ttc_vehicles(route_id)
                route_vehicles[str(route_id)] = vehicles

            data = {"route_vehicles": route_vehicles}
            response = requests.put(worker_url, json=data)
            print("Sent bus update")

        except Exception as e:
            print(f"main error: {e}")

        time.sleep(30)

    
