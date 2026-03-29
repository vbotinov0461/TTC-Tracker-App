import pika
import time
import json
import os
import threading
import requests
from google.transit import gtfs_realtime_pb2
from flask import Flask

app = Flask(__name__)

@app.route('/')
def health_check():
    return "TTC Main is running", 200


OCCUPANCY_MAP = {
    0: "EMPTY",
    1: "MANY_SEATS_AVAILABLE",
    2: "FEW_SEATS_AVAILABLE",
    3: "STANDING_ROOM_ONLY",
    4: "CRUSHED_STANDING_ROOM_ONLY",
    5: "FULL",
    6: "NOT_ACCEPTING_PASSENGERS"
}

RABBITMQ_HOST = os.environ.get("CLOUDAMQP_URL", "amqps://uorhxbdd:Qq68xALHgnp1ynNQKlFMCtaqGQMwgLMZ@codfish.rmq.cloudamqp.com/uorhxbdd")
BUS_UPDATE_QUEUE_NAME = 'bus_update'
URL = "https://bustime.ttc.ca/gtfsrt/vehicles"

ROUTES = [39, 36, 29, 110, 97]


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


def run_main(ch):
    print("main running...")

    while True:
        try:
            route_vehicles = {}

            for route_id in ROUTES:
                vehicles = fetch_ttc_vehicles(route_id)
                route_vehicles[str(route_id)] = vehicles

            data = {"route_vehicles": route_vehicles}
            message = json.dumps(data)

            ch.basic_publish(
                exchange="",
                routing_key=BUS_UPDATE_QUEUE_NAME,
                body=message
            )

            print("Sent bus update")

        except Exception as e:
            print(f"main error: {e}")

        time.sleep(10)


if __name__ == '__main__':
    connection = pika.BlockingConnection(pika.URLParameters(RABBITMQ_HOST))
    publish_channel = connection.channel()
    publish_channel.queue_declare(queue=BUS_UPDATE_QUEUE_NAME)

    thread = threading.Thread(target=run_main, args=(publish_channel, ), daemon=True)
    thread.start()

    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)


    
