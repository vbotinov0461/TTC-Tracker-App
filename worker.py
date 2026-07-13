import numpy as np
import math
from typing import List, Dict
from pydantic import BaseModel
from sklearn.cluster import KMeans
from fastapi import FastAPI

ROUTES = [39, 36, 29, 110, 97]
bus_object = {"kept": [], "removed": [], "original": [], "new": []}

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

# Utility functions
def generate_bus(bus, i):
    new_bus = bus.copy()
    new_bus['status'] = "added"
    new_bus['occupancy_status'] = "EMPTY"

    # Minor offset to geo-location
    offset = 0.0005 * ((-1) ** i)
    new_bus['lat'] += offset
    new_bus['lon'] += offset

    return new_bus

def k_means(veh, n):
    positions = np.array([[v['lat'], v['lon']] for v in veh])
    return KMeans(n_clusters=n, random_state=42).fit(positions)
# --- 


# Root function. Takes route-separated vehicles as arg, returns updated list set.
def recommend(vrs):
    budget = 0
    busy, kept, removed, original, new = [], [], [], [], []

    for r_id in ROUTES:
        # Grab vehicles from each route
        v_for_route = vrs.get(str(r_id), [])
        
        # Trim off empty buses and add to 'kept' and 'removed' lists
        temp_kept, temp_removed = trim_buses(v_for_route)
        kept.extend(temp_kept)
        removed.extend(temp_removed)

        # Update fleet budget, otherwise identify congested route
        if len(temp_removed) > 0: budget += len(temp_removed)
        else: busy.append(v_for_route)

    # allocate more buses to each congested route
    for vehicles in busy:
        temp_original, temp_new = add_buses(vehicles, budget // len(busy))
        original.extend(temp_original)
        new.extend(temp_new)

    return kept, removed, original, new


def add_buses(vehicles, budget):
    original, new = vehicles.copy(), []

    # Budget check
    if budget <= 0: return original, new

    # Build list of congested buses in a geographic order
    vehicles = sorted(vehicles, key=lambda v: (v['lat'], v['lon']))
    congested = [
        v for v in vehicles
        if v['occupancy_status'] in [
            "FEW_SEATS_AVAILABLE", "STANDING_ROOM_ONLY", 
            "CRUSHED_STANDING_ROOM_ONLY","FULL"]
    ]

    # For each congested bus add one more until budget runs out. 
    for idx, v in enumerate(congested):
        if budget <= 0: break
        new.append(generate_bus(v, idx))
        budget -= 1

    

    # If there's still budget, use K-means to fill in GEOGRAPHIC gaps
    # Grab new fleet positions and run K-means for n clusters according to budget
    # The buses are clustered according to distance
    centers = k_means(vehicles, min(budget+1, len(vehicles))).cluster_centers_

    # Calculate the average direction the fleet is traveling
    avg_bearing = math.radians(sum(v.get('bearing', 0) for v in vehicles) / len(vehicles))
    cos_b, sin_b = math.cos(avg_bearing), math.sin(avg_bearing)

    # Function to project 2D coords onto a 1D line matching the route's path
    def project(center):
        lat, lon = center
        return lat * cos_b + lon * sin_b

    # Sort the cluster centers chronologically along the direction of travel
    centers = sorted(centers, key=project)

    # Spawn new clusters directly in the midpoints between these sorted cluster centers
    for i in range(len(centers) - 1):
        if budget <= 0: break

        # Calculate the mathematical midpoint between cluster center A and B
        mid_lat = (centers[i][0] + centers[i + 1][0]) / 2
        mid_lon = (centers[i][1] + centers[i + 1][1]) / 2

        new_bus = {
            "vehicle_id": f"new_{len(new)}",
            "lat": mid_lat,
            "lon": mid_lon,
            "route": vehicles[0]['route'],
            "occupancy_status": "EMPTY",
            "status": "added"
        }
        new.append(new_bus)
        budget -= 1

    return original, new

# Keep all buses if there are less than 5
# Otherwise, use K-means to strip off empty buses
def trim_buses(vehicles):
    # Identify candidates for removal
    cand = [v for v in vehicles if v['occupancy_status'] == "EMPTY"]

    # If less than half the bus count is empty, or if there are < 5 buses, keep them
    if len(cand) < (0.5 * len(vehicles)) or len(vehicles) < 5:
        for v in vehicles: 
            v["status"] = "kept"
        return vehicles, []

    # Grab positions and set n clusters to half of bus count
    k = max(1, len(vehicles) // 2)
    labels = k_means(vehicles, k).labels_

    kept, removed = [], []
    # for each cluster, keep the first non-empty bus
    # Otherwise, if the bus is empty, remove it.
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
    data_dict = body.model_dump() # converts pydantic obj into dict for computing
    
    # Route-Separated vehicles
    vehicles_rs = data_dict["route_vehicles"]

    # fetch updated list set from root function
    kept, removed, original, new = recommend(vehicles_rs)
    global bus_object
    new_data = {"kept": kept, "removed": removed, "original": original, "new": new}
    bus_object.update(new_data)

@app.get("/worker")
def get_bus(): return bus_object
