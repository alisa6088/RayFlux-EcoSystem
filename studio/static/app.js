/* ============================================================================
   RayFlux Studio — Frontend Operations Controller
   ============================================================================ */

const STATE = {
  areas: [],
  activeAreaId: "area_default",
  portfolio: null,
  areaStats: null,
  cvOptions: null,
  cvProfiles: [],
  activeJobId: null,
  logOffset: 0,
  logFilter: "ALL",
  pollTimer: null,
  // Leaflet Map state
  map: null,
  drawnItems: null,
  drawnGeoJSON: null,
  boundariesLayer: null,
  vectorLayers: {},
  rasterOverlay: null,
  // Charts
  monthlyChart: null,
  giChart: null,
};

const MONTHS = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"];
const GI_COLORS = {
  "Hot Spot (99%)": "#dc2626",
  "Hot Spot (95%)": "#f97316",
  "Hot Spot (90%)": "#facc15",
  "Not Significant": "#64748b",
  "Cold Spot (90%)": "#7dd3fc",
  "Cold Spot (95%)": "#3b82f6",
  "Cold Spot (99%)": "#1d4ed8",
};

/* ---------------- Utilities ---------------- */

function toast(msg, kind = "info") {
  const c = document.getElementById("toastContainer");
  const el = document.createElement("div");
  el.className = `toast ${kind === "error" ? "err" : kind === "ok" ? "ok" : ""}`;
  el.textContent = msg;
  c.appendChild(el);
  setTimeout(() => el.remove(), 4500);
}

async function api(url, opts = {}) {
  const res = await fetch(url, opts);
  const text = await res.text();
  let data;
  try { data = JSON.parse(text); } catch { data = { detail: text }; }
  if (!res.ok) {
    throw new Error(data.detail || `HTTP ${res.status}`);
  }
  return data;
}

function fmtNum(v, dec = 1) {
  if (v === null || v === undefined || isNaN(v)) return "0";
  return Number(v).toLocaleString(undefined, { minimumFractionDigits: dec, maximumFractionDigits: dec });
}

function openModal(title, html) {
  document.getElementById("modalTitle").textContent = title;
  document.getElementById("modalBody").innerHTML = html;
  document.getElementById("previewModal").classList.add("open");
}

function closeModal() {
  document.getElementById("previewModal").classList.remove("open");
}

function switchTab(tabName, logFilterOpt = null) {
  document.querySelectorAll(".tab-pane").forEach((el) => el.classList.remove("active"));
  document.querySelectorAll(".nav-btn").forEach((el) => el.classList.remove("active"));
  const pane = document.getElementById(`tab-${tabName}`);
  if (pane) pane.classList.add("active");
  const btn = document.querySelector(`.nav-btn[data-tab="${tabName}"]`);
  if (btn) btn.classList.add("active");

  if (tabName === "map") {
    initMapIfNeeded();
    setTimeout(() => STATE.map && STATE.map.invalidateSize(), 120);
  } else if (tabName === "data") {
    loadDataInventory();
  } else if (tabName === "logs") {
    if (logFilterOpt) STATE.logFilter = logFilterOpt;
    loadLogs();
  } else if (tabName === "runner") {
    loadJobsHistory();
  } else if (tabName === "cv") {
    loadCvProfiles();
    loadSolarYaml();
  }
}

/* ---------------- Health & PostGIS ---------------- */

async function loadHealth() {
  try {
    const h = await api("/api/health");
    const pill = document.getElementById("pgStatusPill");
    if (h.postgis_online) {
      pill.className = "pill pill-ok";
      pill.textContent = `PostGIS Online (:${h.postgis_port})`;
    } else {
      pill.className = "pill pill-warn";
      pill.textContent = `PostGIS Standby (:${h.postgis_port})`;
    }
    document.getElementById("errBadge").textContent = `Errors: ${h.log_counts.ERROR || 0}`;
    document.getElementById("warnBadge").textContent = `Warnings: ${h.log_counts.WARNING || 0}`;
  } catch (e) {
    console.error(e);
  }
}

async function startPostGIS() {
  try {
    toast("Starting PostgreSQL/PostGIS server...", "info");
    await api("/api/postgis/start", { method: "POST" });
    toast("PostgreSQL/PostGIS is online!", "ok");
    await loadHealth();
    await loadDataInventory();
  } catch (e) {
    toast(`PostGIS error: ${e.message}`, "error");
  }
}

/* ---------------- Areas & Overview Statistics ---------------- */

async function loadAreas() {
  const res = await api("/api/areas");
  STATE.areas = res.areas || [];
  const sel = document.getElementById("globalAreaSelect");
  const runSel = document.getElementById("runAreaSelect");
  const prev = STATE.activeAreaId;

  const optsHtml = STATE.areas.map(
    (a) => `<option value="${a.area_id}">${a.name} (${a.section_status.buildings_count.toLocaleString()} bldgs)</option>`
  ).join("");
  sel.innerHTML = optsHtml;
  runSel.innerHTML = optsHtml;

  if (STATE.areas.some((a) => a.area_id === prev)) {
    STATE.activeAreaId = prev;
  } else if (STATE.areas.length > 0) {
    STATE.activeAreaId = STATE.areas[0].area_id;
  }
  sel.value = STATE.activeAreaId;
  runSel.value = STATE.activeAreaId;
}

async function loadOverview() {
  const [port, areaStats] = await Promise.all([
    api("/api/portfolio/stats"),
    api(`/api/areas/${STATE.activeAreaId}/stats?top_n=80`),
  ]);
  STATE.portfolio = port;
  STATE.areaStats = areaStats;

  document.getElementById("statsScopePill").textContent = areaStats.name;

  // KPI Grid
  const hotTotal = Object.entries(areaStats.gi_clusters || {})
    .filter(([k]) => k.startsWith("Hot Spot"))
    .reduce((acc, [, v]) => acc + v, 0);

  const kpis = [
    { label: "Active Areas (Portfolio)", value: port.total_areas, sub: `Total Portfolio: ${fmtNum(port.total_annual_gwh, 1)} GWh/yr` },
    { label: "Buildings (Active Area)", value: areaStats.buildings_count.toLocaleString(), sub: `Extent: ${fmtNum(areaStats.area_km2, 2)} km² · ${areaStats.target_crs}` },
    { label: "Net Usable Roof Area", value: `${fmtNum(areaStats.usable_area_m2 / 1e4, 2)} ha`, sub: `${fmtNum(areaStats.usable_pct, 1)}% of ${fmtNum(areaStats.gross_area_m2 / 1e4, 2)} ha gross` },
    { label: "Obstacles Removed (S2)", value: areaStats.obstacle_count.toLocaleString(), sub: `${fmtNum(areaStats.obstacle_area_m2 / 1e4, 2)} ha subtracted` },
    { label: "Installed PV Capacity", value: `${fmtNum(areaStats.installed_capacity_mwp, 2)} MWp`, sub: `Mean Flux: ${fmtNum(areaStats.mean_irradiance_kwhm2, 0)} kWh/m²/yr` },
    { label: "Annual PV Generation", value: `${fmtNum(areaStats.annual_elec_gwh, 2)} GWh/yr`, sub: `Mean: ${fmtNum(areaStats.mean_bldg_elec_mwh, 1)} MWh/bldg · ${hotTotal} Hot Spots` },
  ];
  document.getElementById("kpiGrid").innerHTML = kpis.map((k) => `
    <div class="kpi-card">
      <div class="kpi-label">${k.label}</div>
      <div class="kpi-value">${k.value}</div>
      <div class="kpi-sub">${k.sub}</div>
    </div>
  `).join("");

  // Monthly Chart
  const mCtx = document.getElementById("monthlyChart").getContext("2d");
  if (STATE.monthlyChart) STATE.monthlyChart.destroy();
  STATE.monthlyChart = new Chart(mCtx, {
    type: "bar",
    data: {
      labels: MONTHS,
      datasets: [{
        label: "PV Yield (GWh/month)",
        data: areaStats.monthly_elec_gwh,
        backgroundColor: "rgba(16, 185, 129, 0.82)",
        borderColor: "#34d399",
        borderWidth: 1,
        borderRadius: 5,
      }],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: { legend: { display: false } },
      scales: {
        x: { ticks: { color: "#94a3b8" }, grid: { color: "#1e293b" } },
        y: { ticks: { color: "#94a3b8" }, grid: { color: "#1e293b" }, title: { display: true, text: "GWh", color: "#94a3b8" } },
      },
    },
  });

  // Gi* Cluster Chart
  const giEntries = Object.entries(areaStats.gi_clusters || {});
  const gCtx = document.getElementById("giChart").getContext("2d");
  if (STATE.giChart) STATE.giChart.destroy();
  STATE.giChart = new Chart(gCtx, {
    type: "doughnut",
    data: {
      labels: giEntries.length ? giEntries.map(([k]) => k) : ["No S3 Data Yet"],
      datasets: [{
        data: giEntries.length ? giEntries.map(([, v]) => v) : [1],
        backgroundColor: giEntries.length ? giEntries.map(([k]) => GI_COLORS[k] || "#475569") : ["#334155"],
        borderColor: "#0f172a",
        borderWidth: 2,
      }],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: { legend: { position: "right", labels: { color: "#cbd5e1", font: { size: 11 } } } },
    },
  });

  // Multi-Area Summary Table
  const badge = (ok) => ok ? `<span class="pill pill-ok">OK</span>` : `<span class="pill pill-warn">—</span>`;
  document.getElementById("areasSummaryBody").innerHTML = port.areas.map((a) => `
    <tr>
      <td><b>${a.name}</b><br/><span style="color:#64748b;font-size:11px;">${a.area_id}</span></td>
      <td>${(a.area_types || []).join(", ")}</td>
      <td>${fmtNum(a.area_km2, 2)}</td>
      <td>${a.target_crs}</td>
      <td>${badge(a.section_status.section1)}</td>
      <td>${badge(a.section_status.section2)}</td>
      <td>${badge(a.section_status.section3)}</td>
      <td>${a.buildings_count.toLocaleString()}</td>
      <td>${fmtNum(a.usable_area_m2 / 1e4, 2)}</td>
      <td>${fmtNum(a.installed_capacity_mwp, 2)}</td>
      <td><b>${fmtNum(a.annual_elec_gwh, 2)}</b></td>
      <td class="flex-row">
        <button class="btn btn-sm btn-primary" onclick="selectAndMapArea('${a.area_id}')">Map</button>
        <button class="btn btn-sm btn-success" onclick="openRunnerForArea('${a.area_id}')">Run</button>
        ${a.area_id !== "area_default" ? `<button class="btn btn-sm btn-danger" onclick="deleteArea('${a.area_id}')">Del</button>` : ""}
      </td>
    </tr>
  `).join("");

  renderTopBuildingsTable();
}

function renderTopBuildingsTable() {
  const q = (document.getElementById("bldgSearchInput").value || "").toLowerCase();
  const rows = (STATE.areaStats?.top_buildings || []).filter((r) =>
    !q || String(r.building_id).includes(q) || (r.gi_cluster_class || "").toLowerCase().includes(q)
  );
  document.getElementById("topBuildingsBody").innerHTML = rows.map((r) => {
    const c = GI_COLORS[r.gi_cluster_class] || "#64748b";
    return `
      <tr>
        <td><b>#${r.building_id}</b></td>
        <td>${fmtNum(r.gross_area_m2, 1)}</td>
        <td>${fmtNum(r.usable_area_m2, 1)}</td>
        <td>${fmtNum(r.usable_area_pct, 1)}%</td>
        <td>${r.obstacle_count}</td>
        <td>${fmtNum(r.mean_kwh_m2_yr, 1)}</td>
        <td>${fmtNum(r.installed_capacity_kwp, 1)}</td>
        <td><b>${fmtNum(r.elec_yield_mwh_yr, 1)}</b></td>
        <td><span class="pill" style="background:${c}25;color:${c};border-color:${c}66;">${r.gi_cluster_class}</span></td>
        <td><button class="btn btn-sm btn-primary" onclick="locateBuilding(${r.lat}, ${r.lon}, ${r.building_id})">Locate</button></td>
      </tr>
    `;
  }).join("");
}

function selectAndMapArea(areaId) {
  STATE.activeAreaId = areaId;
  document.getElementById("globalAreaSelect").value = areaId;
  switchTab("map");
  zoomToActiveArea();
}

function openRunnerForArea(areaId) {
  STATE.activeAreaId = areaId;
  document.getElementById("globalAreaSelect").value = areaId;
  document.getElementById("runAreaSelect").value = areaId;
  syncRunnerProfileForArea();
  switchTab("runner");
}

async function deleteArea(areaId) {
  if (!confirm(`Delete area '${areaId}', its files, and drop its PostGIS schema?`)) return;
  try {
    await api(`/api/areas/${areaId}`, { method: "DELETE" });
    toast(`Deleted area '${areaId}'.`, "ok");
    await refreshAll();
  } catch (e) {
    toast(e.message, "error");
  }
}

/* ---------------- Interactive GIS Map (Leaflet + Leaflet.Draw) ---------------- */

function initMapIfNeeded() {
  if (STATE.map) return;
  const esriSat = L.tileLayer(
    "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
    { attribution: "Esri World Imagery", maxZoom: 19 }
  );
  const darkMap = L.tileLayer(
    "https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png",
    { attribution: "CartoDB Dark", maxZoom: 19 }
  );
  const osm = L.tileLayer(
    "https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png",
    { attribution: "OpenStreetMap", maxZoom: 19 }
  );

  STATE.map = L.map("gisMap", { center: [35.7075, 50.2981], zoom: 13, layers: [esriSat] });
  L.control.layers({ "Esri Satellite": esriSat, "Dark Matter": darkMap, "OpenStreetMap": osm }).addTo(STATE.map);

  STATE.drawnItems = new L.FeatureGroup().addTo(STATE.map);
  const drawCtrl = new L.Control.Draw({
    edit: { featureGroup: STATE.drawnItems },
    draw: {
      polygon: { allowIntersection: false, showArea: true, shapeOptions: { color: "#38bdf8", weight: 2.5 } },
      rectangle: { shapeOptions: { color: "#10b981", weight: 2.5 } },
      polyline: false, circle: false, marker: false, circlemarker: false,
    },
  });
  STATE.map.addControl(drawCtrl);

  STATE.map.on(L.Draw.Event.CREATED, (e) => {
    STATE.drawnItems.clearLayers();
    STATE.drawnItems.addLayer(e.layer);
    STATE.drawnGeoJSON = e.layer.toGeoJSON();
    const badge = document.getElementById("drawnStatusBadge");
    badge.style.display = "inline-flex";
    badge.textContent = "Polygon drawn on map — ready to Save!";
    toast("Boundary drawn on map! Enter an Area Name and click Save.", "ok");
  });

  STATE.map.on(L.Draw.Event.DELETED, () => {
    STATE.drawnGeoJSON = null;
    document.getElementById("drawnStatusBadge").style.display = "none";
  });

  loadAllBoundariesOnMap();
  populateRasterKeysDropdown();
}

async function loadAllBoundariesOnMap() {
  if (!STATE.map) return;
  if (STATE.boundariesLayer) {
    STATE.map.removeLayer(STATE.boundariesLayer);
    STATE.boundariesLayer = null;
  }
  if (!document.getElementById("chkBoundaries").checked) return;
  try {
    const fc = await api("/api/map/areas");
    STATE.boundariesLayer = L.geoJSON(fc, {
      style: (f) => ({
        color: f.properties.area_id === STATE.activeAreaId ? "#38bdf8" : "#f59e0b",
        weight: f.properties.area_id === STATE.activeAreaId ? 3 : 2,
        fillOpacity: 0.08,
        dashArray: f.properties.area_id === STATE.activeAreaId ? null : "6 4",
      }),
      onEachFeature: (f, layer) => {
        const p = f.properties;
        layer.bindPopup(
          `<b>${p.name}</b><br/>ID: ${p.area_id}<br/>Types: ${p.area_types}<br/>` +
          `Area: ${p.area_km2} km² (${p.target_crs})<br/>Buildings: ${p.buildings_count}`
        );
        layer.on("click", () => {
          STATE.activeAreaId = p.area_id;
          document.getElementById("globalAreaSelect").value = p.area_id;
        });
      },
    }).addTo(STATE.map);
    if (fc.features && fc.features.length > 0) {
      zoomToActiveArea();
    }
  } catch (e) {
    toast(`Boundaries error: ${e.message}`, "error");
  }
}

function toggleBoundariesLayer() {
  loadAllBoundariesOnMap();
}

function zoomToActiveArea() {
  if (!STATE.map) return;
  const area = STATE.areas.find((a) => a.area_id === STATE.activeAreaId);
  if (area && area.bounds_wgs84) {
    const [w, s, e, n] = area.bounds_wgs84;
    STATE.map.fitBounds([[s, w], [n, e]], { padding: [25, 25] });
  }
}

function locateBuilding(lat, lon, bldgId) {
  switchTab("map");
  setTimeout(async () => {
    STATE.map.setView([lat, lon], 18);
    if (!document.getElementById("chkHotspots").checked) {
      document.getElementById("chkHotspots").checked = true;
      await toggleVectorLayer("hotspots");
    }
    L.popup().setLatLng([lat, lon]).setContent(`<b>Building #${bldgId}</b>`).openOn(STATE.map);
  }, 200);
}

function styleForLayer(layerKey, feature) {
  const p = feature.properties || {};
  if (layerKey === "footprints") return { color: "#94a3b8", weight: 1, fillOpacity: 0.25 };
  if (layerKey === "usable_rooftops") return { color: "#10b981", weight: 1, fillOpacity: 0.45 };
  if (layerKey === "obstacles") return { color: "#ef4444", weight: 0.8, fillOpacity: 0.78 };
  if (layerKey === "shadows") return { color: "#2563eb", weight: 0.5, fillOpacity: 0.50 };
  if (layerKey === "hotspots") {
    const c = GI_COLORS[p.gi_cluster_class] || "#64748b";
    return { color: "#0f172a", fillColor: c, weight: 0.6, fillOpacity: p.gi_cluster_class === "Not Significant" ? 0.35 : 0.85 };
  }
  if (layerKey === "hotspots_yield") {
    const v = Number(p.elec_yield_mwh_yr || 0);
    const col = v >= 2000 ? "#fef08a" : v >= 800 ? "#f59e0b" : v >= 300 ? "#ea580c" : v >= 100 ? "#db2777" : "#6d28d9";
    return { color: "#0f172a", fillColor: col, weight: 0.5, fillOpacity: 0.85 };
  }
  return { color: "#38bdf8", weight: 1, fillOpacity: 0.3 };
}

function popupHtmlForFeature(p) {
  const rows = [];
  if (p.building_id !== undefined) rows.push(`<b>Building #${p.building_id}</b>`);
  if (p.obj_class) rows.push(`Class: <b>${p.obj_class}</b> (${fmtNum(p.area_m2, 1)} m²)`);
  if (p.building_height_m !== undefined) rows.push(`Height: ${fmtNum(p.building_height_m, 1)} m`);
  if (p.gross_area_m2 !== undefined) rows.push(`Gross Roof: ${fmtNum(p.gross_area_m2, 1)} m²`);
  if (p.usable_area_m2 !== undefined) rows.push(`Usable Roof: <b>${fmtNum(p.usable_area_m2, 1)} m²</b> (${fmtNum(p.usable_area_pct, 1)}%)`);
  if (p.obstacle_count !== undefined) rows.push(`Obstacles: ${p.obstacle_count} (${fmtNum(p.obstacle_area_m2, 1)} m²)`);
  if (p.mean_kwh_m2_yr !== undefined) rows.push(`Irradiance: ${fmtNum(p.mean_kwh_m2_yr, 1)} kWh/m²/yr`);
  if (p.installed_capacity_kwp !== undefined) rows.push(`PV Capacity: <b>${fmtNum(p.installed_capacity_kwp, 1)} kWp</b>`);
  if (p.elec_yield_mwh_yr !== undefined) rows.push(`Annual Yield: <b>${fmtNum(p.elec_yield_mwh_yr, 1)} MWh/yr</b>`);
  if (p.gi_cluster_class) rows.push(`Gi* Cluster: <b>${p.gi_cluster_class}</b> (Z=${fmtNum(p.gi_z_score, 2)})`);
  return rows.join("<br/>");
}

async function toggleVectorLayer(layerKey) {
  initMapIfNeeded();
  const chkMap = {
    footprints: "chkFootprints",
    usable_rooftops: "chkUsable",
    obstacles: "chkObstacles",
    shadows: "chkShadows",
    hotspots_yield: "chkYield",
    hotspots: "chkHotspots",
  };
  const checked = document.getElementById(chkMap[layerKey]).checked;

  if (STATE.vectorLayers[layerKey]) {
    STATE.map.removeLayer(STATE.vectorLayers[layerKey]);
    delete STATE.vectorLayers[layerKey];
  }
  if (!checked) return;

  const backendKey = layerKey === "hotspots_yield" ? "hotspots" : layerKey;
  try {
    toast(`Loading ${layerKey} layer...`, "info");
    const fc = await api(`/api/areas/${STATE.activeAreaId}/layer/${backendKey}?simplify_m=0.5&max_features=8000`);
    if (!fc.features || fc.features.length === 0) {
      toast(`No features found for ${layerKey} in this area. Run the corresponding section first.`, "error");
      document.getElementById(chkMap[layerKey]).checked = false;
      return;
    }
    STATE.vectorLayers[layerKey] = L.geoJSON(fc, {
      style: (f) => styleForLayer(layerKey, f),
      onEachFeature: (f, lyr) => lyr.bindPopup(popupHtmlForFeature(f.properties || {})),
    }).addTo(STATE.map);
    toast(`Loaded ${fc.count.toLocaleString()} features (${layerKey}).`, "ok");
  } catch (e) {
    toast(`Layer load error: ${e.message}`, "error");
    document.getElementById(chkMap[layerKey]).checked = false;
  }
}

async function populateRasterKeysDropdown() {
  const res = await api("/api/raster-keys");
  const sel = document.getElementById("rasterOverlaySelect");
  sel.innerHTML = `<option value="">-- None (Basemap Only) --</option>` +
    res.rasters.map((r) => `<option value="${r.key}">${r.label}</option>`).join("");
}

async function loadRasterOverlay(forceKey = null) {
  initMapIfNeeded();
  const sel = document.getElementById("rasterOverlaySelect");
  if (forceKey !== null) sel.value = forceKey;
  const rkey = sel.value;

  if (STATE.rasterOverlay) {
    STATE.map.removeLayer(STATE.rasterOverlay);
    STATE.rasterOverlay = null;
  }
  document.getElementById("rasterRangeNote").textContent = "";
  if (!rkey) return;

  try {
    toast(`Rendering ${rkey} raster overlay...`, "info");
    const res = await api(`/api/areas/${STATE.activeAreaId}/raster-overlay/${rkey}`);
    const opacity = Number(document.getElementById("rasterOpacity").value) / 100.0;
    STATE.rasterOverlay = L.imageOverlay(res.data_url, res.bounds, { opacity }).addTo(STATE.map);
    STATE.map.fitBounds(res.bounds, { padding: [20, 20] });
    document.getElementById("rasterRangeNote").textContent = `${res.label} | Range: ${res.vmin} – ${res.vmax}`;
    toast(`Overlay active: ${res.label}`, "ok");
  } catch (e) {
    toast(`Raster overlay unavailable: ${e.message}`, "error");
    sel.value = "";
  }
}

function updateRasterOpacity() {
  const val = Number(document.getElementById("rasterOpacity").value);
  document.getElementById("rasterOpacityVal").textContent = `${val}%`;
  if (STATE.rasterOverlay) STATE.rasterOverlay.setOpacity(val / 100.0);
}

/* ---------------- Create New Area (Draw OR Upload) ---------------- */

function getCheckedValues(containerId) {
  return Array.from(document.querySelectorAll(`#${containerId} input:checked`)).map((el) => el.value);
}

async function saveNewArea(runImmediately = false) {
  const name = (document.getElementById("newAreaName").value || "").trim();
  if (!name) {
    toast("Please enter an Area Name first.", "error");
    return;
  }
  const files = document.getElementById("newAreaFiles").files;
  const areaTypes = getCheckedValues("mapAreaTypeChecks");
  const traits = getCheckedValues("mapTraitChecks");
  const gsd = Number(document.getElementById("newAreaGsd").value || 0.45);
  const dsmRes = Number(document.getElementById("newAreaDsmRes").value || 0.50);

  let createdArea = null;
  try {
    if (files && files.length > 0) {
      const fd = new FormData();
      fd.append("name", name);
      fd.append("area_types", (areaTypes.length ? areaTypes : ["mixed_urban"]).join(","));
      fd.append("traits", traits.join(","));
      fd.append("auto_generate_cv_yaml", "true");
      fd.append("imagery_gsd_m", String(gsd));
      fd.append("dsm_resolution_m", String(dsmRes));
      for (const f of files) fd.append("files", f);
      const res = await api("/api/areas/upload", { method: "POST", body: fd });
      createdArea = res.area;
    } else if (STATE.drawnGeoJSON) {
      const res = await api("/api/areas/draw", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          name,
          geojson: STATE.drawnGeoJSON,
          area_types: areaTypes.length ? areaTypes : ["mixed_urban"],
          traits,
          auto_generate_cv_yaml: true,
          imagery_gsd_m: gsd,
          dsm_resolution_m: dsmRes,
        }),
      });
      createdArea = res.area;
    } else {
      toast("Either draw a polygon on the map OR upload a Shapefile / GeoJSON first.", "error");
      return;
    }

    toast(`Created area '${createdArea.name}' with optimized CV YAML (${createdArea.cv_profile})!`, "ok");
    STATE.activeAreaId = createdArea.area_id;
    STATE.drawnGeoJSON = null;
    if (STATE.drawnItems) STATE.drawnItems.clearLayers();
    document.getElementById("drawnStatusBadge").style.display = "none";
    document.getElementById("newAreaName").value = "";
    document.getElementById("newAreaFiles").value = "";

    await refreshAll();
    if (runImmediately) {
      switchTab("runner");
      document.getElementById("runAreaSelect").value = createdArea.area_id;
      document.getElementById("runCvProfile").value = createdArea.cv_profile || "default";
      document.getElementById("runS1").checked = true;
      document.getElementById("runS2").checked = true;
      document.getElementById("runS3").checked = true;
      await launchPipeline();
    }
  } catch (e) {
    toast(`Area creation failed: ${e.message}`, "error");
  }
}

/* ---------------- Smart CV & Solar YAML Studio ---------------- */

async function loadCvOptions() {
  const opts = await api("/api/cv/options");
  STATE.cvOptions = opts;

  const renderTypeChecks = (containerId, compact = false) => {
    document.getElementById(containerId).innerHTML = opts.area_types.map((t) => `
      <label class="check-item" title="${t.description}">
        <input type="checkbox" value="${t.id}" ${t.id === "industrial" ? "checked" : ""} />
        <div>
          <b>${compact ? t.id.replace("_", " ") : t.label}</b>
          ${compact ? "" : `<div style="font-size:11px;color:#94a3b8;">${t.description}</div>`}
        </div>
      </label>
    `).join("");
  };

  const renderTraitChecks = (containerId, compact = false) => {
    document.getElementById(containerId).innerHTML = opts.traits.map((t) => `
      <label class="check-item" title="${t.effect}">
        <input type="checkbox" value="${t.id}" />
        <div>
          <span>${compact ? t.id.replace(/_/g, " ") : t.label}</span>
          ${compact ? "" : `<div style="font-size:11px;color:#94a3b8;">${t.effect}</div>`}
        </div>
      </label>
    `).join("");
  };

  renderTypeChecks("cvAreaTypesContainer", false);
  renderTraitChecks("cvTraitsContainer", false);
  renderTypeChecks("mapAreaTypeChecks", true);
  renderTraitChecks("mapTraitChecks", true);
}

async function loadCvProfiles() {
  const res = await api("/api/cv/profiles");
  STATE.cvProfiles = res.profiles || [];

  const runSel = document.getElementById("runCvProfile");
  runSel.innerHTML = STATE.cvProfiles.map((p) => `<option value="${p.id}">${p.name}</option>`).join("");
  syncRunnerProfileForArea();

  document.getElementById("savedProfilesList").innerHTML = STATE.cvProfiles.map((p) => `
    <div class="check-item" style="justify-content:space-between;align-items:center;">
      <div>
        <b>${p.name}</b>
        <div style="font-size:11px;color:#64748b;">${p.path}</div>
      </div>
      <button class="btn btn-sm" onclick="editSavedProfile('${p.id}')">Load</button>
    </div>
  `).join("");

  if (!document.getElementById("cvYamlEditor").value && STATE.cvProfiles.length > 0) {
    document.getElementById("cvYamlEditor").value = STATE.cvProfiles[0].yaml_text;
  }
}

function editSavedProfile(profileId) {
  const p = STATE.cvProfiles.find((x) => x.id === profileId);
  if (!p) return;
  document.getElementById("cvProfileName").value = p.id === "default" ? "custom_default" : p.id;
  document.getElementById("cvYamlEditor").value = p.yaml_text;
  toast(`Loaded profile '${p.name}' into editor.`, "info");
}

async function generateCvYaml() {
  const areaTypes = getCheckedValues("cvAreaTypesContainer");
  const traits = getCheckedValues("cvTraitsContainer");
  const gsd = Number(document.getElementById("cvGsdSlider").value || 0.48);
  const name = document.getElementById("cvProfileName").value || "custom_area";

  const res = await api("/api/cv/synthesize", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ profile_name: name, area_types: areaTypes, traits, imagery_gsd_m: gsd }),
  });
  document.getElementById("cvYamlEditor").value = res.yaml_text;
  toast(`Generated calibrated YAML for [${res.area_types.join(", ")}] @ ${res.imagery_gsd_m} m/px.`, "ok");
}

async function saveCvProfile(setAsDefault) {
  const name = (document.getElementById("cvProfileName").value || "").trim() || "custom_profile";
  const yamlText = document.getElementById("cvYamlEditor").value;
  try {
    const res = await api("/api/cv/profiles/save", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ profile_name: name, yaml_text: yamlText, set_as_default: setAsDefault }),
    });
    toast(`Saved validated profile '${res.id}'${setAsDefault ? " & set as default" : ""}!`, "ok");
    await loadCvProfiles();
  } catch (e) {
    toast(`YAML validation failed: ${e.message}`, "error");
  }
}

async function assignCvToActiveArea() {
  const name = (document.getElementById("cvProfileName").value || "").trim() || "default";
  try {
    await saveCvProfile(false);
    await api(`/api/areas/${STATE.activeAreaId}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ cv_profile: name }),
    });
    toast(`Assigned CV profile '${name}' to active area '${STATE.activeAreaId}'.`, "ok");
    await loadAreas();
  } catch (e) {
    toast(e.message, "error");
  }
}

async function loadSolarYaml() {
  const res = await api("/api/solar/config");
  document.getElementById("solarYamlEditor").value = res.yaml_text || "";
}

async function saveSolarYaml() {
  try {
    await api("/api/solar/config", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ yaml_text: document.getElementById("solarYamlEditor").value }),
    });
    toast("Saved config/solar_parameters.yaml!", "ok");
  } catch (e) {
    toast(`Invalid Solar YAML: ${e.message}`, "error");
  }
}

/* ---------------- Pipeline Runner & Live Progress ---------------- */

function syncRunnerProfileForArea() {
  const areaId = document.getElementById("runAreaSelect").value;
  const area = STATE.areas.find((a) => a.area_id === areaId);
  if (area && area.cv_profile) {
    const sel = document.getElementById("runCvProfile");
    if (Array.from(sel.options).some((o) => o.value === area.cv_profile)) {
      sel.value = area.cv_profile;
    }
  }
}

async function launchPipeline() {
  const areaId = document.getElementById("runAreaSelect").value;
  const sections = [];
  if (document.getElementById("runS1").checked) sections.push(1);
  if (document.getElementById("runS2").checked) sections.push(2);
  if (document.getElementById("runS3").checked) sections.push(3);
  if (!sections.length) {
    toast("Select at least one section (S1, S2, or S3).", "error");
    return;
  }

  try {
    const res = await api("/api/jobs/run", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        area_id: areaId,
        sections,
        cv_profile: document.getElementById("runCvProfile").value || "default",
      }),
    });
    STATE.activeJobId = res.job.job_id;
    STATE.logOffset = 0;
    document.getElementById("liveTerminal").innerHTML = "";
    toast(`Started job ${STATE.activeJobId} on ${areaId}.`, "ok");
    startJobPolling();
  } catch (e) {
    toast(e.message, "error");
  }
}

async function cancelActiveJob() {
  if (!STATE.activeJobId) return;
  try {
    await api(`/api/jobs/${STATE.activeJobId}/cancel`, { method: "POST" });
    toast("Cancel signal sent to running job.", "info");
  } catch (e) {
    toast(e.message, "error");
  }
}

function startJobPolling() {
  if (STATE.pollTimer) clearInterval(STATE.pollTimer);
  const tick = async () => {
    if (!STATE.activeJobId) return;
    try {
      const j = await api(`/api/jobs/${STATE.activeJobId}?log_offset=${STATE.logOffset}`);
      STATE.logOffset = j.total_log_lines;

      document.getElementById("jobIdText").textContent = j.job_id;
      document.getElementById("jobElapsedText").textContent = `${j.elapsed_sec}s`;
      document.getElementById("jobPctText").textContent = `${j.progress_pct}%`;
      document.getElementById("jobProgressFill").style.width = `${j.progress_pct}%`;
      document.getElementById("jobStageText").textContent = j.current_stage;
      document.getElementById("jobWarnText").textContent = j.warning_count;
      document.getElementById("jobErrText").textContent = j.error_count;

      const sp = document.getElementById("jobStatusPill");
      sp.textContent = j.status.toUpperCase();
      sp.className = `pill ${j.status === "completed" ? "pill-ok" : j.status === "failed" ? "pill-err" : j.status === "running" ? "pill-info" : "pill-warn"}`;

      const mini = document.getElementById("miniJobPill");
      if (j.status === "running") {
        mini.classList.add("active");
        document.getElementById("miniJobText").textContent = `S${j.current_section} ${j.progress_pct}%`;
        document.getElementById("miniJobFill").style.width = `${j.progress_pct}%`;
        document.getElementById("btnStartJob").disabled = true;
        document.getElementById("btnCancelJob").disabled = false;
      } else {
        mini.classList.remove("active");
        document.getElementById("btnStartJob").disabled = false;
        document.getElementById("btnCancelJob").disabled = true;
      }

      if (j.logs && j.logs.length > 0) {
        const term = document.getElementById("liveTerminal");
        for (const row of j.logs) {
          const div = document.createElement("div");
          div.className = `log-line-${row.level}`;
          div.textContent = `[${row.ts}] ${row.text}`;
          term.appendChild(div);
        }
        term.scrollTop = term.scrollHeight;
      }

      if (j.status !== "running") {
        clearInterval(STATE.pollTimer);
        STATE.pollTimer = null;
        await refreshAll();
        await loadJobsHistory();
        toast(`Job ${j.job_id} ${j.status}!`, j.status === "completed" ? "ok" : "error");
      }
    } catch (e) {
      console.error(e);
    }
  };
  tick();
  STATE.pollTimer = setInterval(tick, 1200);
}

async function loadJobsHistory() {
  const res = await api("/api/jobs");
  const jobs = res.jobs || [];
  document.getElementById("jobsHistoryBody").innerHTML = jobs.map((j) => `
    <tr>
      <td><b>${j.job_id}</b></td>
      <td>${j.area_id}</td>
      <td>S${j.sections.join(", S")}</td>
      <td>${j.cv_profile}</td>
      <td><span class="pill ${j.status === "completed" ? "pill-ok" : j.status === "failed" ? "pill-err" : "pill-info"}">${j.status}</span></td>
      <td>${j.progress_pct}%</td>
      <td>${j.elapsed_sec}s</td>
      <td>${j.error_count}</td>
    </tr>
  `).join("");
}

/* ---------------- Data Management & Explorer ---------------- */

async function loadDataInventory() {
  try {
    const inv = await api(`/api/areas/${STATE.activeAreaId}/data`);
    document.getElementById("dataPgSchema").textContent = inv.postgis_schema;
    const st = document.getElementById("dataPgState");
    st.textContent = inv.postgis_online ? `Connected (${inv.postgis_tables.length} tables)` : "PostGIS Standby";
    st.className = `pill ${inv.postgis_online ? "pill-ok" : "pill-warn"}`;

    document.getElementById("pgTablesBody").innerHTML = inv.postgis_tables.length
      ? inv.postgis_tables.map((t) => `
        <tr>
          <td>${t.schema}</td><td><b>${t.table}</b></td><td>${t.rows.toLocaleString()}</td><td>${t.size}</td>
          <td><button class="btn btn-sm btn-primary" onclick="previewTable('${t.table}')">Preview Rows</button></td>
        </tr>`).join("")
      : `<tr><td colspan="5" style="color:#94a3b8;">No PostGIS tables found for schema '${inv.postgis_schema}'. Start PostGIS or run pipeline.</td></tr>`;

    document.getElementById("rastersBody").innerHTML = inv.rasters.map((r) => `
      <tr>
        <td><span class="pill pill-info">${r.section}</span></td>
        <td><b>${r.label || r.name}</b><br/><span style="font-size:11px;color:#64748b;">${r.name}</span></td>
        <td>${fmtNum(r.size_mb, 2)}</td>
        <td class="flex-row">
          ${r.map_key ? `<button class="btn btn-sm btn-primary" onclick="showRasterOnMap('${r.map_key}')">Map</button>` : ""}
          <a class="btn btn-sm" href="/api/files/download?path=${encodeURIComponent(r.rel_path)}" target="_blank">Download</a>
          <button class="btn btn-sm btn-danger" onclick="deleteAsset('${r.rel_path}')">Del</button>
        </td>
      </tr>
    `).join("") || `<tr><td colspan="4" style="color:#94a3b8;">No rasters generated yet.</td></tr>`;

    const combined = [...inv.shapefiles, ...inv.geopackages, ...inv.tables];
    document.getElementById("vectorsTablesBody").innerHTML = combined.map((f) => `
      <tr>
        <td><span class="pill pill-ok">${f.kind.toUpperCase()}</span></td>
        <td><b>${f.name}</b></td>
        <td>${fmtNum(f.size_mb, 2)}</td>
        <td class="flex-row">
          ${f.map_key ? `<button class="btn btn-sm btn-primary" onclick="showVectorOnMap('${f.map_key}')">Map</button>` : ""}
          ${f.layer ? `<button class="btn btn-sm" onclick="previewTable('${f.layer}')">Preview</button>` : ""}
          <a class="btn btn-sm" href="/api/files/download?path=${encodeURIComponent(f.rel_path)}" target="_blank">Download</a>
          <button class="btn btn-sm btn-danger" onclick="deleteAsset('${f.rel_path}')">Del</button>
        </td>
      </tr>
    `).join("") || `<tr><td colspan="4" style="color:#94a3b8;">No vector or table files generated yet.</td></tr>`;

    const allImgs = [...inv.maps, ...inv.cards];
    document.getElementById("mapsGallery").innerHTML = allImgs.length
      ? allImgs.map((img) => {
          const url = `/api/files/inline?path=${encodeURIComponent(img.rel_path)}`;
          const dl = `/api/files/download?path=${encodeURIComponent(img.rel_path)}`;
          return `
            <div class="thumb-card">
              <img src="${url}" alt="${img.name}" onclick="openImageModal('${img.name}', '${url}')" />
              <div class="thumb-meta">
                <b>${img.name}</b>
                <div class="flex-row" style="justify-content:space-between;">
                  <span style="color:#94a3b8;">${img.section} · ${fmtNum(img.size_mb, 2)} MB</span>
                  <a class="btn btn-sm" href="${dl}" target="_blank">Download</a>
                </div>
              </div>
            </div>
          `;
        }).join("")
      : `<div style="color:#94a3b8;font-size:13px;">No maps or diagnostic cards generated yet for this area.</div>`;
  } catch (e) {
    toast(`Inventory load failed: ${e.message}`, "error");
  }
}

function showRasterOnMap(rasterKey) {
  switchTab("map");
  setTimeout(() => loadRasterOverlay(rasterKey), 250);
}

function showVectorOnMap(layerKey) {
  switchTab("map");
  const chkMap = {
    footprints: "chkFootprints",
    usable_rooftops: "chkUsable",
    obstacles: "chkObstacles",
    shadows: "chkShadows",
    hotspots: "chkHotspots",
  };
  setTimeout(() => {
    const id = chkMap[layerKey];
    if (id) {
      document.getElementById(id).checked = true;
      toggleVectorLayer(layerKey);
    }
  }, 250);
}

async function previewTable(layerName) {
  try {
    const res = await api(`/api/areas/${STATE.activeAreaId}/table-preview/${layerName}?limit=80`);
    const cols = res.columns;
    const head = cols.map((c) => `<th>${c}</th>`).join("");
    const body = res.rows.map((r) => `<tr>${cols.map((c) => `<td>${r[c] ?? ""}</td>`).join("")}</tr>`).join("");
    openModal(`Table Preview: ${layerName} (First ${res.returned} rows)`, `<div class="table-wrap" style="max-height:70vh;"><table><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table></div>`);
  } catch (e) {
    toast(e.message, "error");
  }
}

function openImageModal(title, url) {
  openModal(title, `<img src="${url}" style="max-width:86vw;max-height:76vh;border-radius:8px;display:block;margin:auto;" />`);
}

async function deleteAsset(relPath) {
  if (!confirm(`Permanently delete '${relPath}'?`)) return;
  try {
    await api(`/api/files/delete?path=${encodeURIComponent(relPath)}&area_id=${STATE.activeAreaId}`, { method: "DELETE" });
    toast(`Deleted ${relPath}`, "ok");
    await loadDataInventory();
  } catch (e) {
    toast(e.message, "error");
  }
}

/* ---------------- Smart Logs, Errors & Warnings ---------------- */

function setLogFilter(lvl) {
  STATE.logFilter = lvl;
  loadLogs();
}

async function loadLogs() {
  const q = encodeURIComponent(document.getElementById("logSearchInput").value || "");
  const res = await api(`/api/logs?level=${STATE.logFilter}&search=${q}&limit=300`);
  const c = res.counts || {};
  document.getElementById("cntAll").textContent = c.TOTAL || 0;
  document.getElementById("cntErr").textContent = c.ERROR || 0;
  document.getElementById("cntWarn").textContent = c.WARNING || 0;
  document.getElementById("cntOk").textContent = c.SUCCESS || 0;
  document.getElementById("errBadge").textContent = `Errors: ${c.ERROR || 0}`;
  document.getElementById("warnBadge").textContent = `Warnings: ${c.WARNING || 0}`;

  const el = document.getElementById("eventsList");
  el.innerHTML = (res.events || []).length
    ? res.events.map((ev) => `
      <div class="event-row ${ev.level}">
        <div class="flex-row" style="justify-content:space-between;font-size:11.5px;margin-bottom:4px;">
          <div class="flex-row">
            <span class="pill ${ev.level === "ERROR" ? "pill-err" : ev.level === "WARNING" ? "pill-warn" : ev.level === "SUCCESS" ? "pill-ok" : "pill-info"}">${ev.level}</span>
            <span class="pill pill-info">${ev.section}</span>
            <span style="color:#94a3b8;">Area: ${ev.area_id}</span>
          </div>
          <span style="color:#64748b;">${ev.timestamp}</span>
        </div>
        <div style="font-size:13px;">${ev.message}</div>
        ${ev.detail ? `<pre style="margin-top:6px;font-size:11px;color:#fca5a5;white-space:pre-wrap;">${ev.detail}</pre>` : ""}
        ${ev.hint ? `<div class="event-hint"><b>Suggested Fix:</b> ${ev.hint}</div>` : ""}
      </div>
    `).join("")
    : `<div style="color:#94a3b8;padding:12px;">No log events match this filter.</div>`;

  document.getElementById("auditLogBox").textContent = (res.audit_log || []).join("\n") || "Audit log empty.";
}

async function clearLogs() {
  await api("/api/logs/clear", { method: "POST" });
  toast("Event log cleared.", "ok");
  await loadLogs();
}

/* ---------------- Bootstrap ---------------- */

async function refreshAll() {
  await loadHealth();
  await loadAreas();
  await loadOverview();
  await loadCvProfiles();
  if (STATE.map) await loadAllBoundariesOnMap();
}

document.addEventListener("DOMContentLoaded", async () => {
  document.getElementById("globalAreaSelect").addEventListener("change", async (e) => {
    STATE.activeAreaId = e.target.value;
    document.getElementById("runAreaSelect").value = STATE.activeAreaId;
    await loadOverview();
    await loadDataInventory();
    if (STATE.map) {
      Object.values(STATE.vectorLayers).forEach((l) => STATE.map.removeLayer(l));
      STATE.vectorLayers = {};
      ["chkFootprints","chkUsable","chkObstacles","chkShadows","chkYield","chkHotspots"].forEach((id) => {
        document.getElementById(id).checked = false;
      });
      if (STATE.rasterOverlay) {
        STATE.map.removeLayer(STATE.rasterOverlay);
        STATE.rasterOverlay = null;
      }
      await loadAllBoundariesOnMap();
    }
  });

  await loadCvOptions();
  await refreshAll();
  setInterval(loadHealth, 12000);
});
