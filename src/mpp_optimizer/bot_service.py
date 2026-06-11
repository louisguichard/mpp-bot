from __future__ import annotations

import json
import os
from datetime import datetime

from flask import Flask, jsonify, request
from google.api_core.exceptions import AlreadyExists
from google.cloud import tasks_v2
from google.protobuf import timestamp_pb2

from .auth import MppTokenManager, token_store_from_environment
from .bot import ForecastBot, PlannedForecast
from .mpp_client import MppClient
from .odds_client import PolymarketClient
from .rarity import SupervisedRarityModel


def create_app() -> Flask:
    app = Flask(__name__)

    @app.get("/health")
    def health():
        return jsonify({"ok": True})

    @app.post("/plan")
    def plan():
        # Every planner pass also replays the full sweep: the very first run
        # therefore forecasts every match, later runs only fix drifted picks.
        allow_write = _allow_write()
        sync_result = bot_from_environment(allow_write=allow_write).sync(write=allow_write)
        plans = bot_from_environment(allow_write=False).plan()
        created = [create_forecast_task(item) for item in plans]
        result = {
            "planned": len(plans),
            "tasks": created,
            "sync": {key: value for key, value in sync_result.items() if key != "matches"},
        }
        app.logger.info(json.dumps(result))
        return jsonify(result)

    @app.post("/sync")
    def sync():
        allow_write = _allow_write()
        result = bot_from_environment(allow_write=allow_write).sync(write=allow_write)
        # Full per-match payload on purpose: these are the T-15 covariate
        # snapshots needed to audit the rarity model after the tournament.
        app.logger.info(json.dumps(result))
        return jsonify(result)

    @app.post("/forecast")
    def forecast():
        payload = request.get_json(force=True)
        allow_write = _allow_write()
        result = bot_from_environment(allow_write=allow_write).execute(
            payload["match_id"],
            write=allow_write,
            require_due=True,
        )
        app.logger.info(json.dumps(result))
        return jsonify(result)

    return app


def _allow_write() -> bool:
    return os.getenv("MPP_BOT_ALLOW_WRITE", "").lower() == "true"


def bot_from_environment(*, allow_write: bool) -> ForecastBot:
    token = MppTokenManager(token_store_from_environment()).access_token()
    return ForecastBot(
        MppClient(token=token, allow_write=allow_write),
        PolymarketClient(),
        SupervisedRarityModel.load(),
        lead_minutes=int(os.getenv("MPP_BOT_LEAD_MINUTES", "15")),
        minimum_confidence=float(os.getenv("MPP_BOT_MIN_CONFIDENCE", "0.90")),
    )


def create_forecast_task(plan: PlannedForecast) -> dict:
    project = os.getenv("GOOGLE_CLOUD_PROJECT") or _required("GCP_PROJECT_ID")
    location = _required("CLOUD_TASKS_LOCATION")
    queue = _required("CLOUD_TASKS_QUEUE")
    service_url = _required("MPP_BOT_SERVICE_URL").rstrip("/")
    service_account = _required("MPP_BOT_TASK_SERVICE_ACCOUNT")
    client = tasks_v2.CloudTasksClient()
    parent = client.queue_path(project, location, queue)
    kickoff = datetime.fromisoformat(plan.starts_at)
    task_id = f"{plan.match_id}-{int(kickoff.timestamp())}"
    schedule_time = timestamp_pb2.Timestamp()
    schedule_time.FromDatetime(datetime.fromisoformat(plan.execute_at))
    task = {
        "name": client.task_path(project, location, queue, task_id),
        "schedule_time": schedule_time,
        "http_request": {
            "http_method": tasks_v2.HttpMethod.POST,
            # The T-15 trigger replays the full sweep; the match id is only
            # kept in the body for log traceability.
            "url": f"{service_url}/sync",
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps({"match_id": plan.match_id}).encode(),
            "oidc_token": {
                "service_account_email": service_account,
                "audience": service_url,
            },
        },
    }
    try:
        response = client.create_task(request={"parent": parent, "task": task})
        return {"match_id": plan.match_id, "status": "created", "task": response.name}
    except AlreadyExists:
        return {"match_id": plan.match_id, "status": "already-exists", "task": task["name"]}


def _required(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise ValueError(f"Missing required environment variable: {name}")
    return value


app = create_app()
