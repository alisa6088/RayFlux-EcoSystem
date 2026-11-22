"""
studio/job_runner.py
Asynchronous Background Pipeline Orchestrator for RayFlux Studio.
Executes `run_ecosystem.py` in a managed subprocess with real-time progress bar parsing,
live terminal line capture, cancellation support, and automatic SmartLogger ingestion.
"""
from datetime import datetime, timezone
import os
from pathlib import Path
import re
import subprocess
import sys
import threading
import time
from typing import Any, Dict, List, Optional
import uuid

from config.ecosystem_config import PROJECT_ROOT
from studio.smart_logger import studio_logger

_RE_PCT = re.compile(r"\((\d+(?:\.\d+)?)%\)")


class PipelineJobManager:
    """Manages active and historical pipeline runs with real-time progress and logs."""

    def __init__(self):
        self._lock = threading.Lock()
        self._jobs: Dict[str, Dict[str, Any]] = {}
        self._procs: Dict[str, subprocess.Popen] = {}
        self._active_job_id: Optional[str] = None

    def start_job(
        self,
        area_id: str,
        sections: List[int],
        cv_profile: Optional[str] = None,
        workers: Optional[int] = None,
        reuse_rasters: bool = False,
        dsm_res: Optional[float] = None,
        min_area: Optional[float] = None,
    ) -> Dict[str, Any]:
        with self._lock:
            if self._active_job_id and self._jobs.get(self._active_job_id, {}).get("status") == "running":
                raise RuntimeError(f"Another job ({self._active_job_id}) is already running. Wait or cancel it first.")

            clean_sections = sorted(set(s for s in sections if s in (1, 2, 3)))
            if not clean_sections:
                raise ValueError("Select at least one section (1, 2, or 3) to run.")

            job_id = f"job_{datetime.now().strftime('%H%M%S')}_{uuid.uuid4().hex[:5]}"
            cmd = [sys.executable, "-u", str(PROJECT_ROOT / "run_ecosystem.py"), "--area-id", area_id]
            if clean_sections == [1, 2, 3]:
                cmd.append("--all")
            else:
                for s in clean_sections:
                    cmd.extend(["--section", str(s)])
            if cv_profile:
                cmd.extend(["--cv-profile", cv_profile])
            if workers:
                cmd.extend(["--workers", str(int(workers))])
            if reuse_rasters:
                cmd.append("--reuse-rasters")
            if dsm_res is not None:
                cmd.extend(["--dsm-res", str(float(dsm_res))])
            if min_area is not None:
                cmd.extend(["--min-area", str(float(min_area))])

            job = {
                "job_id": job_id,
                "area_id": area_id,
                "sections": clean_sections,
                "cv_profile": cv_profile or "default",
                "status": "running",
                "progress_pct": 1.0,
                "current_section": clean_sections[0],
                "current_stage": f"Initializing Section {clean_sections[0]}...",
                "started_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
                "ended_at": None,
                "elapsed_sec": 0.0,
                "exit_code": None,
                "logs": [],
                "error_count": 0,
                "warning_count": 0,
                "_t0": time.time(),
            }
            self._jobs[job_id] = job
            self._active_job_id = job_id

        studio_logger.info(
            f"Started pipeline job {job_id} on area '{area_id}' (sections={clean_sections}).",
            section="PIPELINE",
            area_id=area_id,
        )
        t = threading.Thread(target=self._run_worker, args=(job_id, cmd), daemon=True)
        t.start()
        return self.get_job(job_id)

    def _update_progress_from_line(self, job: Dict[str, Any], line: str) -> None:
        sections = job["sections"]
        n_sec = len(sections)
        cur_sec = job["current_section"]

        if "SECTION 1:" in line or "[S1]" in line:
            cur_sec = 1
        elif "SECTION 2:" in line or "[S2]" in line:
            cur_sec = 2
        elif "SECTION 3:" in line or "[S3]" in line:
            cur_sec = 3

        job["current_section"] = cur_sec
        sec_idx = sections.index(cur_sec) if cur_sec in sections else 0
        sec_base = (sec_idx / n_sec) * 100.0
        sec_span = (1.0 / n_sec) * 100.0

        # Fine-grained sub-stage parsing
        local_pct = None
        m = _RE_PCT.search(line)
        if m:
            raw_p = float(m.group(1))
            if cur_sec == 2:
                local_pct = 10.0 + raw_p * 0.72
            elif cur_sec == 3:
                local_pct = 8.0 + raw_p * 0.65
            else:
                local_pct = raw_p * 0.85
        elif "SECTION 1 COMPLETE" in line or "SECTION 2 COMPLETE" in line or "SECTION 3 COMPLETE" in line:
            local_pct = 99.0
        elif "Committing" in line:
            local_pct = 86.0
        elif "Rendering" in line:
            local_pct = 93.0
        elif "Steps 3.5" in line or "Computing PV yields" in line:
            local_pct = 78.0
        elif "Running exact Getis-Ord" in line:
            local_pct = 83.0
        elif "Step 3.1" in line:
            local_pct = 5.0
        elif "Loaded" in line and "buildings" in line:
            local_pct = 8.0

        if local_pct is not None:
            new_pct = min(99.5, sec_base + (local_pct / 100.0) * sec_span)
            job["progress_pct"] = round(max(job["progress_pct"], new_pct), 1)

        clean_stage = line.strip()
        if clean_stage and not clean_stage.startswith("="):
            job["current_stage"] = clean_stage[:120]

    def _run_worker(self, job_id: str, cmd: List[str]) -> None:
        env = os.environ.copy()
        env["PYTHONUNBUFFERED"] = "1"
        env["PYTHONIOENCODING"] = "utf-8"

        try:
            proc = subprocess.Popen(
                cmd,
                cwd=str(PROJECT_ROOT),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                env=env,
            )
            with self._lock:
                self._procs[job_id] = proc

            error_tail: List[str] = []
            assert proc.stdout is not None
            for raw_line in proc.stdout:
                line = raw_line.rstrip("\r\n")
                if not line:
                    continue
                low = line.lower()
                lvl = "INFO"
                if any(tok in low for tok in ("traceback", "error:", "exception", "failed", "filenotfounderror", "valueerror")):
                    lvl = "ERROR"
                    error_tail.append(line)
                elif any(tok in low for tok in ("warning", "warn", "fallback", "standby")):
                    lvl = "WARNING"
                elif "complete" in low or "enabled postgis" in low:
                    lvl = "SUCCESS"

                ts = datetime.now().strftime("%H:%M:%S")
                with self._lock:
                    job = self._jobs[job_id]
                    job["elapsed_sec"] = round(time.time() - job["_t0"], 1)
                    job["logs"].append({"ts": ts, "level": lvl, "text": line})
                    if len(job["logs"]) > 2000:
                        job["logs"] = job["logs"][-1500:]
                    if lvl == "ERROR":
                        job["error_count"] += 1
                    elif lvl == "WARNING":
                        job["warning_count"] += 1
                    self._update_progress_from_line(job, line)

                if lvl in ("ERROR", "WARNING"):
                    studio_logger.log(
                        lvl,
                        line,
                        section=f"SECTION_{self._jobs[job_id]['current_section']}",
                        area_id=self._jobs[job_id]["area_id"],
                    )

            rc = proc.wait()
            with self._lock:
                job = self._jobs[job_id]
                job["exit_code"] = rc
                job["elapsed_sec"] = round(time.time() - job["_t0"], 1)
                job["ended_at"] = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
                if job["status"] == "cancelled":
                    job["current_stage"] = "Cancelled by user."
                elif rc == 0:
                    job["status"] = "completed"
                    job["progress_pct"] = 100.0
                    job["current_stage"] = "Pipeline completed successfully."
                else:
                    job["status"] = "failed"
                    job["current_stage"] = f"Pipeline failed (exit code {rc})."
                self._procs.pop(job_id, None)

            if self._jobs[job_id]["status"] == "completed":
                studio_logger.success(
                    f"Pipeline job {job_id} completed in {self._jobs[job_id]['elapsed_sec']}s.",
                    section="PIPELINE",
                    area_id=self._jobs[job_id]["area_id"],
                )
            elif self._jobs[job_id]["status"] == "failed":
                studio_logger.error(
                    f"Pipeline job {job_id} failed with exit code {rc}.",
                    section="PIPELINE",
                    area_id=self._jobs[job_id]["area_id"],
                    detail="\n".join(error_tail[-12:]),
                )
        except Exception as exc:
            with self._lock:
                job = self._jobs[job_id]
                job["status"] = "failed"
                job["ended_at"] = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
                job["current_stage"] = f"Launcher error: {exc}"
                job["error_count"] += 1
            studio_logger.error(f"Job {job_id} crashed: {exc}", section="PIPELINE", area_id=job["area_id"])

    def cancel_job(self, job_id: str) -> Dict[str, Any]:
        with self._lock:
            proc = self._procs.get(job_id)
            job = self._jobs.get(job_id)
            if not job:
                raise KeyError(f"Job '{job_id}' not found.")
            if proc and proc.poll() is None:
                job["status"] = "cancelled"
                proc.terminate()
        studio_logger.warning(f"Cancelled pipeline job {job_id}.", section="PIPELINE", area_id=job["area_id"])
        return self.get_job(job_id)

    def get_job(self, job_id: str, log_offset: int = 0) -> Dict[str, Any]:
        with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                raise KeyError(f"Job '{job_id}' not found.")
            elapsed = round(time.time() - job["_t0"], 1) if job["status"] == "running" else job["elapsed_sec"]
            return {
                "job_id": job["job_id"],
                "area_id": job["area_id"],
                "sections": job["sections"],
                "cv_profile": job["cv_profile"],
                "status": job["status"],
                "progress_pct": job["progress_pct"],
                "current_section": job["current_section"],
                "current_stage": job["current_stage"],
                "started_at": job["started_at"],
                "ended_at": job["ended_at"],
                "elapsed_sec": elapsed,
                "exit_code": job["exit_code"],
                "error_count": job["error_count"],
                "warning_count": job["warning_count"],
                "total_log_lines": len(job["logs"]),
                "logs": job["logs"][log_offset:],
            }

    def list_jobs(self) -> List[Dict[str, Any]]:
        with self._lock:
            ids = list(reversed(list(self._jobs.keys())))
        return [self.get_job(jid, log_offset=max(0, len(self._jobs[jid]["logs"]) - 25)) for jid in ids[:20]]


job_manager = PipelineJobManager()
