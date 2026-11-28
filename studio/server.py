"""
studio/server.py
FastAPI Application for RayFlux Studio — Unified Operations, Multi-Area GIS,
CV Profile Builder, Data Explorer, PostGIS Monitor & Pipeline Control Center.
"""
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from config.ecosystem_config import EcosystemConfig, PROJECT_ROOT
from core_db.database_manager import CentralDatabaseManager
from core_db.init_postgis_cluster import ensure_postgis_cluster_running
from studio.area_registry import area_registry
from studio.cv_profile_engine import (
    AREA_TYPE_ARCHETYPES,
    ROOF_TRAIT_OPTIONS,
    list_profiles,
    save_profile,
    synthesize_cv_config,
    validate_cv_yaml_text,
)
from studio.gis_service import (
    RASTER_KEYS,
    bundle_shapefile_zip,
    delete_asset_file,
    get_all_area_boundaries_geojson,
    get_area_data_inventory,
    get_area_vector_geojson,
    preflight_area_sections,
    preview_table_rows,
    purge_area_sections,
    render_raster_overlay_png,
    resolve_safe_project_file,
)
from studio.job_runner import job_manager
from studio.smart_logger import studio_logger

STATIC_DIR = Path(__file__).resolve().parent / "static"

app = FastAPI(title="RayFlux Studio — Solar Intelligence Control Center", version="1.0.0")
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


# ---------------- Pydantic Request Schemas ----------------

class DrawnAreaRequest(BaseModel):
    name: str
    description: str = ""
    geojson: Dict[str, Any]
    area_types: List[str] = ["mixed_urban"]
    traits: List[str] = []
    cv_profile: Optional[str] = None
    auto_generate_cv_yaml: bool = True
    imagery_gsd_m: float = 0.45
    dsm_resolution_m: float = 0.50
    min_building_area_m2: float = 50.0
    footprint_mode: str = "wfs_only"


class UpdateAreaRequest(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    area_types: Optional[List[str]] = None
    traits: Optional[List[str]] = None
    cv_profile: Optional[str] = None
    dsm_resolution_m: Optional[float] = None
    min_building_area_m2: Optional[float] = None


class PurgeSectionsRequest(BaseModel):
    sections: List[int] = []


class RunJobRequest(BaseModel):
    area_id: str
    sections: List[int] = [1, 2, 3]
    cv_profile: Optional[str] = None
    workers: Optional[int] = 8
    reuse_rasters: bool = False
    dsm_res: Optional[float] = None
    min_area: Optional[float] = None
    imagery_zoom: int = 18


class SynthesizeCVRequest(BaseModel):
    profile_name: str = "custom_area"
    area_types: List[str] = ["industrial"]
    traits: List[str] = []
    imagery_gsd_m: float = 0.48


class SaveCVProfileRequest(BaseModel):
    profile_name: str
    yaml_text: str
    set_as_default: bool = False


class SaveSolarYamlRequest(BaseModel):
    yaml_text: str


# ---------------- Root UI ----------------

@app.get("/", response_class=HTMLResponse)
def serve_index():
    index_file = STATIC_DIR / "index.html"
    if not index_file.exists():
        return HTMLResponse("<h1>RayFlux Studio UI not built yet.</h1>", status_code=500)
    return HTMLResponse(index_file.read_text(encoding="utf-8"))


# ---------------- System Health & PostGIS ----------------

@app.get("/api/health")
def get_health():
    cfg = EcosystemConfig()
    pg_online = False
    try:
        import socket
        with socket.create_connection((cfg.postgis.host, cfg.postgis.port), timeout=0.6):
            pg_online = True
    except Exception:
        pg_online = False

    events_summary = studio_logger.read_events(limit=1)["counts"]
    return {
        "status": "ok",
        "postgis_online": pg_online,
        "postgis_host": cfg.postgis.host,
        "postgis_port": cfg.postgis.port,
        "postgis_database": cfg.postgis.database,
        "areas_count": len(area_registry.list_areas()),
        "log_counts": events_summary,
    }


@app.post("/api/postgis/start")
def start_postgis():
    try:
        cfg = EcosystemConfig()
        ensure_postgis_cluster_running()
        studio_logger.success(
            f"PostgreSQL/PostGIS started on {cfg.postgis.host}:{cfg.postgis.port}/{cfg.postgis.database}.",
            section="POSTGIS",
        )
        return {"started": True, "host": cfg.postgis.host, "port": cfg.postgis.port}
    except Exception as exc:
        studio_logger.error(f"Failed to start PostGIS: {exc}", section="POSTGIS")
        raise HTTPException(status_code=500, detail=str(exc))


# ---------------- Areas & Portfolio Statistics ----------------

@app.get("/api/areas")
def api_list_areas():
    return {"areas": area_registry.list_areas()}


@app.get("/api/portfolio/stats")
def api_portfolio_stats():
    return area_registry.get_portfolio_statistics()


@app.get("/api/areas/{area_id}/stats")
def api_area_stats(area_id: str, top_n: int = Query(50, ge=5, le=200)):
    try:
        return area_registry.get_area_statistics(area_id, top_n=top_n)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@app.post("/api/areas/draw")
def api_create_drawn_area(req: DrawnAreaRequest):
    try:
        created = area_registry.create_area_from_geojson(
            name=req.name,
            geojson_obj=req.geojson,
            area_types=req.area_types,
            traits=req.traits,
            description=req.description,
            cv_profile=req.cv_profile,
            auto_generate_cv_yaml=req.auto_generate_cv_yaml,
            imagery_gsd_m=req.imagery_gsd_m,
            dsm_resolution_m=req.dsm_resolution_m,
            min_building_area_m2=req.min_building_area_m2,
            footprint_mode=req.footprint_mode,
        )
        return {"area": created}
    except Exception as exc:
        studio_logger.error(f"Failed creating drawn area '{req.name}': {exc}", section="AREA_MANAGER")
        raise HTTPException(status_code=400, detail=str(exc))


@app.post("/api/areas/upload")
async def api_upload_area(
    name: str = Form(...),
    area_types: str = Form("mixed_urban"),
    traits: str = Form(""),
    description: str = Form(""),
    auto_generate_cv_yaml: bool = Form(True),
    imagery_gsd_m: float = Form(0.45),
    dsm_resolution_m: float = Form(0.50),
    min_building_area_m2: float = Form(50.0),
    footprint_mode: str = Form("auto"),
    files: List[UploadFile] = File(...),
):
    try:
        payload = []
        for uf in files:
            content = await uf.read()
            payload.append((uf.filename or "upload.geojson", content))
        a_types = [t.strip() for t in area_types.split(",") if t.strip()]
        t_list = [t.strip() for t in traits.split(",") if t.strip()]
        created = area_registry.create_area_from_uploaded_files(
            name=name,
            uploaded_files=payload,
            area_types=a_types,
            traits=t_list,
            description=description,
            auto_generate_cv_yaml=auto_generate_cv_yaml,
            imagery_gsd_m=imagery_gsd_m,
            dsm_resolution_m=dsm_resolution_m,
            min_building_area_m2=min_building_area_m2,
            footprint_mode=footprint_mode,
        )
        return {"area": created}
    except Exception as exc:
        studio_logger.error(f"Failed uploading area '{name}': {exc}", section="AREA_MANAGER")
        raise HTTPException(status_code=400, detail=str(exc))


@app.patch("/api/areas/{area_id}")
def api_update_area(area_id: str, req: UpdateAreaRequest):
    try:
        updates = {k: v for k, v in req.model_dump().items() if v is not None}
        return {"area": area_registry.update_area(area_id, updates)}
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@app.delete("/api/areas/{area_id}")
def api_delete_area(area_id: str):
    try:
        return area_registry.delete_area(area_id, drop_postgis=True)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


# ---------------- GIS Map Layers & Raster Overlays ----------------

@app.get("/api/map/areas")
def api_map_areas():
    return get_all_area_boundaries_geojson()


@app.get("/api/areas/{area_id}/layer/{layer_key}")
def api_area_layer(area_id: str, layer_key: str, simplify_m: float = 0.4, max_features: int = 8000):
    try:
        return get_area_vector_geojson(area_id, layer_key, simplify_m=simplify_m, max_features=max_features)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.get("/api/areas/{area_id}/raster-overlay/{raster_key}")
def api_raster_overlay(area_id: str, raster_key: str, max_dim: int = 1200):
    try:
        return render_raster_overlay_png(area_id, raster_key, max_dim=max_dim)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:
        studio_logger.error(f"Raster overlay failed ({raster_key}): {exc}", section="GIS", area_id=area_id)
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/api/raster-keys")
def api_raster_keys():
    return {
        "rasters": [{"key": k, "label": v[1]} for k, v in RASTER_KEYS.items()]
        + [{"key": f"monthly_m{m:02d}", "label": f"Monthly Irradiance M{m:02d}"} for m in range(1, 13)]
    }


# ---------------- CV Profile Builder & Solar Config ----------------

@app.get("/api/cv/options")
def api_cv_options():
    return {
        "area_types": [
            {"id": k, "label": v["label"], "description": v["description"]}
            for k, v in AREA_TYPE_ARCHETYPES.items()
        ],
        "traits": [
            {"id": k, "label": v["label"], "effect": v["effect"]}
            for k, v in ROOF_TRAIT_OPTIONS.items()
        ],
    }


@app.get("/api/cv/profiles")
def api_cv_profiles():
    return {"profiles": list_profiles()}


@app.post("/api/cv/synthesize")
def api_cv_synthesize(req: SynthesizeCVRequest):
    return synthesize_cv_config(
        area_types=req.area_types,
        traits=req.traits,
        imagery_gsd_m=req.imagery_gsd_m,
        profile_name=req.profile_name,
    )


@app.post("/api/cv/profiles/save")
def api_cv_save_profile(req: SaveCVProfileRequest):
    try:
        res = save_profile(req.profile_name, req.yaml_text, set_as_default=req.set_as_default)
        studio_logger.success(
            f"Saved CV YAML profile '{res['id']}' ({res['path']}, default={res['set_as_default']}).",
            section="CV_PROFILES",
        )
        return res
    except Exception as exc:
        studio_logger.error(f"Invalid CV YAML profile: {exc}", section="CV_PROFILES")
        raise HTTPException(status_code=400, detail=str(exc))


@app.get("/api/solar/config")
def api_get_solar_config():
    p = PROJECT_ROOT / "config" / "solar_parameters.yaml"
    return {"path": "config/solar_parameters.yaml", "yaml_text": p.read_text(encoding="utf-8") if p.exists() else ""}


@app.post("/api/solar/config")
def api_save_solar_config(req: SaveSolarYamlRequest):
    try:
        import yaml
        raw = yaml.safe_load(req.yaml_text)
        if not isinstance(raw, dict):
            raise ValueError("Solar YAML must be a valid mapping.")
        p = PROJECT_ROOT / "config" / "solar_parameters.yaml"
        p.write_text(req.yaml_text, encoding="utf-8")
        studio_logger.success("Updated config/solar_parameters.yaml.", section="SOLAR_CONFIG")
        return {"saved": True}
    except Exception as exc:
        studio_logger.error(f"Invalid Solar YAML: {exc}", section="SOLAR_CONFIG")
        raise HTTPException(status_code=400, detail=str(exc))


# ---------------- Pipeline Execution, Preflight & Selective Cleanup ----------------

@app.get("/api/areas/{area_id}/preflight")
def api_area_preflight(area_id: str, sections: str = Query("1,2,3")):
    try:
        sec_list = [int(s.strip()) for s in sections.split(",") if s.strip().isdigit()]
        return preflight_area_sections(area_id, sec_list)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@app.post("/api/areas/{area_id}/purge-sections")
def api_purge_sections(area_id: str, req: PurgeSectionsRequest):
    try:
        return purge_area_sections(area_id, req.sections)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:
        studio_logger.error(f"Section purge failed for '{area_id}': {exc}", section="CLEANUP", area_id=area_id)
        raise HTTPException(status_code=500, detail=str(exc))


@app.post("/api/jobs/run")
def api_run_job(req: RunJobRequest):
    try:
        job = job_manager.start_job(
            area_id=req.area_id,
            sections=req.sections,
            cv_profile=req.cv_profile,
            workers=req.workers,
            reuse_rasters=req.reuse_rasters,
            dsm_res=req.dsm_res,
            min_area=req.min_area,
            imagery_zoom=req.imagery_zoom,
        )
        return {"job": job}
    except Exception as exc:
        studio_logger.error(f"Could not start job: {exc}", section="PIPELINE", area_id=req.area_id)
        raise HTTPException(status_code=400, detail=str(exc))


@app.get("/api/jobs")
def api_list_jobs():
    return {"jobs": job_manager.list_jobs()}


@app.get("/api/jobs/{job_id}")
def api_get_job(job_id: str, log_offset: int = 0):
    try:
        return job_manager.get_job(job_id, log_offset=log_offset)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@app.post("/api/jobs/{job_id}/cancel")
def api_cancel_job(job_id: str):
    try:
        return job_manager.cancel_job(job_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


# ---------------- Data Management, Preview, Download & Delete ----------------

@app.get("/api/areas/{area_id}/data")
def api_area_data(area_id: str):
    try:
        return get_area_data_inventory(area_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@app.get("/api/areas/{area_id}/table-preview/{layer_name}")
def api_table_preview(area_id: str, layer_name: str, limit: int = 80):
    try:
        return preview_table_rows(area_id, layer_name, limit=limit)
    except Exception as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@app.get("/api/files/download")
def api_download_file(path: str = Query(...)):
    try:
        target = resolve_safe_project_file(path)
        if target.suffix.lower() == ".shp":
            zip_bytes = bundle_shapefile_zip(target)
            return Response(
                content=zip_bytes,
                media_type="application/zip",
                headers={"Content-Disposition": f'attachment; filename="{target.stem}_shapefile.zip"'},
            )
        return FileResponse(path=str(target), filename=target.name)
    except Exception as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@app.get("/api/files/inline")
def api_inline_file(path: str = Query(...)):
    try:
        target = resolve_safe_project_file(path)
        return FileResponse(path=str(target))
    except Exception as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@app.delete("/api/files/delete")
def api_delete_file(path: str = Query(...), area_id: Optional[str] = None):
    try:
        return delete_asset_file(path, area_id=area_id)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


# ---------------- Smart Logs, Errors & Warnings ----------------

@app.get("/api/logs")
def api_get_logs(
    level: str = Query("ALL"),
    search: Optional[str] = Query(None),
    area_id: str = Query("all"),
    limit: int = Query(300, ge=10, le=1000),
):
    data = studio_logger.read_events(level=level, search=search, area_id=area_id, limit=limit)
    data["audit_log"] = studio_logger.read_audit_log(limit=80)
    return data


@app.post("/api/logs/clear")
def api_clear_logs():
    studio_logger.clear_events()
    studio_logger.info("Cleared RayFlux Studio event log.", section="STUDIO")
    return {"cleared": True}
