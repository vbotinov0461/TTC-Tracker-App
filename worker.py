import pika
import json
import numpy as np
import math
import os
from sklearn.cluster import KMeans

RABBITMQ_HOST = os.environ.get("CLOUDAMQP_URL", "amqps://uorhxbdd:Qq68xALHgnp1ynNQKlFMCtaqGQMwgLMZ@codfish.rmq.cloudamqp.com/uorhxbdd")
RECOMMENDATION_QUEUE_NAME = 'schedule_recommendation'
BUS_UPDATE_QUEUE_NAME = 'bus_update'

ROUTES = [39, 36, 29, 110, 97]


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


def callback(ch, method, properties, body):
    try:
        data = json.loads(body)
        vehicles_route_separated = data["route_vehicles"]

        kept, removed, OG, xtra = recommend(vehicles_route_separated)
        data_send = {"kept": kept, "removed": removed, "OG": OG, "xtra": xtra}

        message = json.dumps(data_send)
        publish_channel.basic_publish(
            exchange='',
            routing_key=RECOMMENDATION_QUEUE_NAME,
            body=message
        )

        print("Sent recommendation update")

    except Exception as e:
        print(f"Worker error: {e}")

    ch.basic_ack(delivery_tag=method.delivery_tag)


if __name__ == '__main__':
    connection = pika.BlockingConnection(pika.URLParameters(RABBITMQ_HOST))

    consume_channel = connection.channel()
    consume_channel.queue_declare(queue=BUS_UPDATE_QUEUE_NAME)

    global publish_channel
    publish_channel = connection.channel()
    publish_channel.queue_declare(queue=RECOMMENDATION_QUEUE_NAME)

    consume_channel.basic_consume(
        queue=BUS_UPDATE_QUEUE_NAME,
        on_message_callback=callback,
        auto_ack=False
    )

    print("Worker running...")
    consume_channel.start_consuming()
