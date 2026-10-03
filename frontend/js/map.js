function escapeHtml(str) {
  if (window.escapeHtml) return window.escapeHtml(str);
  if (str === null || str === undefined) return '';
  return String(str).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#039;');
}

/**
 * Z-TRACS Road Intelligence - GIS Map Engine
 * Implements Section 15, 16, 17 of Technical Specification
 */

let mapInstance = null;
let segmentsLayer = null;
let defectsLayer = null;

function initRoadMap() {
  if (mapInstance) return mapInstance;

  const mapContainer = document.getElementById("gis-map-container");
  if (!mapContainer) return null;

  // Center around NH-48 corridor
  mapInstance = L.map("gis-map-container", {
    zoomControl: true,
    attributionControl: true
  }).setView([19.035, 73.150], 12);

  window.mapInstance = mapInstance;

  // 1. OpenStreetMap TileLayer with Attribution & Fallback Dark Theme (Requirement 1)
  L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
    maxZoom: 19,
    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener">OpenStreetMap</a> contributors'
  }).addTo(mapInstance);

  // 2. Use featureGroup so fitBounds works on segment/defect layers (Requirement 2)
  segmentsLayer = L.featureGroup().addTo(mapInstance);
  defectsLayer = L.featureGroup().addTo(mapInstance);

  window.segmentsLayer = segmentsLayer;
  window.defectsLayer = defectsLayer;

  return mapInstance;
}

async function loadMapData(inspectionId = "DEMO-001") {
  if (!mapInstance) initRoadMap();
  if (!mapInstance) return;

  // Ensure dimensions are accurately calculated
  mapInstance.invalidateSize();

  segmentsLayer.clearLayers();
  defectsLayer.clearLayers();

  try {
    // 1. Fetch Segments
    const segUrl = (typeof resolveApiUrl === "function") ? resolveApiUrl(`/api/road-segments?inspection_id=${inspectionId}`) : `/api/road-segments?inspection_id=${inspectionId}`;
    const segRes = await (window.apiFetch || fetch)(segUrl);
    const segments = await segRes.json();

    segments.forEach(seg => {
      // 3. Segment lines colored by status (Requirement 3)
      const colorMap = {
        'GREEN': '#10b981',
        'YELLOW': '#f59e0b',
        'ORANGE': '#f97316',
        'RED': '#ef4444'
      };
      const strokeColor = colorMap[seg.status_color] || '#38bdf8';

      // Polyline with rounded ends
      const poly = L.polyline(seg.geometry, {
        color: strokeColor,
        weight: 7,
        opacity: 0.95,
        lineCap: 'round',
        lineJoin: 'round'
      }).addTo(segmentsLayer);

      // Hover emphasis
      poly.on('mouseover', function() {
        this.setStyle({ weight: 10, opacity: 1.0 });
      });
      poly.on('mouseout', function() {
        this.setStyle({ weight: 7, opacity: 0.95 });
      });

      // 4. Clicking a segment opens rich popup (Requirement 4)
      const popupHtml = `
        <div style="font-family: 'Inter', sans-serif; font-size: 12px; min-width: 220px; padding: 4px;">
          <div style="display: flex; justify-content: space-between; align-items: center; border-bottom: 1px solid #334155; padding-bottom: 6px; margin-bottom: 8px;">
            <span style="font-weight: 800; color: #38bdf8; font-size: 14px;">${escapeHtml(seg.id)}</span>
            <span style="padding: 2px 6px; border-radius: 4px; font-size: 10px; font-weight: 800; background: ${strokeColor}22; color: ${strokeColor}; border: 1px solid ${strokeColor}66;">
              ${escapeHtml(seg.status_color)} • ${escapeHtml(seg.priority)}
            </span>
          </div>
          <div style="color: #cbd5e1; font-weight: 600; margin-bottom: 6px; font-size: 11px;">${escapeHtml(seg.segment_name)}</div>
          <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 6px; margin-bottom: 8px; text-align: center;">
            <div style="background: #1e293b; padding: 4px; border-radius: 6px; border: 1px solid #334155;">
              <div style="font-size: 9px; color: #94a3b8;">Condition</div>
              <div style="font-weight: 800; font-size: 13px; color: ${strokeColor};">${escapeHtml(seg.condition_score)}/100</div>
            </div>
            <div style="background: #1e293b; padding: 4px; border-radius: 6px; border: 1px solid #334155;">
              <div style="font-size: 9px; color: #94a3b8;">Risk Score</div>
              <div style="font-weight: 800; font-size: 13px; color: #fb923c;">${escapeHtml(seg.risk_score)}/100</div>
            </div>
          </div>
          <div style="font-size: 11px; color: #94a3b8; margin-bottom: 8px;">
            Total Defects: <b style="color: #f8fafc;">${escapeHtml(seg.defect_count)}</b> (Potholes: ${escapeHtml(seg.pothole_count)}, Cracks: ${escapeHtml(seg.crack_count)}, Markings: ${escapeHtml(seg.marking_count)})
          </div>
          <button class="btn-map-filter-evidence" data-segment-id="${escapeHtml(seg.id)}" 
                  style="width: 100%; padding: 6px 10px; background: #0284c7; color: white; border: none; border-radius: 6px; font-weight: 700; cursor: pointer; font-size: 11px; display: flex; align-items: center; justify-content: center; gap: 4px;">
            🔍 View Evidence & AI Detections →
          </button>
        </div>
      `;
      poly.bindPopup(popupHtml);

      poly.on('click', function(e) {
        showSegmentDetailFlyout(seg);
        poly.openPopup(e.latlng);
      });
    });

    // 2. Fetch Defect GeoJSON Points
    const defUrl = (typeof resolveApiUrl === "function") ? resolveApiUrl(`/api/map/defects?inspection_id=${inspectionId}`) : `/api/map/defects?inspection_id=${inspectionId}`;
    const defRes = await (window.apiFetch || fetch)(defUrl);
    const defGeo = await defRes.json();

    defGeo.features.forEach(feat => {
      const coords = [feat.geometry.coordinates[1], feat.geometry.coordinates[0]];
      const props = feat.properties;

      // 3. Defect point marker colored by SEVERITY (Requirement 3)
      const sev = (props.severity || 'medium').toLowerCase();
      let sevBg = '#eab308'; // medium
      let sevBorder = '#fef08a';
      let sevClass = 'marker-medium';

      if (sev === 'critical') {
        sevBg = '#ef4444';
        sevBorder = '#fca5a5';
        sevClass = 'marker-critical';
      } else if (sev === 'high') {
        sevBg = '#f97316';
        sevBorder = '#fed7aa';
        sevClass = 'marker-high';
      } else if (sev === 'low') {
        sevBg = '#10b981';
        sevBorder = '#a7f3d0';
        sevClass = 'marker-low';
      }

      const iconChar = props.defect_type === 'pothole' ? 'P' : (props.defect_type === 'crack' ? 'C' : 'M');

      const customIcon = L.divIcon({
        className: 'custom-leaflet-pin',
        html: `<div class="defect-marker-pin ${sevClass}" style="background-color: ${sevBg} !important; border: 2px solid ${sevBorder} !important;" title="${props.detection_id} (${sev.toUpperCase()})">${iconChar}</div>`,
        iconSize: [26, 26],
        iconAnchor: [13, 13],
        popupAnchor: [0, -14]
      });

      const marker = L.marker(coords, { icon: customIcon }).addTo(defectsLayer);
      
      const popupHtml = `
        <div style="font-family: 'Inter', sans-serif; font-size: 12px; min-width: 210px; padding: 4px;">
          <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px; border-bottom: 1px solid #334155; padding-bottom: 4px;">
            <span style="font-weight: 800; color: #38bdf8; font-size: 13px;">${escapeHtml(props.detection_id)}</span>
            <span style="padding: 1px 6px; border-radius: 4px; font-size: 10px; font-weight: 800; background: ${sevBg}33; color: ${sevBg}; border: 1px solid ${sevBg}; text-transform: uppercase;">
              ${escapeHtml(props.severity)}
            </span>
          </div>
          <div style="color: #cbd5e1; margin-bottom: 3px;">Type: <span style="text-transform: capitalize; color: #f8fafc; font-weight: 700;">${escapeHtml(props.defect_type)}</span></div>
          <div style="color: #94a3b8; margin-bottom: 3px;">Confidence: <span style="color: #38bdf8; font-weight: 700;">${Math.round(props.confidence * 100)}%</span></div>
          <div style="color: #94a3b8; margin-bottom: 3px;">Segment: <span style="color: #e2e8f0; font-family: monospace;">${escapeHtml(props.road_segment_id)}</span></div>
          <div style="color: #94a3b8; margin-bottom: 8px;">Video Timestamp: <span style="font-family: 'JetBrains Mono', monospace; color: #38bdf8; font-weight: 600;">${escapeHtml(props.timestamp_formatted)}</span></div>
          <button class="btn-map-inspect-defect" data-defect-id="${escapeHtml(props.id)}" data-timestamp-sec="${Number(props.timestamp_sec) || 0}" 
                  style="width: 100%; padding: 7px; background: #0284c7; color: white; border: none; border-radius: 6px; font-weight: 700; cursor: pointer; font-size: 11px; display: flex; align-items: center; justify-content: center; gap: 4px;">
            🔍 Open Evidence & Video →
          </button>
        </div>
      `;
      marker.bindPopup(popupHtml);

      // 4. Clicking a defect point opens its evidence (Requirement 4)
      marker.on('click', function(e) {
        window.inspectSpecificDefect(props.id, Number(props.timestamp_sec) || 0);
      });
    });

    // 2. fitBounds to the segment layer (Requirement 2)
    if (segmentsLayer.getLayers().length > 0) {
      const bounds = segmentsLayer.getBounds();
      if (bounds && bounds.isValid()) {
        mapInstance.fitBounds(bounds, { padding: [50, 50], maxZoom: 15 });
      }
    }

  } catch (err) {
    console.error("Error loading map data:", err);
  }
}

function showSegmentDetailFlyout(seg) {
  const flyout = document.getElementById("segment-flyout");
  if (!flyout) return;

  document.getElementById("flyout-segment-id").innerText = seg.id;
  document.getElementById("flyout-segment-name").innerText = seg.segment_name;
  document.getElementById("flyout-cond-score").innerText = `${seg.condition_score}/100`;
  document.getElementById("flyout-risk-score").innerText = `${seg.risk_score}/100`;
  document.getElementById("flyout-priority").innerText = seg.priority || 'P3';
  
  const priorityBadge = document.getElementById("flyout-priority-badge");
  if (priorityBadge) {
    priorityBadge.className = `px-2 py-0.5 rounded text-xs font-bold ${
      seg.priority === 'P1' ? 'bg-red-500/20 text-red-400 border border-red-500/40' :
      (seg.priority === 'P2' ? 'bg-orange-500/20 text-orange-400 border border-orange-500/40' :
      'bg-amber-500/20 text-amber-400 border border-amber-500/40')
    }`;
  }

  document.getElementById("flyout-total-defects").innerText = seg.defect_count || 0;
  document.getElementById("flyout-potholes").innerText = seg.pothole_count || 0;
  document.getElementById("flyout-cracks").innerText = seg.crack_count || 0;
  document.getElementById("flyout-markings").innerText = seg.marking_count || 0;

  document.getElementById("flyout-critical").innerText = seg.critical_count || 0;
  document.getElementById("flyout-high").innerText = seg.high_count || 0;
  document.getElementById("flyout-medium").innerText = seg.medium_count || 0;
  document.getElementById("flyout-low").innerText = seg.low_count || 0;

  const viewBtn = document.getElementById("flyout-view-evidence-btn");
  if (viewBtn) {
    viewBtn.onclick = () => {
      window.navigateToScreen('screen-evidence');
      window.filterEvidenceBySegment(seg.id);
    };
  }

  flyout.classList.remove("hidden");
}

window.initRoadMap = initRoadMap;
window.loadMapData = loadMapData;
window.showSegmentDetailFlyout = showSegmentDetailFlyout;

// Safe event delegation for map popup actions (neutralizes inline onclick XSS)
document.addEventListener('click', function(e) {
  const filterBtn = e.target.closest('.btn-map-filter-evidence');
  if (filterBtn) {
    const segId = filterBtn.getAttribute('data-segment-id');
    if (segId && window.filterEvidenceBySegment) {
      window.filterEvidenceBySegment(segId);
      if (window.navigateToScreen) window.navigateToScreen('screen-evidence');
    }
    return;
  }
  const inspectBtn = e.target.closest('.btn-map-inspect-defect');
  if (inspectBtn) {
    const defectId = inspectBtn.getAttribute('data-defect-id');
    const tsSec = Number(inspectBtn.getAttribute('data-timestamp-sec')) || 0;
    if (defectId && window.inspectSpecificDefect) {
      window.inspectSpecificDefect(defectId, tsSec);
    }
    return;
  }
});
