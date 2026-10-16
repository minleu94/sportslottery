#!/usr/bin/env python3
"""Model Registry (模型註冊中心).

Dynamically loads and manages prediction models based on config/models.yaml.
Allows enabling, disabling, and replacing models without touching core code.
"""

from __future__ import annotations

import importlib
import hashlib
import inspect
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional
import yaml

from integrations.common.models import PredictionSignal, TaiwanLeg
from core.model_acceptance import ModelAcceptanceGate, load_policy, protocol_hash
from core.strategy_version import get_strategy_metadata
from core.research_paths import research_paths
from probability.calibration import apply_binary_temperature

logger = logging.getLogger(__name__)

CONFIG_PATH = Path(__file__).resolve().parents[1] / "config" / "models.yaml"


class ModelRegistry:
    """Manages all registered open-source prediction models."""

    def __init__(self, config_path: Optional[Path] = None, data_root: Optional[Path] = None,
                 acceptance_gate: Optional[ModelAcceptanceGate] = None):
        self.config_path = config_path or CONFIG_PATH
        self.data_root = research_paths(data_root)["root"]
        if acceptance_gate is not None:
            self.acceptance_gate = acceptance_gate
        else:
            self.acceptance_gate = ModelAcceptanceGate(
                snapshot_path=research_paths(self.data_root)["snapshots"],
                policy_path=Path(__file__).resolve().parents[1] / "config" / "model_acceptance.yaml",
            )
        self._load_acceptance_protocol()
        self.models_config = self._load_config()
        self._instances: Dict[str, Any] = {}
        self._artifact_hashes: Dict[str, str] = {}
        self._state_signatures: Dict[str, Optional[tuple[int, int]]] = {}
        self._init_models()

    def _load_acceptance_protocol(self) -> None:
        self.acceptance_policy = load_policy()
        self.acceptance_protocol_id = self.acceptance_policy.get("protocol_id", "taiwan-forward-binary-temperature-v1")
        predictive_hash = get_strategy_metadata().get("prediction_manifest_hash", "")
        self.acceptance_protocol_hash = protocol_hash({
            "acceptance_policy": self.acceptance_policy,
            "prediction_manifest_hash": predictive_hash,
        })

    def _load_config(self) -> Dict[str, Any]:
        if not self.config_path.exists():
            return {}
        try:
            content = self.config_path.read_text(encoding="utf-8")
            data = yaml.safe_load(content)
            return data.get("models", {}) if isinstance(data, dict) else {}
        except Exception as exc:
            logger.warning("Error loading models config: %s", exc)
            return {}

    def _init_models(self) -> None:
        for model_id, cfg in self.models_config.items():
            if not cfg.get("enabled", True):
                continue
            adapter_path = cfg.get("adapter", "")
            if not adapter_path:
                continue
            try:
                mod_name, cls_name = adapter_path.rsplit(".", 1)
                mod = importlib.import_module(mod_name)
                cls = getattr(mod, cls_name)
                constructor_kwargs = {}
                isolated_cache = self.data_root / "cache" / "models" / model_id
                isolated_state = self.data_root / "model_state" / f"{model_id}.json"
                for parameter in inspect.signature(cls).parameters.values():
                    if parameter.name == "cache_dir":
                        constructor_kwargs[parameter.name] = str(isolated_cache)
                    elif parameter.name == "cache_file":
                        constructor_kwargs[parameter.name] = str(isolated_cache / "cache.json")
                    elif parameter.name == "state_file":
                        constructor_kwargs[parameter.name] = isolated_state
                self._instances[model_id] = cls(**constructor_kwargs)
                self._state_signatures[model_id] = self._state_file_signature(self._instances[model_id])
                module_path = inspect.getsourcefile(cls)
                if module_path and Path(module_path).is_file():
                    self._artifact_hashes[model_id] = hashlib.sha256(Path(module_path).read_bytes()).hexdigest()
            except Exception as exc:
                logger.warning("Failed to initialize model %s: %s", model_id, exc)

    def refresh(self) -> None:
        """Reload persisted model state after a CLI update without resetting the wallet."""
        self._load_acceptance_protocol()
        self.models_config = self._load_config()
        self._instances.clear()
        self._artifact_hashes.clear()
        self._state_signatures.clear()
        self._init_models()

    @staticmethod
    def _state_file_signature(instance: Any) -> Optional[tuple[int, int]]:
        path = getattr(instance, "state_file", None)
        if path is None:
            return None
        try:
            stat = Path(path).stat()
            return stat.st_mtime_ns, stat.st_size
        except FileNotFoundError:
            return None

    def _sync_persisted_state(self, model_id: str, instance: Any) -> None:
        if not hasattr(instance, "state_file"):
            return
        try:
            signature = self._state_file_signature(instance)
        except OSError as exc:
            invalidate = getattr(instance, "invalidate_state", None)
            if callable(invalidate):
                invalidate(f"state file stat failed: {exc}")
            self._state_signatures[model_id] = None
            return
        if signature == self._state_signatures.get(model_id):
            return
        reload_state = getattr(instance, "reload_state", None)
        if not callable(reload_state):
            return
        try:
            reload_state()
        except Exception as exc:
            invalidate = getattr(instance, "invalidate_state", None)
            if callable(invalidate):
                invalidate(f"state reload failed: {exc}")
            logger.warning("Failed reloading persisted state for model %s: %s", model_id, exc)
        self._state_signatures[model_id] = self._state_file_signature(instance)

    def evaluate_leg_across_models(self, leg: TaiwanLeg) -> List[PredictionSignal]:
        """Run all matching enabled models on a TaiwanLeg."""
        signals: List[PredictionSignal] = []
        for model_id, inst in self._instances.items():
            cfg = self.models_config.get(model_id, {})
            model_sport = cfg.get("sport", "").lower()
            if model_sport and model_sport != leg.sport.lower():
                continue
            try:
                self._sync_persisted_state(model_id, inst)
                sig = inst.evaluate_leg(leg)
                if sig:
                    if not isinstance(sig.metadata, dict):
                        sig.metadata = {}
                    if not sig.source_category:
                        sig.source_category = cfg.get("source_category", "MODEL")
                    if not sig.independence_group:
                        sig.independence_group = cfg.get("independence_group", "")
                    sig.metadata["configured_weight"] = cfg.get("weight", 1.0)
                    artifact_hash = self._artifact_hashes.get(model_id, "")
                    try:
                        acceptance = self.acceptance_gate.status(
                            model_id=model_id, model_version=str(cfg.get("version", "unspecified")),
                            league=str(leg.league), market=str(leg.market), source_scope="taiwan_forward",
                            artifact_hash=artifact_hash, protocol_id=self.acceptance_protocol_id,
                            protocol_hash_value=self.acceptance_protocol_hash,
                        )
                    except Exception as gate_exc:
                        logger.warning("Acceptance evidence unavailable for %s: %s", model_id, gate_exc)
                        acceptance = {"accepted": False, "status": "GATE_UNAVAILABLE",
                                      "reason": "evidence_evaluation_failed"}
                    candidate_probability = sig.probability
                    sig.metadata.update({
                        "model_id": model_id,
                        "model_version": str(cfg.get("version", "unspecified")),
                        "model_artifact_hash": artifact_hash,
                        "model_protocol_id": self.acceptance_protocol_id,
                        "model_protocol_hash": self.acceptance_protocol_hash,
                        "prediction_source_scope": "taiwan_forward",
                        "model_acceptance": acceptance,
                        "model_candidate_probability": candidate_probability,
                    })
                    if (acceptance.get("accepted") is True and acceptance.get("calibration_temperature") is not None
                            and isinstance(candidate_probability, (int, float))
                            and not isinstance(candidate_probability, bool)
                            and 0 < float(candidate_probability) < 1):
                        sig.probability = apply_binary_temperature(
                            float(candidate_probability), float(acceptance["calibration_temperature"])
                        )
                        sig.metadata["model_calibrated_probability"] = sig.probability
                        sig.metadata["calibration_provenance"] = {
                            "temperature": acceptance["calibration_temperature"],
                            "fit_cutoff": acceptance.get("calibration_max_prediction_timestamp"),
                            "outcomes_known_by": acceptance.get("calibration_outcomes_known_by"),
                            "training_sample_size": acceptance.get("calibration_n"),
                            "protocol_id": self.acceptance_protocol_id,
                        }
                        odds = getattr(leg, "taiwan_odds", None)
                        if isinstance(odds, (int, float)) and not isinstance(odds, bool) and odds > 1:
                            delta_pp = (sig.probability - 1.0 / float(odds)) * 100.0
                            sig.score = round(delta_pp, 1)
                            sig.model_market_delta_pp = round(delta_pp, 1)
                            sig.model_probability = sig.probability
                    signals.append(sig)
            except Exception as exc:
                logger.warning("Model %s failed on leg %s: %s", model_id, leg.selection, exc)
        return signals

    def get_registered_models_summary(self) -> List[Dict[str, Any]]:
        summary = []
        for mid, cfg in self.models_config.items():
            summary.append({
                "id": mid,
                "name": cfg.get("name"),
                "sport": cfg.get("sport"),
                "enabled": cfg.get("enabled", True),
                "source_category": cfg.get("source_category", "MODEL"),
                "independence_group": cfg.get("independence_group", ""),
                "repo": cfg.get("repo"),
                "repo_url": cfg.get("repo_url", ""),
                "license": cfg.get("license"),
                "version": cfg.get("version"),
                "weight": cfg.get("weight", 1.0),
                "description": cfg.get("description", ""),
                "is_loaded": mid in self._instances,
                "acceptance_status": "REQUIRES_PER_LEAGUE_MARKET_FORWARD_EVIDENCE",
                "acceptance_protocol_id": self.acceptance_protocol_id,
                "artifact_hash": self._artifact_hashes.get(mid),
            })
        return summary
