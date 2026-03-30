import numpy as np
import math
from typing import List, Dict
from pydantic import BaseModel
from sklearn.cluster import KMeans
from fastapi import FastAPI


ROUTES = [39, 36, 29, 110, 97]
bus_object = {"kept": None, "removed": None, "OG": None, "xtra": None}

app = FastAPI()

class Vehicle(BaseModel):
    vehicle_id: str
    route: str
    lat: float
    lon: float
    timestamp: int
    bearing: float = 0.0
    occupancy_status: str

class Active_Vehicles(BaseModel):
    route_vehicles: Dict[str, List[Vehicle]]


# Internal computation functions
def recommend(vehicles_route_separated):
    budget = 0
    busy = []
    kept = []
    removed = []
    OG = []
    xtra = []

    for route_id in ROUTES:
        vehicles_for_route = vehicles_route_separated.get(str(route_id), [])
        temp_kept, temp_removed = filter_buses(vehicles_for_route)
        kept.extend(temp_kept)
        removed.extend(temp_removed)

        if len(temp_removed) > 0:
            budget += len(temp_removed)
        else:
            busy.append(vehicles_for_route)

    for vehicles in busy:
        temp_OG, temp_xtra = add_buses(vehicles, budget // len(busy))
        OG.extend(temp_OG)
        xtra.extend(temp_xtra)

    return kept, removed, OG, xtra


def add_buses(vehicles, budget):
    OG, xtra = vehicles.copy(), []

    if budget == 0:
        return OG, xtra

    vehicles = sorted(vehicles, key=lambda v: (v['lat'], v['lon']))

    congested = [
        v for v in vehicles
        if v['occupancy_status'] in [
            "FEW_SEATS_AVAILABLE", "STANDING_ROOM_ONLY",
            "CRUSHED_STANDING_ROOM_ONLY", "FULL"
        ]
    ]

    for idx, v in enumerate(congested):
        if budget <= 0:
            break

        new_bus = v.copy()
        new_bus['status'] = "added"
        new_bus['occupancy_status'] = "EMPTY"

        offset = 0.0005 * ((-1) ** idx)
        new_bus['lat'] += offset
        new_bus['lon'] += offset

        xtra.append(new_bus)
        budget -= 1

    positions = np.array([[v['lat'], v['lon']] for v in vehicles])
    kmeans = KMeans(n_clusters=min(budget + 1, len(vehicles)), random_state=42).fit(positions)
    centers = kmeans.cluster_centers_

    avg_bearing = sum(v.get('bearing', 0) for v in vehicles) / len(vehicles)
    bearing_rad = math.radians(avg_bearing)
    cos_b, sin_b = math.cos(bearing_rad), math.sin(bearing_rad)

    def project(center):
        lat, lon = center
        return lat * cos_b + lon * sin_b

    centers = sorted(centers, key=project)

    for i in range(len(centers) - 1):
        if budget <= 0:
            break

        mid_lat = (centers[i][0] + centers[i + 1][0]) / 2
        mid_lon = (centers[i][1] + centers[i + 1][1]) / 2

        new_bus = {
            "vehicle_id": f"new_{len(xtra)}",
            "lat": mid_lat,
            "lon": mid_lon,
            "route": vehicles[0]['route'],
            "occupancy_status": "EMPTY",
            "status": "added"
        }
        xtra.append(new_bus)
        budget -= 1

    return OG, xtra


def filter_buses(vehicles):
    if len(vehicles) < 5:
        for v in vehicles:
            v["status"] = "kept"
        return vehicles, []

    candidates = [v for v in vehicles if v['occupancy_status'] == "EMPTY"]

    if len(candidates) < 0.5 * len(vehicles):
        for v in vehicles:
            v["status"] = "kept"
        return vehicles, []

    positions = np.array([[v['lat'], v['lon']] for v in vehicles])
    k = max(1, len(vehicles) // 2)
    kmeans = KMeans(n_clusters=k, random_state=42).fit(positions)
    labels = kmeans.labels_

    kept = []
    removed = []

    for cluster_id in range(k):
        cluster_buses = [vehicles[i] for i in range(len(vehicles)) if labels[i] == cluster_id]

        non_empty = [v for v in cluster_buses if v['occupancy_status'] != "EMPTY"]
        bus_to_keep = non_empty[0] if non_empty else cluster_buses[0]

        for v in cluster_buses:
            if v == bus_to_keep:
                v["status"] = "kept"
                kept.append(v)
            else:
                v["status"] = "removed"
                removed.append(v)

    return kept, removed


@app.put("/worker")
def post_bus(body: Active_Vehicles):
    data_dict = body.model_dump() # converts pydantic obj back into dict for computing
    
    vehicles_route_separated = data_dict["route_vehicles"]

    kept, removed, OG, xtra = recommend(vehicles_route_separated)
    global bus_object
    new_data = {"kept": kept, "removed": removed, "OG": OG, "xtra": xtra}
    bus_object.update(new_data)

@app.get("/worker")
def get_bus():
    return bus_object
