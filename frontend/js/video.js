/**
 * Z-TRACS Road Intelligence - Synchronized Video Player Engine
 * Implements Section 19 ("Video Player - AI to Evidence to Location to Video")
 */

let videoElement = null;
let currentDetections = [];
let activeDefectId = null;

function initVideoSync(videoElId = "inspection-video-player") {
  videoElement = document.getElementById(videoElId);
  if (!videoElement) return;

  // Listen for time updates to highlight upcoming/active defect
  videoElement.addEventListener("timeupdate", () => {
    const curTime = videoElement.currentTime;
    updateActiveDefectByTime(curTime);
  });
}

function setVideoSource(videoUrl) {
  if (!videoElement) initVideoSync();
  if (!videoElement) return;

  videoElement.src = (typeof resolveApiUrl === "function") ? resolveApiUrl(videoUrl) : videoUrl;
  videoElement.load();
}

function jumpVideoToTimestamp(seconds, defectId = null) {
  if (!videoElement) initVideoSync();
  if (!videoElement) return;

  // If video is shorter than seconds (e.g. sample clip is 10s while survey is 5m), wrap or seek
  if (videoElement.duration && seconds > videoElement.duration) {
    videoElement.currentTime = seconds % videoElement.duration;
  } else {
    videoElement.currentTime = seconds;
  }
  
  videoElement.play().catch(e => console.log("Autoplay blocked, user interaction required"));

  if (defectId) {
    highlightDefectChip(defectId);
  }
}

function renderVideoTimelineChips(detections) {
  currentDetections = detections || [];
  const container = document.getElementById("video-timeline-chips");
  if (!container) return;

  container.innerHTML = "";

  detections.forEach(d => {
    const chip = document.createElement("div");
    chip.id = `chip-${d.id}`;
    chip.className = "timeline-chip";
    
    const sevColor = d.severity === 'critical' ? 'text-red-400' : (d.severity === 'high' ? 'text-orange-400' : 'text-amber-400');
    
    chip.innerHTML = `
      <span class="font-mono text-cyan-400 font-bold">${d.timestamp_formatted}</span>
      <span class="capitalize font-semibold text-slate-200">${d.defect_type}</span>
      <span class="text-xs uppercase font-bold ${sevColor}">[${d.severity}]</span>
    `;

    chip.onclick = () => {
      jumpVideoToTimestamp(d.timestamp, d.id);
      window.selectDefectForEvidence(d);
    };

    container.appendChild(chip);
  });
}

function highlightDefectChip(defectId) {
  activeDefectId = defectId;
  const chips = document.querySelectorAll(".timeline-chip");
  chips.forEach(c => c.classList.remove("active"));

  const targetChip = document.getElementById(`chip-${defectId}`);
  if (targetChip) {
    targetChip.classList.add("active");
    targetChip.scrollIntoView({ behavior: 'smooth', block: 'nearest', inline: 'center' });
  }
}

function updateActiveDefectByTime(currentTime) {
  // Find closest defect within 2.5 seconds
  const match = currentDetections.find(d => Math.abs(d.timestamp - currentTime) < 2.5);
  if (match && match.id !== activeDefectId) {
    highlightDefectChip(match.id);
  }
}

window.initVideoSync = initVideoSync;
window.setVideoSource = setVideoSource;
window.jumpVideoToTimestamp = jumpVideoToTimestamp;
window.renderVideoTimelineChips = renderVideoTimelineChips;
