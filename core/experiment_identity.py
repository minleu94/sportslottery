"""Stable, auditable identity for one strategy/config/model experiment."""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any, Mapping, Optional

from core.strategy_version import get_strategy_metadata, hash_prediction_manifest

IDENTITY_SCHEMA = "experiment-identity-v2"
LEGACY_IDENTITY_SCHEMA = "experiment-identity-v1"
METRICS_PROTOCOL = "unique-event-selection-v1"


def _canonical_json(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                      allow_nan=False).encode("utf-8")


def _identity_payload(identity: Mapping[str, Any]) -> dict[str, Any]:
    schema = identity["schema"]
    if schema == LEGACY_IDENTITY_SCHEMA:
        fields = ("schema", "strategy_version", "code_content_hash", "config_hashes",
                  "current_model_set", "protocol_settings")
    elif schema == IDENTITY_SCHEMA:
        fields = ("schema", "strategy_version", "prediction_manifest_hash", "prediction_manifest",
                  "config_hashes", "current_model_set", "protocol_settings")
    else:
        raise ValueError("unsupported experiment identity schema")
    return {key: identity[key] for key in fields}


def _experiment_id(payload: Mapping[str, Any]) -> str:
    return "exp_" + hashlib.sha256(_canonical_json(dict(payload))).hexdigest()


def build_experiment_identity(
    strategy_metadata: Optional[Mapping[str, Any]] = None,
    protocol_settings: Optional[Mapping[str, Any]] = None,
    *,
    repo_dir: Optional[Path] = None,
) -> dict[str, Any]:
    """Build an identity from content hashes and explicit evaluation protocols.

    Volatile generation timestamps, git status text, and absolute paths are
    intentionally excluded. Pass persisted strategy metadata when reconstructing
    an identity for historical snapshots; never replace it with current runtime
    metadata.
    """
    metadata = dict(strategy_metadata) if strategy_metadata is not None else get_strategy_metadata(repo_dir)
    prediction_hash = metadata.get("prediction_manifest_hash")
    prediction_manifest = metadata.get("prediction_manifest")
    # Metadata explicitly supplied by older callers/snapshots may only have the
    # v1 whole-build hash. Keep it reconstructible as a legacy identity.
    legacy_metadata = not isinstance(prediction_hash, str) or not isinstance(prediction_manifest, Mapping)
    code_hash = metadata.get("code_hash") or metadata.get("content_hash") or metadata.get("working_tree_hash")
    config_hashes = metadata.get("config_hashes")
    model_set = metadata.get("current_model_set")
    strategy_version = metadata.get("strategy_version")
    if not isinstance(strategy_version, str) or not strategy_version.strip():
        raise ValueError("strategy metadata is missing strategy_version")
    if not isinstance(code_hash, str) or not re.fullmatch(r"[0-9a-fA-F]{64}", code_hash):
        raise ValueError("strategy metadata is missing a valid code content hash")
    if not isinstance(config_hashes, Mapping) or not all(
            isinstance(key, str) and isinstance(value, str)
            and re.fullmatch(r"[0-9a-fA-F]{64}", value)
            for key, value in config_hashes.items()):
        raise ValueError("strategy metadata is missing valid configuration hashes")
    if not isinstance(model_set, Mapping):
        raise ValueError("strategy metadata is missing current_model_set")

    defaults = {
        "prediction_cutoff_policy": "strict-pre-event-v1",
        "freshness_policy": "source-observed-time-required-v1",
        "calibration_protocol": "uncalibrated-estimates-excluded-from-verified-accuracy-v1",
        "settlement_rules_version": metadata.get("settlement_rules_version"),
        "evidence_weights_version": metadata.get("evidence_weights_version"),
        "evidence_weights_hash": metadata.get("evidence_weights_hash"),
        "metrics_protocol": METRICS_PROTOCOL,
    }
    if protocol_settings:
        defaults.update(dict(protocol_settings))
    if any(value is None for value in defaults.values()):
        raise ValueError("protocol settings lack versioned settlement or evidence-weight identity")
    if legacy_metadata:
        payload = {
            "schema": LEGACY_IDENTITY_SCHEMA,
            "strategy_version": strategy_version,
            "code_content_hash": code_hash.lower(),
            "config_hashes": dict(sorted(config_hashes.items())),
            "current_model_set": dict(sorted(model_set.items())),
            "protocol_settings": defaults,
        }
    else:
        if not re.fullmatch(r"[0-9a-fA-F]{64}", prediction_hash):
            raise ValueError("strategy metadata is missing a valid prediction manifest hash")
        if not all(isinstance(path, str) and isinstance(digest, str)
                   and re.fullmatch(r"[0-9a-fA-F]{64}", digest)
                   for path, digest in prediction_manifest.items()):
            raise ValueError("strategy metadata contains an invalid prediction manifest")
        payload = {
            "schema": IDENTITY_SCHEMA,
            "strategy_version": strategy_version,
            "prediction_manifest_hash": prediction_hash.lower(),
            "prediction_manifest": dict(sorted(prediction_manifest.items())),
            "config_hashes": dict(sorted(config_hashes.items())),
            "current_model_set": dict(sorted(model_set.items())),
            "protocol_settings": defaults,
        }
    identity = dict(payload)
    identity["experiment_id"] = _experiment_id(payload)
    return identity


def validate_experiment_identity(identity: Any) -> bool:
    """Return True only when the identity is structurally complete and untampered."""
    if not isinstance(identity, Mapping):
        return False
    try:
        payload = _identity_payload(identity)
        if payload["schema"] not in {IDENTITY_SCHEMA, LEGACY_IDENTITY_SCHEMA}:
            return False
        if not isinstance(payload["strategy_version"], str) or not payload["strategy_version"]:
            return False
        if not isinstance(payload["config_hashes"], Mapping) or not isinstance(payload["current_model_set"], Mapping):
            return False
        if not isinstance(payload["protocol_settings"], Mapping):
            return False
        if payload["schema"] == LEGACY_IDENTITY_SCHEMA:
            if not re.fullmatch(r"[0-9a-f]{64}", payload["code_content_hash"]):
                return False
        else:
            if not re.fullmatch(r"[0-9a-f]{64}", payload["prediction_manifest_hash"]):
                return False
            manifest = payload["prediction_manifest"]
            if not isinstance(manifest, Mapping) or not all(
                    isinstance(path, str) and isinstance(digest, str)
                    and re.fullmatch(r"[0-9a-f]{64}", digest)
                    for path, digest in manifest.items()):
                return False
            if hash_prediction_manifest(dict(manifest)) != payload["prediction_manifest_hash"]:
                return False
        return identity.get("experiment_id") == _experiment_id(payload)
    except (KeyError, TypeError, ValueError):
        return False


def get_current_experiment_identity(repo_dir: Optional[Path] = None) -> dict[str, Any]:
    """Return the identity of the currently running code/configuration set."""
    return build_experiment_identity(repo_dir=repo_dir)
