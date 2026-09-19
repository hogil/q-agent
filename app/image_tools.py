"""Read-only HTTP adapters for registered SEM and overlay comparisons."""
import datetime as _datetime
import copy
import ipaddress
import json
import math
import os
import re
import socket
import uuid
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener

from incident_tools import ToolError


_MAX_RESPONSE = 1024 * 1024
_MAX_LIST_ASSETS = 100
_ASSET_FIELDS = {
    "asset_id", "incident_id", "lot_id", "wafer_id", "item", "step",
    "equipment", "modality", "coordinate_system", "acquisition",
    "acquired_at", "revision",
}
_RESULT_FIELDS = {
    "request_id", "model", "model_version", "item", "modality",
    "asset_ids", "asset_revisions", "status", "alignment_verified",
    "similarity", "findings", "limitations", "artifact_ids",
}
_ENV_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\Z")
_ID_SCHEME = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*:")


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ToolError("IMAGE_REDIRECT_REFUSED")


def _string(value, code, limit=256):
    if type(value) is not str or not value.strip() or len(value) > limit:
        raise ToolError(code)
    return value


def _date(value):
    _string(value, "INVALID_AS_OF", 10)
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise ToolError("INVALID_AS_OF")
    try:
        _datetime.date.fromisoformat(value)
    except ValueError as exc:
        raise ToolError("INVALID_AS_OF") from exc
    return value


def _loopback(host):
    if host.lower() == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _endpoint(value, code="INVALID_IMAGE_ENDPOINT"):
    if type(value) is not str or not value:
        raise ToolError(code)
    parsed = urlparse(value)
    try:
        host = parsed.hostname
        port = parsed.port
    except ValueError as exc:
        raise ToolError(code) from exc
    if parsed.scheme not in ("http", "https") or not parsed.netloc or not host or port == 0 or parsed.query or parsed.fragment:
        raise ToolError(code)
    if parsed.username or parsed.password:
        raise ToolError(code)
    if parsed.scheme != "https" and not _loopback(host):
        raise ToolError(code)
    return value.rstrip("/")


def _asset_id(value, code="INVALID_ASSET_ID"):
    _string(value, code)
    if "/" in value or "\\" in value or _ID_SCHEME.match(value):
        raise ToolError(code)
    return value


def _iso_timestamp(value, as_of):
    _string(value, "INVALID_IMAGE_ASSET")
    try:
        parsed = _datetime.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ToolError("INVALID_IMAGE_ASSET") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ToolError("INVALID_IMAGE_ASSET")
    if parsed.date() > _datetime.date.fromisoformat(as_of):
        raise ToolError("INVALID_IMAGE_ASSET")
    return value


class ImageTools:
    def __init__(self, settings, incident_tools):
        self.incident_tools = incident_tools
        try:
            configs = settings.data["image_tools"]
        except (AttributeError, KeyError, TypeError) as exc:
            raise ToolError("IMAGE_TOOLS_CONFIG_REQUIRED") from exc
        if not isinstance(configs, dict):
            raise ToolError("INVALID_IMAGE_CONFIG")
        self.config = {}
        for modality in ("sem", "overlay"):
            self.config[modality] = self._read_config(configs.get(modality))
        runtime = getattr(settings, "data", {}).get("runtime", {})
        page_size = runtime.get("max_page_size", runtime.get("default_page_size", 100))
        if type(page_size) is not int or page_size < 1:
            raise ToolError("INVALID_RUNTIME_PAGE_SIZE")
        self.page_size = page_size
        self._asset_cache = {}

    def _read_config(self, config):
        if not isinstance(config, dict):
            raise ToolError("INVALID_IMAGE_CONFIG")
        required = {"enabled", "endpoint", "api_key_env", "timeout_seconds", "served_model"}
        if set(config) != required:
            raise ToolError("INVALID_IMAGE_CONFIG")
        if type(config["enabled"]) is not bool:
            raise ToolError("INVALID_IMAGE_CONFIG")
        if type(config["api_key_env"]) is not str or (config["api_key_env"] and not _ENV_NAME.fullmatch(config["api_key_env"])):
            raise ToolError("INVALID_IMAGE_CONFIG")
        if type(config["timeout_seconds"]) not in (int, float) or isinstance(config["timeout_seconds"], bool) or config["timeout_seconds"] <= 0:
            raise ToolError("INVALID_IMAGE_CONFIG")
        if type(config["served_model"]) is not str or len(config["served_model"]) > 256:
            raise ToolError("INVALID_IMAGE_CONFIG")
        if config["enabled"] and not config["served_model"].strip():
            raise ToolError("INVALID_IMAGE_CONFIG")
        endpoint = config["endpoint"]
        if config["enabled"]:
            endpoint = _endpoint(endpoint)
        elif endpoint:
            endpoint = _endpoint(endpoint)
        else:
            endpoint = ""
        return {**config, "endpoint": endpoint}

    def _scope(self, actor, scope_id):
        _string(actor, "INVALID_ACTOR")
        _string(scope_id, "INVALID_SCOPE_ID")
        scope = self.incident_tools._scope(actor, scope_id)
        ids = scope.get("ids") if isinstance(scope, dict) else None
        if not isinstance(ids, (list, tuple)) or not ids:
            raise ToolError("IMAGE_SCOPE_EMPTY")
        if any(type(value) is not str or not value.strip() for value in ids):
            raise ToolError("IMAGE_SCOPE_INVALID")
        return scope, tuple(ids)

    def _config_for(self, modality):
        if modality not in self.config:
            raise ToolError("INVALID_MODALITY")
        config = self.config[modality]
        if not config["enabled"]:
            raise ToolError("IMAGE_MODEL_DISABLED")
        return config

    def _credential(self, config):
        env_name = config["api_key_env"]
        if not env_name:
            return None
        key = os.environ.get(env_name)
        if not key:
            raise ToolError("IMAGE_API_KEY_UNAVAILABLE")
        return key

    def _post(self, config, path, payload):
        key = self._credential(config)
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        if key:
            headers["Authorization"] = "Bearer " + key
        request = Request(config["endpoint"] + path, data=json.dumps(payload).encode("utf-8"),
                          headers=headers, method="POST")
        try:
            with build_opener(_NoRedirect).open(request, timeout=config["timeout_seconds"]) as response:
                raw = response.read(_MAX_RESPONSE + 1)
            if len(raw) > _MAX_RESPONSE:
                raise ToolError("IMAGE_RESPONSE_TOO_LARGE")
            return json.loads(raw.decode("utf-8"))
        except ToolError:
            raise
        except (HTTPError, URLError, TimeoutError, socket.timeout, OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ToolError("IMAGE_REMOTE_REQUEST_FAILED") from exc

    def _registered_wafers(self, actor, scope_id, incident_ids):
        registered = set()
        offset = 0
        while True:
            try:
                page = self.incident_tools.list_incident_wafers(
                    actor, scope_id, page_size=self.page_size, offset=offset)
            except ToolError:
                raise
            except (KeyError, TypeError, ValueError) as exc:
                raise ToolError("IMAGE_WAFER_REGISTRY_INVALID") from exc
            if not isinstance(page, dict) or not isinstance(page.get("items"), list):
                raise ToolError("IMAGE_WAFER_REGISTRY_INVALID")
            for row in page["items"]:
                if not isinstance(row, dict):
                    raise ToolError("IMAGE_WAFER_REGISTRY_INVALID")
                values = tuple(row.get(key) for key in ("incident_id", "lot_id", "wafer_id"))
                if any(type(value) is not str or not value.strip() or len(value) > 256 for value in values):
                    raise ToolError("IMAGE_WAFER_REGISTRY_INVALID")
                if values[0] in incident_ids:
                    registered.add(values)
            next_offset = page.get("next_offset")
            if next_offset is None:
                return registered
            if type(next_offset) is not int or next_offset <= offset:
                raise ToolError("IMAGE_WAFER_REGISTRY_INVALID")
            offset = next_offset

    def _validate_asset(self, asset, item, modality, as_of, incident_ids, registered):
        if not isinstance(asset, dict) or set(asset) != _ASSET_FIELDS:
            raise ToolError("INVALID_IMAGE_ASSET")
        for field in _ASSET_FIELDS - {"acquired_at"}:
            _string(asset.get(field), "INVALID_IMAGE_ASSET")
        _asset_id(asset["asset_id"], "INVALID_IMAGE_ASSET")
        _iso_timestamp(asset["acquired_at"], as_of)
        if asset["item"] != item or asset["modality"] != modality:
            raise ToolError("INVALID_IMAGE_ASSET")
        if asset["incident_id"] not in incident_ids:
            raise ToolError("INVALID_IMAGE_ASSET")
        if (asset["incident_id"], asset["lot_id"], asset["wafer_id"]) not in registered:
            raise ToolError("INVALID_IMAGE_ASSET")
        return {field: asset[field] for field in _ASSET_FIELDS}

    def list_comparison_assets(self, actor, scope_id, item, modality, as_of):
        scope, incident_ids = self._scope(actor, scope_id)
        del scope
        config = self._config_for(modality)
        item = _string(item, "INVALID_ITEM")
        as_of = _date(as_of)
        registered = self._registered_wafers(actor, scope_id, incident_ids)
        body = self._post(config, "/assets", {
            "actor": actor, "incident_ids": list(incident_ids), "item": item,
            "modality": modality, "as_of": as_of,
        })
        if not isinstance(body, dict) or set(body) != {"assets"} or not isinstance(body["assets"], list):
            raise ToolError("INVALID_IMAGE_RESPONSE")
        if len(body["assets"]) > _MAX_LIST_ASSETS:
            raise ToolError("INVALID_IMAGE_RESPONSE")
        assets = []
        seen = set()
        for asset in body["assets"]:
            normalized = self._validate_asset(asset, item, modality, as_of, incident_ids, registered)
            if normalized["asset_id"] in seen:
                raise ToolError("INVALID_IMAGE_ASSET")
            seen.add(normalized["asset_id"])
            assets.append(normalized)
        self._asset_cache[(actor, scope_id, item, modality, as_of)] = copy.deepcopy({
            asset["asset_id"]: asset for asset in assets
        })
        return {"assets": copy.deepcopy(assets)}

    def _validate_result(self, body, request_id, item, modality, asset_ids, revisions, model):
        if not isinstance(body, dict) or set(body) != _RESULT_FIELDS:
            raise ToolError("INVALID_IMAGE_COMPARE_RESULT")
        if body["request_id"] != request_id or body["model"] != model or body["item"] != item or body["modality"] != modality:
            raise ToolError("INVALID_IMAGE_COMPARE_RESULT")
        if body["asset_ids"] != asset_ids or body["asset_revisions"] != revisions:
            raise ToolError("INVALID_IMAGE_COMPARE_RESULT")
        _string(body["model_version"], "INVALID_IMAGE_COMPARE_RESULT")
        if body["status"] not in ("OK", "INCOMPARABLE") or type(body["alignment_verified"]) is not bool:
            raise ToolError("INVALID_IMAGE_COMPARE_RESULT")
        if body["status"] == "INCOMPARABLE":
            if body["similarity"] is not None:
                raise ToolError("INVALID_IMAGE_COMPARE_RESULT")
        elif body["alignment_verified"]:
            if type(body["similarity"]) not in (int, float) or isinstance(body["similarity"], bool) or not math.isfinite(body["similarity"]) or not 0 <= body["similarity"] <= 1:
                raise ToolError("INVALID_IMAGE_COMPARE_RESULT")
        else:
            raise ToolError("INVALID_IMAGE_COMPARE_RESULT")
        for field in ("findings", "limitations"):
            values = body[field]
            if not isinstance(values, list) or len(values) > 20 or any(type(value) is not str or not value.strip() or len(value) > 2000 for value in values):
                raise ToolError("INVALID_IMAGE_COMPARE_RESULT")
        artifacts = body["artifact_ids"]
        if not isinstance(artifacts, list) or len(artifacts) > 20:
            raise ToolError("INVALID_IMAGE_COMPARE_RESULT")
        for artifact in artifacts:
            _asset_id(artifact, "INVALID_IMAGE_COMPARE_RESULT")
        return body

    def _compare(self, modality, actor, scope_id, item, asset_ids, as_of):
        scope, incident_ids = self._scope(actor, scope_id)
        del scope
        config = self._config_for(modality)
        item = _string(item, "INVALID_ITEM")
        as_of = _date(as_of)
        if not isinstance(asset_ids, list) or len(asset_ids) != 2:
            raise ToolError("IMAGE_ASSET_IDS_REQUIRED")
        asset_ids = [_asset_id(value) for value in asset_ids]
        if asset_ids[0] == asset_ids[1]:
            raise ToolError("IMAGE_ASSET_IDS_REQUIRED")
        cache = self._asset_cache.get((actor, scope_id, item, modality, as_of))
        if not cache or any(value not in cache for value in asset_ids):
            raise ToolError("IMAGE_ASSET_UNKNOWN")
        assets = [cache[value] for value in asset_ids]
        for field in ("item", "step", "coordinate_system", "acquisition"):
            if assets[0][field] != assets[1][field]:
                raise ToolError("IMAGE_COMPARISON_INCOMPATIBLE")
        revisions = [asset["revision"] for asset in assets]
        request_id = str(uuid.uuid4())
        body = self._post(config, "/compare", {
            "request_id": request_id, "actor": actor, "incident_ids": list(incident_ids),
            "item": item, "modality": modality, "as_of": as_of,
            "asset_ids": asset_ids, "asset_revisions": revisions,
            "model": config["served_model"],
        })
        result = self._validate_result(body, request_id, item, modality, asset_ids, revisions, config["served_model"])
        return {
            **result,
            "provenance": {
                "status": result["status"],
                "score_type": "model_similarity",
                "model_score": result["similarity"],
                "validated_asset_metadata": copy.deepcopy(assets),
            },
        }

    def compare_sem_images(self, actor, scope_id, item, asset_ids, as_of):
        return self._compare("sem", actor, scope_id, item, asset_ids, as_of)

    def compare_overlay_maps(self, actor, scope_id, item, asset_ids, as_of):
        return self._compare("overlay", actor, scope_id, item, asset_ids, as_of)
