"""
studio/smart_logger.py
Structured JSONL operational logger + automatic error/warning diagnostic hint engine +
audit log integrator for RayFlux Studio.
"""
from datetime import datetime, timezone
import json
from pathlib import Path
import threading
from typing import Any, Dict, List, Optional

from config.ecosystem_config import DB_ROOT, LOGS_DIR

EVENTS_LOG_PATH = LOGS_DIR / "rfx_studio_events.jsonl"
AUDIT_LOG_PATH = DB_ROOT / "core" / "rfx_db_transaction_audit.log"

_LOCK = threading.Lock()

# Pattern -> actionable human diagnostic hint
DIAGNOSTIC_HINTS = [
    ("connection refused", "PostgreSQL/PostGIS server is stopped. Click 'Start PostGIS' in the header or Logs tab."),
    ("does not exist", "Required upstream layer is missing. Run Section 1 before Section 2/3, or Section 2 before Section 3."),
    ("filenotfounderror", "Input file missing on disk. Verify the AOI boundary or run the preceding section first."),
    ("missing section 1", "Run Section 1 (Data Gathering) for this area first to generate DSM, orthophoto & footprints."),
    ("wfs", "Remote 3D building WFS server temporarily busy or unreachable. Retry Section 1 or check internet connectivity."),
    ("memoryerror", "Out of RAM. Reduce Section 2 worker count or verify Section 3 tile_size <= 512 in solar_parameters.yaml."),
    ("crs", "Coordinate Reference System mismatch. Set target_crs to auto-infer UTM or inspect the uploaded shapefile .prj."),
    ("permissionerror", "File is locked by another program (e.g., QGIS or Excel). Close the file and retry."),
    ("timeout", "External tile or WFS request timed out. Cached tiles are preserved — safely re-run Section 1."),
    ("yaml", "YAML syntax or schema validation error. Check indentation and numeric types in the CV Profile Builder."),
]


def infer_hint(message: str, detail: str = "") -> Optional[str]:
    """Infers an actionable remediation hint from an error/warning message."""
    blob = f"{message} {detail}".lower()
    for needle, hint in DIAGNOSTIC_HINTS:
        if needle in blob:
            return hint
    return None


class SmartLogger:
    """Thread-safe structured event logger writing JSONL entries for the Studio Diagnostics UI."""

    def __init__(self, log_path: Path = EVENTS_LOG_PATH):
        self.log_path = Path(log_path)
        self.log_path.parent.mkdir(parents=True, exist_ok=True)

    def log(
        self,
        level: str,
        message: str,
        section: str = "STUDIO",
        area_id: Optional[str] = None,
        detail: Optional[str] = None,
        hint: Optional[str] = None,
    ) -> Dict[str, Any]:
        lvl = level.upper()
        if lvl not in ("INFO", "WARNING", "ERROR", "SUCCESS"):
            lvl = "INFO"
        resolved_hint = hint or (infer_hint(message, detail or "") if lvl in ("WARNING", "ERROR") else None)
        entry = {
            "timestamp": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
            "level": lvl,
            "section": section,
            "area_id": area_id or "global",
            "message": message.strip(),
            "detail": (detail or "").strip() or None,
            "hint": resolved_hint,
        }
        line = json.dumps(entry, ensure_ascii=False)
        with _LOCK:
            with self.log_path.open("a", encoding="utf-8") as fh:
                fh.write(line + "\n")
        return entry

    def info(self, message: str, section: str = "STUDIO", area_id: Optional[str] = None, detail: Optional[str] = None) -> Dict[str, Any]:
        return self.log("INFO", message, section=section, area_id=area_id, detail=detail)

    def success(self, message: str, section: str = "STUDIO", area_id: Optional[str] = None, detail: Optional[str] = None) -> Dict[str, Any]:
        return self.log("SUCCESS", message, section=section, area_id=area_id, detail=detail)

    def warning(self, message: str, section: str = "STUDIO", area_id: Optional[str] = None, detail: Optional[str] = None) -> Dict[str, Any]:
        return self.log("WARNING", message, section=section, area_id=area_id, detail=detail)

    def error(self, message: str, section: str = "STUDIO", area_id: Optional[str] = None, detail: Optional[str] = None) -> Dict[str, Any]:
        return self.log("ERROR", message, section=section, area_id=area_id, detail=detail)

    def read_events(
        self,
        level: Optional[str] = None,
        search: Optional[str] = None,
        area_id: Optional[str] = None,
        limit: int = 300,
    ) -> Dict[str, Any]:
        """Returns filtered structured events + live severity counts."""
        events: List[Dict[str, Any]] = []
        if self.log_path.exists():
            with _LOCK:
                lines = self.log_path.read_text(encoding="utf-8", errors="replace").splitlines()
            for raw in lines:
                raw = raw.strip()
                if not raw:
                    continue
                try:
                    events.append(json.loads(raw))
                except json.JSONDecodeError:
                    continue

        counts = {"TOTAL": len(events), "ERROR": 0, "WARNING": 0, "SUCCESS": 0, "INFO": 0}
        for e in events:
            lvl = e.get("level", "INFO")
            if lvl in counts:
                counts[lvl] += 1

        filtered = events
        if level and level.upper() != "ALL":
            want = level.upper()
            filtered = [e for e in filtered if e.get("level") == want]
        if area_id and area_id != "all":
            filtered = [e for e in filtered if e.get("area_id") == area_id]
        if search:
            q = search.lower()
            filtered = [
                e for e in filtered
                if q in (e.get("message", "") + " " + (e.get("detail") or "") + " " + (e.get("section") or "")).lower()
            ]

        # Most recent first
        filtered = list(reversed(filtered))[:limit]
        return {"counts": counts, "events": filtered}

    def read_audit_log(self, limit: int = 120) -> List[str]:
        """Reads the latest lines from database/core/rfx_db_transaction_audit.log."""
        if not AUDIT_LOG_PATH.exists():
            return []
        lines = AUDIT_LOG_PATH.read_text(encoding="utf-8", errors="replace").splitlines()
        return list(reversed(lines[-limit:]))

    def clear_events(self) -> None:
        with _LOCK:
            self.log_path.write_text("", encoding="utf-8")


studio_logger = SmartLogger()
