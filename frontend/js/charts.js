/**
 * Z-TRACS Road Intelligence - Analytics & Chart Visualizations
 * Implements Section 21 of Technical Specification
 */

let defectDistChart = null;
let severityChart = null;
let densityChart = null;

function renderAnalyticsCharts(analyticsData) {
  if (!window.Chart) {
    console.warn("Chart.js not loaded yet");
    return;
  }

  // 1. Defect Distribution Donut Chart (Section 21: Pothole 42%, Crack 31%, Marking 17%, Other 10%)
  const distCtx = document.getElementById("chart-defect-dist");
  if (distCtx) {
    if (defectDistChart) defectDistChart.destroy();
    
    const distData = analyticsData.defect_distribution || { pothole: 8, crack: 10, marking: 6, other: 0 };
    defectDistChart = new Chart(distCtx, {
      type: 'doughnut',
      data: {
        labels: ['Potholes', 'Cracks', 'Markings', 'Other'],
        datasets: [{
          data: [distData.pothole, distData.crack, distData.marking, distData.other || 0],
          backgroundColor: [
            '#ef4444', // Red for Potholes
            '#f97316', // Orange for Cracks
            '#eab308', // Amber for Markings
            '#64748b'  // Slate for Other
          ],
          borderColor: '#0f172a',
          borderWidth: 2,
          hoverOffset: 6
        }]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: {
            position: 'bottom',
            labels: { color: '#cbd5e1', font: { family: 'Inter', size: 11 }, boxWidth: 12 }
          }
        },
        cutout: '70%'
      }
    });
  }

  // 2. Severity Breakdown Bar Chart
  const sevCtx = document.getElementById("chart-severity");
  if (sevCtx) {
    if (severityChart) severityChart.destroy();

    const sevData = analyticsData.severity_distribution || { critical: 2, high: 9, medium: 9, low: 4 };
    severityChart = new Chart(sevCtx, {
      type: 'bar',
      data: {
        labels: ['Critical (P1)', 'High (P2)', 'Medium (P3)', 'Low (P4)'],
        datasets: [{
          label: 'Defect Severity Count',
          data: [sevData.critical, sevData.high, sevData.medium, sevData.low],
          backgroundColor: ['#ef4444', '#f97316', '#eab308', '#10b981'],
          borderRadius: 6
        }]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: { display: false }
        },
        scales: {
          x: { ticks: { color: '#94a3b8', font: { size: 10 } }, grid: { display: false } },
          y: { ticks: { color: '#94a3b8', stepSize: 2 }, grid: { color: 'rgba(255,255,255,0.05)' } }
        }
      }
    });
  }

  // 3. Defects Per Kilometer Bar Chart (Section 21)
  const densCtx = document.getElementById("chart-density");
  if (densCtx && analyticsData.defects_per_km) {
    if (densityChart) densityChart.destroy();

    const labels = analyticsData.defects_per_km.map(d => d.segment_id);
    const densities = analyticsData.defects_per_km.map(d => d.density);
    const colors = analyticsData.defects_per_km.map(d => {
      if (d.risk >= 75) return '#ef4444';
      if (d.risk >= 55) return '#f97316';
      if (d.risk >= 35) return '#eab308';
      return '#10b981';
    });

    densityChart = new Chart(densCtx, {
      type: 'bar',
      data: {
        labels: labels,
        datasets: [{
          label: 'Defects / KM',
          data: densities,
          backgroundColor: colors,
          borderRadius: 4
        }]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: { display: false }
        },
        scales: {
          x: { ticks: { color: '#94a3b8', font: { size: 10 } }, grid: { display: false } },
          y: { ticks: { color: '#94a3b8' }, grid: { color: 'rgba(255,255,255,0.05)' } }
        }
      }
    });
  }
}

window.renderAnalyticsCharts = renderAnalyticsCharts;
