/**
 * LLM Frontier Benchmark Explorer & Gallery Dashboard
 * Interactive visual analytics, Pareto frontier calculation, and run drill-down.
 */

(function () {
  'use strict';

  // State
  let benchmarkData = null;
  let activeTab = 'pareto';
  let filters = {
    series: 'all',
    status: 'all',
    provider: 'all',
    search: '',
    sort: 'pareto',
  };

  let paretoState = {
    mode: 'multi', // 'multi' or 'passing'
    scale: 'linear', // 'linear' or 'log'
  };

  let toolsChartMode = 'count'; // 'count' or 'pct'
  let selectedCacheRunId = null;

  // DOM Elements
  const tooltip = document.getElementById('chart-tooltip');
  const modal = document.getElementById('run-modal');

  // ==========================================================================
  // Data Loading & Bootstrapping
  // ==========================================================================

  async function loadData() {
    const embeddedScript = document.getElementById('benchmark-data');
    if (embeddedScript && embeddedScript.textContent.trim().length > 0) {
      try {
        return JSON.parse(embeddedScript.textContent);
      } catch (err) {
        console.warn('Could not parse embedded benchmark data:', err);
      }
    }
    // Fallback for web server hosting
    const resp = await fetch('data.json');
    if (!resp.ok) {
      throw new Error(`Failed to load data.json: HTTP ${resp.status}`);
    }
    return await resp.json();
  }

  async function init() {
    try {
      benchmarkData = await loadData();
      setupHeaderStats();
      setupFilterDropdowns();
      setupEventListeners();
      renderAllViews();
    } catch (err) {
      console.error('Failed to initialize dashboard:', err);
      document.body.innerHTML = `
        <div style="padding: 2rem; color: #f87171; font-family: monospace;">
          <h2>Failed to load benchmark data</h2>
          <p>${err.message}</p>
        </div>
      `;
    }
  }

  // ==========================================================================
  // Header Stats & Filter Controls
  // ==========================================================================

  function setupHeaderStats() {
    const s = benchmarkData.summary;
    document.getElementById('stat-total-runs').textContent = s.total_runs;
    document.getElementById('stat-passed-runs').textContent = `${s.successful_runs} / ${s.total_runs}`;
    document.getElementById('stat-total-series').textContent = s.total_series;
    document.getElementById('stat-total-tokens').textContent = formatCompactNumber(s.total_tokens_generated);
    document.getElementById('stat-total-cost').textContent = `$${s.total_estimated_cost_usd.toFixed(2)}`;
  }

  function setupFilterDropdowns() {
    // Prompt series dropdown
    const seriesSelect = document.getElementById('filter-series');
    benchmarkData.prompts.forEach((p) => {
      const opt = document.createElement('option');
      opt.value = p.prompt_id;
      opt.textContent = `${p.prompt_id} (${p.runs_count} runs)`;
      seriesSelect.appendChild(opt);
    });

    // Provider dropdown
    const providerSelect = document.getElementById('filter-provider');
    const providers = new Set(benchmarkData.runs.map((r) => r.model.provider).filter(Boolean));
    Array.from(providers).sort().forEach((prov) => {
      const opt = document.createElement('option');
      opt.value = prov;
      opt.textContent = prov.charAt(0).toUpperCase() + prov.slice(1);
      providerSelect.appendChild(opt);
    });

    // Cache curve run selector
    const cacheRunSelect = document.getElementById('select-cache-run');
    cacheRunSelect.innerHTML = '';
    const runsWithTurns = benchmarkData.runs.filter((r) => r.turns && r.turns.length > 0);
    runsWithTurns.forEach((r) => {
      const opt = document.createElement('option');
      opt.value = r.run_id;
      opt.textContent = `${r.model.name} — ${r.prompt_id} (${r.turns.length} turns)`;
      cacheRunSelect.appendChild(opt);
    });
    if (runsWithTurns.length > 0) {
      selectedCacheRunId = runsWithTurns[0].run_id;
    }
  }

  function setupEventListeners() {
    // Tabs Navigation
    document.querySelectorAll('.nav-tab').forEach((tabBtn) => {
      tabBtn.addEventListener('click', () => {
        document.querySelectorAll('.nav-tab').forEach((b) => b.classList.remove('active'));
        document.querySelectorAll('.tab-content').forEach((c) => c.classList.remove('active'));

        tabBtn.classList.add('active');
        activeTab = tabBtn.dataset.tab;
        document.getElementById(`tab-${activeTab}`).classList.add('active');
        renderAllViews();
      });
    });

    // Filter controls
    document.getElementById('filter-series').addEventListener('change', (e) => {
      filters.series = e.target.value;
      renderAllViews();
    });

    document.getElementById('filter-status').addEventListener('change', (e) => {
      filters.status = e.target.value;
      renderAllViews();
    });

    document.getElementById('filter-provider').addEventListener('change', (e) => {
      filters.provider = e.target.value;
      renderAllViews();
    });

    document.getElementById('filter-search').addEventListener('input', (e) => {
      filters.search = e.target.value.toLowerCase().trim();
      renderAllViews();
    });

    document.getElementById('filter-sort').addEventListener('change', (e) => {
      filters.sort = e.target.value;
      renderAllViews();
    });

    // Pareto controls
    document.getElementById('btn-frontier-multi').addEventListener('click', () => {
      paretoState.mode = 'multi';
      document.getElementById('btn-frontier-multi').classList.add('active');
      document.getElementById('btn-frontier-passing').classList.remove('active');
      renderParetoChart();
    });

    document.getElementById('btn-frontier-passing').addEventListener('click', () => {
      paretoState.mode = 'passing';
      document.getElementById('btn-frontier-passing').classList.add('active');
      document.getElementById('btn-frontier-multi').classList.remove('active');
      renderParetoChart();
    });

    document.getElementById('btn-scale-linear').addEventListener('click', () => {
      paretoState.scale = 'linear';
      document.getElementById('btn-scale-linear').classList.add('active');
      document.getElementById('btn-scale-log').classList.remove('active');
      renderParetoChart();
    });

    document.getElementById('btn-scale-log').addEventListener('click', () => {
      paretoState.scale = 'log';
      document.getElementById('btn-scale-log').classList.add('active');
      document.getElementById('btn-scale-linear').classList.remove('active');
      renderParetoChart();
    });

    // Tools chart controls
    document.getElementById('btn-tools-stacked').addEventListener('click', () => {
      toolsChartMode = 'count';
      document.getElementById('btn-tools-stacked').classList.add('active');
      document.getElementById('btn-tools-pct').classList.remove('active');
      renderToolsChart();
    });

    document.getElementById('btn-tools-pct').addEventListener('click', () => {
      toolsChartMode = 'pct';
      document.getElementById('btn-tools-pct').classList.add('active');
      document.getElementById('btn-tools-stacked').classList.remove('active');
      renderToolsChart();
    });

    // Cache curve run selector
    document.getElementById('select-cache-run').addEventListener('change', (e) => {
      selectedCacheRunId = e.target.value;
      renderCacheCurveChart();
    });

    // Modal close events
    document.getElementById('modal-close-btn').addEventListener('click', closeModal);
    modal.addEventListener('click', (e) => {
      if (e.target === modal) closeModal();
    });
    window.addEventListener('keydown', (e) => {
      if (e.key === 'Escape' && modal.style.display !== 'none') closeModal();
    });

    // Modal tabs
    document.querySelectorAll('.modal-tab').forEach((mtab) => {
      mtab.addEventListener('click', () => {
        document.querySelectorAll('.modal-tab').forEach((t) => t.classList.remove('active'));
        document.querySelectorAll('.modal-tab-content').forEach((c) => c.classList.remove('active'));
        mtab.classList.add('active');
        document.getElementById(`modal-tab-${mtab.dataset.modaltab}`).classList.add('active');
      });
    });

    // Window resize handler
    window.addEventListener('resize', debounce(renderAllViews, 200));
  }

  // ==========================================================================
  // Filtering & Sorting
  // ==========================================================================

  function getFilteredRuns() {
    return benchmarkData.runs.filter((run) => {
      if (filters.series !== 'all' && run.prompt_id !== filters.series) {
        return false;
      }
      if (filters.status === 'passed' && !run.verification.passed) {
        return false;
      }
      if (filters.status === 'failed' && run.verification.passed) {
        return false;
      }
      if (filters.provider !== 'all' && run.model.provider !== filters.provider) {
        return false;
      }
      if (filters.search) {
        const q = filters.search;
        const text = `${run.model.name} ${run.model.label} ${run.prompt_id} ${run.run_id} ${run.model.provider}`.toLowerCase();
        if (!text.includes(q)) return false;
      }
      return true;
    }).sort((a, b) => {
      const costA = a.cost.estimated_with_harness_usd ?? a.cost.estimated_usd ?? 999999;
      const costB = b.cost.estimated_with_harness_usd ?? b.cost.estimated_usd ?? 999999;
      const timeA = a.model_time.generating_seconds ?? a.wall_clock.seconds ?? 999999;
      const timeB = b.model_time.generating_seconds ?? b.wall_clock.seconds ?? 999999;
      const tokA = a.tokens.total_output ?? 0;
      const tokB = b.tokens.total_output ?? 0;

      switch (filters.sort) {
        case 'cost-asc':
          return costA - costB;
        case 'cost-desc':
          return costB - costA;
        case 'time-asc':
          return timeA - timeB;
        case 'time-desc':
          return timeB - timeA;
        case 'tokens-desc':
          return tokB - tokA;
        case 'name-asc':
          return a.model.name.localeCompare(b.model.name);
        case 'pareto':
        default:
          // Pareto-efficient first, then quality score desc, then cost asc
          const pA = a.pareto.is_pareto_series ? 1 : 0;
          const pB = b.pareto.is_pareto_series ? 1 : 0;
          if (pA !== pB) return pB - pA;
          const qA = a.pareto.quality_score ?? 0;
          const qB = b.pareto.quality_score ?? 0;
          if (qA !== qB) return qB - qA;
          return costA - costB;
      }
    });
  }

  function renderAllViews() {
    if (activeTab === 'pareto') {
      renderParetoChart();
    } else if (activeTab === 'analytics') {
      renderTokensChart();
      renderTimeChart();
      renderToolsChart();
      renderCostCompareChart();
      renderCacheCurveChart();
    } else if (activeTab === 'gallery') {
      renderGallery();
    }
  }

  // ==========================================================================
  // CHART 1: PARETO FRONTIER SCATTER
  // ==========================================================================

  function renderParetoChart() {
    const container = document.getElementById('pareto-chart-container');
    container.innerHTML = '';
    const runs = getFilteredRuns();

    const width = container.clientWidth || 900;
    const height = container.clientHeight || 520;
    const pad = { top: 40, right: 50, bottom: 65, left: 80 };
    const innerW = width - pad.left - pad.right;
    const innerH = height - pad.top - pad.bottom;

    // Filter runs with cost & time
    const chartRuns = runs.filter((r) => {
      const c = r.cost.estimated_with_harness_usd ?? r.cost.estimated_usd;
      const t = r.model_time.generating_seconds ?? r.wall_clock.seconds;
      if (c == null || t == null) return false;
      if (paretoState.mode === 'passing' && !r.verification.passed) return false;
      return true;
    });

    if (chartRuns.length === 0) {
      container.innerHTML = '<div style="display:flex;align-items:center;justify-content:center;height:100%;color:#64748b;">No runs match current filter criteria.</div>';
      updateParetoTable([]);
      return;
    }

    const times = chartRuns.map((r) => r.model_time.generating_seconds ?? r.wall_clock.seconds);
    const costs = chartRuns.map((r) => r.cost.estimated_with_harness_usd ?? r.cost.estimated_usd);

    let minT = Math.min(...times);
    let maxT = Math.max(...times);
    let minC = Math.min(...costs);
    let maxC = Math.max(...costs);

    // Padding for axes
    if (paretoState.scale === 'log') {
      minT = Math.max(10, minT * 0.7);
      maxT = maxT * 1.3;
      minC = Math.max(0.1, minC * 0.7);
      maxC = maxC * 1.3;
    } else {
      minT = 0;
      maxT = maxT * 1.15;
      minC = 0;
      maxC = maxC * 1.2;
    }

    function scaleX(val) {
      if (paretoState.scale === 'log') {
        return pad.left + ((Math.log10(val) - Math.log10(minT)) / (Math.log10(maxT) - Math.log10(minT))) * innerW;
      }
      return pad.left + (val / maxT) * innerW;
    }

    function scaleY(val) {
      if (paretoState.scale === 'log') {
        return pad.top + innerH - ((Math.log10(val) - Math.log10(minC)) / (Math.log10(maxC) - Math.log10(minC))) * innerH;
      }
      return pad.top + innerH - (val / maxC) * innerH;
    }

    const svg = createSvg(width, height);

    // Grid lines & Axes
    const xTicks = getTicks(minT, maxT, paretoState.scale === 'log' ? 5 : 6);
    xTicks.forEach((t) => {
      const x = scaleX(t);
      if (x >= pad.left && x <= pad.left + innerW) {
        svg.appendChild(createSvgLine(x, pad.top, x, pad.top + innerH, 'grid-line'));
        const lbl = createSvgText(x, pad.top + innerH + 20, formatDurationSec(t), 'axis-text', 'middle');
        svg.appendChild(lbl);
      }
    });

    const yTicks = getTicks(minC, maxC, paretoState.scale === 'log' ? 5 : 6);
    yTicks.forEach((c) => {
      const y = scaleY(c);
      if (y >= pad.top && y <= pad.top + innerH) {
        svg.appendChild(createSvgLine(pad.left, y, pad.left + innerW, y, 'grid-line'));
        const lbl = createSvgText(pad.left - 12, y + 4, `$${c.toFixed(2)}`, 'axis-text', 'end');
        svg.appendChild(lbl);
      }
    });

    // Axis borders
    svg.appendChild(createSvgLine(pad.left, pad.top + innerH, pad.left + innerW, pad.top + innerH, 'axis-line'));
    svg.appendChild(createSvgLine(pad.left, pad.top, pad.left, pad.top + innerH, 'axis-line'));

    // Axis Labels
    svg.appendChild(createSvgText(pad.left + innerW / 2, pad.top + innerH + 48, 'Model Generation Time (min:sec)', 'axis-label', 'middle'));
    const yLabel = createSvgText(24, pad.top + innerH / 2, 'Estimated Cost (USD)', 'axis-label', 'middle');
    yLabel.setAttribute('transform', `rotate(-90 24 ${pad.top + innerH / 2})`);
    svg.appendChild(yLabel);

    // Compute Pareto points for drawing the frontier line
    const paretoRuns = chartRuns.filter((r) => {
      if (paretoState.mode === 'passing') {
        return r.pareto.is_pareto_successful_series || r.pareto.is_pareto_successful;
      }
      return r.pareto.is_pareto_series || r.pareto.is_pareto_global;
    });

    // Sort Pareto runs by time ascending
    paretoRuns.sort((a, b) => {
      const ta = a.model_time.generating_seconds ?? a.wall_clock.seconds;
      const tb = b.model_time.generating_seconds ?? b.wall_clock.seconds;
      return ta - tb;
    });

    // Render Pareto Frontier Line (stepped or direct)
    if (paretoRuns.length >= 2) {
      let d = '';
      paretoRuns.forEach((r, idx) => {
        const t = r.model_time.generating_seconds ?? r.wall_clock.seconds;
        const c = r.cost.estimated_with_harness_usd ?? r.cost.estimated_usd;
        const x = scaleX(t);
        const y = scaleY(c);
        if (idx === 0) {
          d += `M ${x} ${y}`;
        } else {
          // Direct curve or step
          d += ` L ${x} ${y}`;
        }
      });
      const path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
      path.setAttribute('d', d);
      path.setAttribute('class', 'pareto-line');
      svg.appendChild(path);
    }

    // Render Data Points
    chartRuns.forEach((run) => {
      const t = run.model_time.generating_seconds ?? run.wall_clock.seconds;
      const c = run.cost.estimated_with_harness_usd ?? run.cost.estimated_usd;
      const x = scaleX(t);
      const y = scaleY(c);

      const isPareto = paretoRuns.includes(run);
      const isPass = run.verification.passed;
      const qualScore = run.pareto.quality_score ?? (isPass ? 1.0 : 0.0);

      // Point size based on quality score
      const radius = 6 + Math.round(qualScore * 6);

      // Color based on verification
      let color = '#f43f5e'; // red
      if (isPass) {
        color = '#10b981'; // green
      } else if (qualScore > 0.1) {
        color = '#f59e0b'; // orange
      }

      // Group
      const g = document.createElementNS('http://www.w3.org/2000/svg', 'g');
      g.setAttribute('class', 'scatter-point');

      // Halo for Pareto runs
      if (isPareto) {
        const halo = document.createElementNS('http://www.w3.org/2000/svg', 'circle');
        halo.setAttribute('cx', x);
        halo.setAttribute('cy', y);
        halo.setAttribute('r', radius + 8);
        halo.setAttribute('class', 'pareto-halo');
        g.appendChild(halo);
      }

      // Main Circle
      const circle = document.createElementNS('http://www.w3.org/2000/svg', 'circle');
      circle.setAttribute('cx', x);
      circle.setAttribute('cy', y);
      circle.setAttribute('r', radius);
      circle.setAttribute('fill', color);
      circle.setAttribute('stroke', isPareto ? '#38bdf8' : '#ffffff');
      circle.setAttribute('stroke-width', isPareto ? '3' : '1.5');
      g.appendChild(circle);

      // Tooltip & Click events
      g.addEventListener('mouseenter', (ev) => {
        showTooltip(ev, `
          <div class="tooltip-title">${escapeHtml(run.model.name)}</div>
          <div class="tooltip-row"><span>Series:</span> <span class="val">${escapeHtml(run.prompt_id)}</span></div>
          <div class="tooltip-row"><span>Cost:</span> <span class="val">$${c.toFixed(2)}</span></div>
          <div class="tooltip-row"><span>Gen Time:</span> <span class="val">${formatDurationSec(t)}</span></div>
          <div class="tooltip-row"><span>Probe Score:</span> <span class="val">${(qualScore * 100).toFixed(0)}%</span></div>
          <div class="tooltip-row"><span>Status:</span> <span class="val" style="color: ${isPass ? '#10b981' : '#f43f5e'}">${isPass ? 'VERIFIED' : 'FAILED'}</span></div>
          ${isPareto ? '<div class="tooltip-row" style="margin-top:4px;"><span class="badge pareto">⚡ PARETO OPTIMAL</span></div>' : ''}
        `);
      });
      g.addEventListener('mousemove', moveTooltip);
      g.addEventListener('mouseleave', hideTooltip);
      g.addEventListener('click', () => openModal(run));

      svg.appendChild(g);
    });

    container.appendChild(svg);
    updateParetoTable(paretoRuns);
  }

  function updateParetoTable(paretoRuns) {
    const tbody = document.querySelector('#pareto-summary-table tbody');
    tbody.innerHTML = '';

    if (paretoRuns.length === 0) {
      tbody.innerHTML = '<tr><td colspan="8" style="text-align:center;color:#64748b;">No Pareto runs in current view.</td></tr>';
      return;
    }

    paretoRuns.forEach((r) => {
      const tr = document.createElement('tr');
      const isPass = r.verification.passed;
      const c = r.cost.estimated_with_harness_usd ?? r.cost.estimated_usd ?? 0;
      const t = r.model_time.generating_seconds ?? r.wall_clock.seconds ?? 0;
      const tok = r.tokens.total_output ?? 0;

      tr.innerHTML = `
        <td><span class="badge ${isPass ? 'pass' : 'fail'}">${isPass ? '✓ PASS' : '✗ FAIL'}</span></td>
        <td><strong>${escapeHtml(r.model.name)}</strong> <span style="font-size:0.75rem;color:#64748b;">(${escapeHtml(r.model.provider)})</span></td>
        <td><span class="series-badge">${escapeHtml(r.prompt_id)}</span></td>
        <td style="font-family:var(--font-mono);">$${c.toFixed(2)}</td>
        <td style="font-family:var(--font-mono);">${formatDurationSec(t)}</td>
        <td style="font-family:var(--font-mono);">${((r.pareto.quality_score ?? 0) * 100).toFixed(0)}%</td>
        <td style="font-family:var(--font-mono);">${formatCompactNumber(tok)}</td>
        <td><button class="btn-inspect" data-runid="${r.run_id}">Inspect</button></td>
      `;

      tr.querySelector('.btn-inspect').addEventListener('click', () => openModal(r));
      tbody.appendChild(tr);
    });
  }

  // ==========================================================================
  // CHART 2: TOKENS GENERATED (VISIBLE VS REASONING)
  // ==========================================================================

  function renderTokensChart() {
    const container = document.getElementById('chart-tokens');
    container.innerHTML = '';
    const runs = getFilteredRuns();

    const width = container.clientWidth || 550;
    const height = 400;
    const pad = { top: 20, right: 30, bottom: 85, left: 65 };
    const innerW = width - pad.left - pad.right;
    const innerH = height - pad.top - pad.bottom;

    if (runs.length === 0) {
      container.innerHTML = '<div style="display:flex;align-items:center;justify-content:center;height:100%;color:#64748b;">No data</div>';
      return;
    }

    const svg = createSvg(width, height);
    const maxTotal = Math.max(...runs.map((r) => (r.tokens.total_output || 0)), 1000) * 1.15;

    const barW = Math.max(12, Math.min(36, Math.floor(innerW / runs.length) - 8));
    const step = innerW / runs.length;

    // Y ticks
    const ticks = getTicks(0, maxTotal, 5);
    ticks.forEach((val) => {
      const y = pad.top + innerH - (val / maxTotal) * innerH;
      svg.appendChild(createSvgLine(pad.left, y, pad.left + innerW, y, 'grid-line'));
      svg.appendChild(createSvgText(pad.left - 10, y + 4, formatCompactNumber(val), 'axis-text', 'end'));
    });

    runs.forEach((r, idx) => {
      const cx = pad.left + idx * step + step / 2;
      const x = cx - barW / 2;
      const vis = r.tokens.visible || 0;
      const reas = r.tokens.reasoning || 0;
      const tot = vis + reas;

      const hVis = (vis / maxTotal) * innerH;
      const hReas = (reas / maxTotal) * innerH;

      const yVis = pad.top + innerH - hVis;
      const yReas = yVis - hReas;

      const g = document.createElementNS('http://www.w3.org/2000/svg', 'g');
      g.style.cursor = 'pointer';

      // Visible rect
      if (hVis > 0) {
        const r1 = createSvgRect(x, yVis, barW, hVis, '#38bdf8');
        g.appendChild(r1);
      }
      // Reasoning rect
      if (hReas > 0) {
        const r2 = createSvgRect(x, yReas, barW, hReas, '#c084fc');
        g.appendChild(r2);
      }

      // X Label (rotated)
      const label = createSvgText(cx, pad.top + innerH + 15, truncate(r.model.name, 12), 'axis-text', 'end');
      label.setAttribute('transform', `rotate(-45 ${cx} ${pad.top + innerH + 15})`);
      svg.appendChild(label);

      // Tooltip & click
      const reasPct = tot > 0 ? Math.round((reas / tot) * 100) : 0;
      g.addEventListener('mouseenter', (ev) => {
        showTooltip(ev, `
          <div class="tooltip-title">${escapeHtml(r.model.name)}</div>
          <div class="tooltip-row"><span>Total:</span> <span class="val">${formatCompactNumber(tot)} tokens</span></div>
          <div class="tooltip-row"><span>Visible:</span> <span class="val">${formatCompactNumber(vis)}</span></div>
          <div class="tooltip-row"><span>Reasoning:</span> <span class="val">${formatCompactNumber(reas)} (${reasPct}%)</span></div>
        `);
      });
      g.addEventListener('mousemove', moveTooltip);
      g.addEventListener('mouseleave', hideTooltip);
      g.addEventListener('click', () => openModal(r));

      svg.appendChild(g);
    });

    svg.appendChild(createSvgLine(pad.left, pad.top + innerH, pad.left + innerW, pad.top + innerH, 'axis-line'));
    svg.appendChild(createSvgLine(pad.left, pad.top, pad.left, pad.top + innerH, 'axis-line'));

    container.appendChild(svg);
  }

  // ==========================================================================
  // CHART 3: MODEL TIME VS OVERHEAD
  // ==========================================================================

  function renderTimeChart() {
    const container = document.getElementById('chart-time');
    container.innerHTML = '';
    const runs = getFilteredRuns();

    const width = container.clientWidth || 550;
    const height = 400;
    const pad = { top: 20, right: 30, bottom: 85, left: 65 };
    const innerW = width - pad.left - pad.right;
    const innerH = height - pad.top - pad.bottom;

    if (runs.length === 0) {
      container.innerHTML = '<div style="display:flex;align-items:center;justify-content:center;height:100%;color:#64748b;">No data</div>';
      return;
    }

    const svg = createSvg(width, height);
    const maxSec = Math.max(...runs.map((r) => Math.max(r.wall_clock.seconds || 0, r.model_time.generating_seconds || 0)), 60) * 1.15;

    const barW = Math.max(12, Math.min(36, Math.floor(innerW / runs.length) - 8));
    const step = innerW / runs.length;

    // Y ticks
    const ticks = getTicks(0, maxSec, 5);
    ticks.forEach((val) => {
      const y = pad.top + innerH - (val / maxSec) * innerH;
      svg.appendChild(createSvgLine(pad.left, y, pad.left + innerW, y, 'grid-line'));
      svg.appendChild(createSvgText(pad.left - 10, y + 4, formatDurationSec(val), 'axis-text', 'end'));
    });

    runs.forEach((r, idx) => {
      const cx = pad.left + idx * step + step / 2;
      const x = cx - barW / 2;
      const genS = r.model_time.generating_seconds || 0;
      const wallS = r.wall_clock.seconds || genS;
      const overheadS = Math.max(0, wallS - genS);

      const hGen = (genS / maxSec) * innerH;
      const hOverhead = (overheadS / maxSec) * innerH;

      const yGen = pad.top + innerH - hGen;
      const yOver = yGen - hOverhead;

      const g = document.createElementNS('http://www.w3.org/2000/svg', 'g');
      g.style.cursor = 'pointer';

      // API Time rect
      if (hGen > 0) {
        g.appendChild(createSvgRect(x, yGen, barW, hGen, '#3b82f6'));
      }
      // Overhead rect
      if (hOverhead > 0) {
        g.appendChild(createSvgRect(x, yOver, barW, hOverhead, '#475569'));
      }

      // X Label
      const label = createSvgText(cx, pad.top + innerH + 15, truncate(r.model.name, 12), 'axis-text', 'end');
      label.setAttribute('transform', `rotate(-45 ${cx} ${pad.top + innerH + 15})`);
      svg.appendChild(label);

      g.addEventListener('mouseenter', (ev) => {
        showTooltip(ev, `
          <div class="tooltip-title">${escapeHtml(r.model.name)}</div>
          <div class="tooltip-row"><span>Wall Clock:</span> <span class="val">${formatDurationSec(wallS)}</span></div>
          <div class="tooltip-row"><span>API Gen Time:</span> <span class="val">${formatDurationSec(genS)}</span></div>
          <div class="tooltip-row"><span>Tool Overhead:</span> <span class="val">${formatDurationSec(overheadS)}</span></div>
        `);
      });
      g.addEventListener('mousemove', moveTooltip);
      g.addEventListener('mouseleave', hideTooltip);
      g.addEventListener('click', () => openModal(r));

      svg.appendChild(g);
    });

    svg.appendChild(createSvgLine(pad.left, pad.top + innerH, pad.left + innerW, pad.top + innerH, 'axis-line'));
    svg.appendChild(createSvgLine(pad.left, pad.top, pad.left, pad.top + innerH, 'axis-line'));

    container.appendChild(svg);
  }

  // ==========================================================================
  // CHART 4: TOOL BUCKET BREAKDOWN
  // ==========================================================================

  function renderToolsChart() {
    const container = document.getElementById('chart-tools');
    container.innerHTML = '';
    const runs = getFilteredRuns();

    const width = container.clientWidth || 550;
    const height = 400;
    const pad = { top: 20, right: 30, bottom: 85, left: 65 };
    const innerW = width - pad.left - pad.right;
    const innerH = height - pad.top - pad.bottom;

    if (runs.length === 0) {
      container.innerHTML = '<div style="display:flex;align-items:center;justify-content:center;height:100%;color:#64748b;">No data</div>';
      return;
    }

    const svg = createSvg(width, height);
    const isPct = toolsChartMode === 'pct';

    const maxVal = isPct
      ? 100
      : Math.max(...runs.map((r) => r.tool_calls.total.calls || 0), 10) * 1.15;

    const barW = Math.max(12, Math.min(36, Math.floor(innerW / runs.length) - 8));
    const step = innerW / runs.length;

    // Y ticks
    const ticks = isPct ? [0, 25, 50, 75, 100] : getTicks(0, maxVal, 5);
    ticks.forEach((val) => {
      const y = pad.top + innerH - (val / maxVal) * innerH;
      svg.appendChild(createSvgLine(pad.left, y, pad.left + innerW, y, 'grid-line'));
      svg.appendChild(createSvgText(pad.left - 10, y + 4, isPct ? `${val}%` : Math.round(val), 'axis-text', 'end'));
    });

    const colors = {
      shell: '#38bdf8',
      files: '#fbbf24',
      visual_checks: '#c084fc',
      web: '#2dd4bf',
      other: '#94a3b8',
    };

    runs.forEach((r, idx) => {
      const cx = pad.left + idx * step + step / 2;
      const x = cx - barW / 2;
      const tc = r.tool_calls;
      const tot = tc.total.calls || 1;

      let currentY = pad.top + innerH;
      const g = document.createElementNS('http://www.w3.org/2000/svg', 'g');
      g.style.cursor = 'pointer';

      ['shell', 'files', 'visual_checks', 'web', 'other'].forEach((bkey) => {
        const count = tc[bkey]?.calls || 0;
        if (count === 0) return;

        const val = isPct ? (count / tot) * 100 : count;
        const h = (val / maxVal) * innerH;
        currentY -= h;

        g.appendChild(createSvgRect(x, currentY, barW, h, colors[bkey]));
      });

      // Failure indicator line if tool failures exist
      if (tc.total.failures > 0) {
        const failLine = createSvgLine(x, pad.top + innerH + 3, x + barW, pad.top + innerH + 3, '');
        failLine.setAttribute('stroke', '#f87171');
        failLine.setAttribute('stroke-width', '3');
        g.appendChild(failLine);
      }

      // X Label
      const label = createSvgText(cx, pad.top + innerH + 15, truncate(r.model.name, 12), 'axis-text', 'end');
      label.setAttribute('transform', `rotate(-45 ${cx} ${pad.top + innerH + 15})`);
      svg.appendChild(label);

      g.addEventListener('mouseenter', (ev) => {
        showTooltip(ev, `
          <div class="tooltip-title">${escapeHtml(r.model.name)}</div>
          <div class="tooltip-row"><span>Total Calls:</span> <span class="val">${tc.total.calls} (Failures: ${tc.total.failures})</span></div>
          <div class="tooltip-row"><span style="color:#38bdf8;">Shell:</span> <span class="val">${tc.shell?.calls || 0}</span></div>
          <div class="tooltip-row"><span style="color:#fbbf24;">Files:</span> <span class="val">${tc.files?.calls || 0}</span></div>
          <div class="tooltip-row"><span style="color:#c084fc;">Visual:</span> <span class="val">${tc.visual_checks?.calls || 0}</span></div>
          <div class="tooltip-row"><span style="color:#2dd4bf;">Web:</span> <span class="val">${tc.web?.calls || 0}</span></div>
          <div class="tooltip-row"><span style="color:#94a3b8;">Other:</span> <span class="val">${tc.other?.calls || 0}</span></div>
        `);
      });
      g.addEventListener('mousemove', moveTooltip);
      g.addEventListener('mouseleave', hideTooltip);
      g.addEventListener('click', () => openModal(r));

      svg.appendChild(g);
    });

    svg.appendChild(createSvgLine(pad.left, pad.top + innerH, pad.left + innerW, pad.top + innerH, 'axis-line'));
    svg.appendChild(createSvgLine(pad.left, pad.top, pad.left, pad.top + innerH, 'axis-line'));

    container.appendChild(svg);
  }

  // ==========================================================================
  // CHART 5: ESTIMATED VS BILLED COST
  // ==========================================================================

  function renderCostCompareChart() {
    const container = document.getElementById('chart-cost-compare');
    container.innerHTML = '';
    const allRuns = getFilteredRuns();
    const billedRuns = allRuns.filter((r) => r.cost.billed_usd != null);

    const width = container.clientWidth || 550;
    const height = 400;
    const pad = { top: 20, right: 30, bottom: 85, left: 65 };
    const innerW = width - pad.left - pad.right;
    const innerH = height - pad.top - pad.bottom;

    if (billedRuns.length === 0) {
      container.innerHTML = '<div style="display:flex;align-items:center;justify-content:center;height:100%;color:#64748b;">No ingested CSV billing data available for current filter.</div>';
      return;
    }

    const svg = createSvg(width, height);
    const maxCost = Math.max(...billedRuns.map((r) => Math.max(r.cost.estimated_with_harness_usd || 0, r.cost.billed_usd || 0)), 5) * 1.2;

    const barGroupW = Math.max(20, Math.min(50, Math.floor(innerW / billedRuns.length) - 10));
    const barW = barGroupW / 2 - 2;
    const step = innerW / billedRuns.length;

    // Y ticks
    const ticks = getTicks(0, maxCost, 5);
    ticks.forEach((val) => {
      const y = pad.top + innerH - (val / maxCost) * innerH;
      svg.appendChild(createSvgLine(pad.left, y, pad.left + innerW, y, 'grid-line'));
      svg.appendChild(createSvgText(pad.left - 10, y + 4, `$${val.toFixed(2)}`, 'axis-text', 'end'));
    });

    billedRuns.forEach((r, idx) => {
      const cx = pad.left + idx * step + step / 2;
      const x1 = cx - barGroupW / 2;
      const x2 = x1 + barW + 4;

      const est = r.cost.estimated_with_harness_usd ?? r.cost.estimated_usd ?? 0;
      const billed = r.cost.billed_usd ?? 0;

      const hEst = (est / maxCost) * innerH;
      const hBilled = (billed / maxCost) * innerH;

      const yEst = pad.top + innerH - hEst;
      const yBilled = pad.top + innerH - hBilled;

      const g = document.createElementNS('http://www.w3.org/2000/svg', 'g');
      g.style.cursor = 'pointer';

      // Est rect
      g.appendChild(createSvgRect(x1, yEst, barW, hEst, '#6366f1'));
      // Billed rect
      g.appendChild(createSvgRect(x2, yBilled, barW, hBilled, '#10b981'));

      // X Label
      const label = createSvgText(cx, pad.top + innerH + 15, truncate(r.model.name, 12), 'axis-text', 'end');
      label.setAttribute('transform', `rotate(-45 ${cx} ${pad.top + innerH + 15})`);
      svg.appendChild(label);

      const delta = billed - est;
      const deltaPct = est > 0 ? (delta / est) * 100 : 0;

      g.addEventListener('mouseenter', (ev) => {
        showTooltip(ev, `
          <div class="tooltip-title">${escapeHtml(r.model.name)}</div>
          <div class="tooltip-row"><span>Estimated Cost:</span> <span class="val">$${est.toFixed(2)}</span></div>
          <div class="tooltip-row"><span>Actual Billed:</span> <span class="val">$${billed.toFixed(2)}</span></div>
          <div class="tooltip-row"><span>Delta:</span> <span class="val">${delta >= 0 ? '+' : ''}$${delta.toFixed(2)} (${deltaPct.toFixed(1)}%)</span></div>
        `);
      });
      g.addEventListener('mousemove', moveTooltip);
      g.addEventListener('mouseleave', hideTooltip);
      g.addEventListener('click', () => openModal(r));

      svg.appendChild(g);
    });

    svg.appendChild(createSvgLine(pad.left, pad.top + innerH, pad.left + innerW, pad.top + innerH, 'axis-line'));
    svg.appendChild(createSvgLine(pad.left, pad.top, pad.left, pad.top + innerH, 'axis-line'));

    container.appendChild(svg);
  }

  // ==========================================================================
  // CHART 6: CONTEXT RE-READ / CACHE CURVE ACROSS TURNS
  // ==========================================================================

  function renderCacheCurveChart() {
    const container = document.getElementById('chart-cache-curve');
    container.innerHTML = '';

    const run = benchmarkData.runs.find((r) => r.run_id === selectedCacheRunId);
    if (!run || !run.turns || run.turns.length === 0) {
      container.innerHTML = '<div style="display:flex;align-items:center;justify-content:center;height:100%;color:#64748b;">No turn-by-turn data available for selected run.</div>';
      return;
    }

    const turns = run.turns;
    const width = container.clientWidth || 1100;
    const height = 380;
    const pad = { top: 30, right: 65, bottom: 50, left: 80 };
    const innerW = width - pad.left - pad.right;
    const innerH = height - pad.top - pad.bottom;

    const svg = createSvg(width, height);

    const maxCacheRead = Math.max(...turns.map((t) => t.cumulative_cache_read_tokens || 0), 1000) * 1.15;
    const numTurns = turns.length;
    const step = innerW / Math.max(1, numTurns - 1);

    // Left Y Axis (Cumulative Tokens)
    const leftTicks = getTicks(0, maxCacheRead, 5);
    leftTicks.forEach((val) => {
      const y = pad.top + innerH - (val / maxCacheRead) * innerH;
      svg.appendChild(createSvgLine(pad.left, y, pad.left + innerW, y, 'grid-line'));
      svg.appendChild(createSvgText(pad.left - 12, y + 4, formatCompactNumber(val), 'axis-text', 'end'));
    });

    // Right Y Axis (Cache Hit Rate %)
    [0, 25, 50, 75, 100].forEach((pct) => {
      const y = pad.top + innerH - (pct / 100) * innerH;
      svg.appendChild(createSvgText(pad.left + innerW + 12, y + 4, `${pct}%`, 'axis-text', 'start'));
    });

    // Build Cache Area Path & Hit Rate Line Path
    let areaPath = '';
    let linePath = '';

    turns.forEach((t, idx) => {
      const x = pad.left + idx * step;
      const yCache = pad.top + innerH - ((t.cumulative_cache_read_tokens || 0) / maxCacheRead) * innerH;
      const yHit = pad.top + innerH - ((t.cache_hit_rate_pct || 0) / 100) * innerH;

      if (idx === 0) {
        areaPath += `M ${x} ${pad.top + innerH} L ${x} ${yCache}`;
        linePath += `M ${x} ${yHit}`;
      } else {
        areaPath += ` L ${x} ${yCache}`;
        linePath += ` L ${x} ${yHit}`;
      }

      // X tick text
      svg.appendChild(createSvgText(x, pad.top + innerH + 20, `T${t.turn_index}`, 'axis-text', 'middle'));

      // Hit rate point
      const pt = document.createElementNS('http://www.w3.org/2000/svg', 'circle');
      pt.setAttribute('cx', x);
      pt.setAttribute('cy', yHit);
      pt.setAttribute('r', '4');
      pt.setAttribute('fill', '#10b981');
      pt.style.cursor = 'pointer';

      pt.addEventListener('mouseenter', (ev) => {
        showTooltip(ev, `
          <div class="tooltip-title">Turn ${t.turn_index}</div>
          <div class="tooltip-row"><span>Cache Hit Rate:</span> <span class="val">${t.cache_hit_rate_pct}%</span></div>
          <div class="tooltip-row"><span>Cum. Cache Read:</span> <span class="val">${formatCompactNumber(t.cumulative_cache_read_tokens)}</span></div>
          <div class="tooltip-row"><span>Turn Cache Read:</span> <span class="val">${formatCompactNumber(t.cache_read_tokens)}</span></div>
          <div class="tooltip-row"><span>Uncached Input:</span> <span class="val">${formatCompactNumber(t.uncached_input_tokens)}</span></div>
        `);
      });
      pt.addEventListener('mousemove', moveTooltip);
      pt.addEventListener('mouseleave', hideTooltip);

      svg.appendChild(pt);
    });

    areaPath += ` L ${pad.left + (numTurns - 1) * step} ${pad.top + innerH} Z`;

    // Render area
    const areaElem = document.createElementNS('http://www.w3.org/2000/svg', 'path');
    areaElem.setAttribute('d', areaPath);
    areaElem.setAttribute('fill', 'rgba(56, 189, 248, 0.18)');
    svg.appendChild(areaElem);

    // Render line
    const lineElem = document.createElementNS('http://www.w3.org/2000/svg', 'path');
    lineElem.setAttribute('d', linePath);
    lineElem.setAttribute('fill', 'none');
    lineElem.setAttribute('stroke', '#10b981');
    lineElem.setAttribute('stroke-width', '2.5');
    svg.appendChild(lineElem);

    svg.appendChild(createSvgLine(pad.left, pad.top + innerH, pad.left + innerW, pad.top + innerH, 'axis-line'));
    svg.appendChild(createSvgLine(pad.left, pad.top, pad.left, pad.top + innerH, 'axis-line'));
    svg.appendChild(createSvgLine(pad.left + innerW, pad.top, pad.left + innerW, pad.top + innerH, 'axis-line'));

    container.appendChild(svg);
  }

  // ==========================================================================
  // RUN GALLERY & CARDS
  // ==========================================================================

  function renderGallery() {
    const grid = document.getElementById('runs-gallery-grid');
    grid.innerHTML = '';
    const runs = getFilteredRuns();

    document.getElementById('gallery-run-count').textContent = `Showing ${runs.length} of ${benchmarkData.runs.length} runs`;

    if (runs.length === 0) {
      grid.innerHTML = '<div style="grid-column: 1/-1; text-align: center; color: #64748b; padding: 3rem;">No benchmark runs match the selected filters.</div>';
      return;
    }

    runs.forEach((run) => {
      const card = document.createElement('div');
      card.className = `run-card ${run.pareto.is_pareto_series ? 'pareto-border' : ''}`;

      const isPass = run.verification.passed;
      const cost = run.cost.estimated_with_harness_usd ?? run.cost.estimated_usd ?? 0;
      const genTime = run.model_time.generating_seconds ?? run.wall_clock.seconds ?? 0;
      const outTokens = run.tokens.total_output ?? 0;
      const reasTokens = run.tokens.reasoning ?? 0;
      const reasPct = outTokens > 0 ? Math.round((reasTokens / outTokens) * 100) : 0;
      const tc = run.tool_calls.total;

      const hasScreenshot = Boolean(run.screenshot_path);

      card.innerHTML = `
        <div class="run-card-header">
          <div>
            <div class="run-card-title">${escapeHtml(run.model.name)}</div>
            <div class="run-card-meta">
              <span class="series-badge">${escapeHtml(run.prompt_id)}</span>
              <span class="provider-badge">${escapeHtml(run.model.provider)}</span>
            </div>
          </div>
          <div>
            ${run.pareto.is_pareto_series ? '<span class="badge pareto">⚡ PARETO</span>' : ''}
            <span class="badge ${isPass ? 'pass' : 'fail'}">${isPass ? '✓ PASSED' : '✗ FAILED'}</span>
          </div>
        </div>

        <div class="card-preview-area" data-runid="${run.run_id}">
          ${
            hasScreenshot
              ? `<img src="${run.screenshot_path}" alt="${escapeHtml(run.model.name)} preview" loading="lazy">`
              : `<div class="card-preview-placeholder">
                  <span>📊 3D / Web App Observatory</span>
                  <span>(No screenshot recorded)</span>
                 </div>`
          }
        </div>

        <div class="card-metrics-grid">
          <div class="metric-cell">
            <span class="label">Est. Cost</span>
            <span class="val">$${cost.toFixed(2)}</span>
          </div>
          <div class="metric-cell">
            <span class="label">Model Time</span>
            <span class="val">${formatDurationSec(genTime)}</span>
          </div>
          <div class="metric-cell">
            <span class="label">Output Tokens</span>
            <span class="val">${formatCompactNumber(outTokens)} <small style="font-size:0.75rem;color:#c084fc;">(${reasPct}%)</small></span>
          </div>
          <div class="metric-cell">
            <span class="label">Tool Calls</span>
            <span class="val">${tc.calls - tc.failures} ✓ <small style="font-size:0.75rem;color:#f87171;">${tc.failures ? `${tc.failures} ✗` : ''}</small></span>
          </div>
        </div>

        <div class="run-card-footer">
          <span style="font-size:0.75rem;color:#64748b;font-family:var(--font-mono);">${escapeHtml(run.run_id.slice(0, 22))}...</span>
          <button class="btn-inspect" data-runid="${run.run_id}">Inspect Details</button>
        </div>
      `;

      card.querySelector('.card-preview-area').addEventListener('click', () => openModal(run));
      card.querySelector('.btn-inspect').addEventListener('click', () => openModal(run));

      grid.appendChild(card);
    });
  }

  // ==========================================================================
  // DRILL-DOWN MODAL INSPECTOR
  // ==========================================================================

  function openModal(run) {
    const isPass = run.verification.passed;
    const statusBadge = document.getElementById('modal-status-badge');
    statusBadge.textContent = isPass ? '✓ PASSED (100%)' : '✗ FAILED';
    statusBadge.className = `badge ${isPass ? 'pass' : 'fail'}`;

    document.getElementById('modal-model-title').textContent = run.model.label || run.model.name;
    document.getElementById('modal-series-tag').textContent = `${run.prompt_id} / ${run.run_id}`;
    document.getElementById('modal-tool-count').textContent = run.tool_timeline ? run.tool_timeline.length : 0;

    // Tab 1: Verification & Runtime
    const scrImg = document.getElementById('modal-screenshot-img');
    const scrPlaceholder = document.getElementById('modal-screenshot-placeholder');
    if (run.screenshot_path) {
      scrImg.src = run.screenshot_path;
      scrImg.style.display = 'block';
      scrPlaceholder.style.display = 'none';
    } else {
      scrImg.style.display = 'none';
      scrPlaceholder.style.display = 'flex';
    }

    const dp = run.verification.data_pipeline || {};
    document.getElementById('modal-probe-score').textContent = `${((dp.score ?? 0) * 100).toFixed(0)}%`;
    document.getElementById('modal-probe-auth').textContent = dp.authenticity || 'n/a';
    document.getElementById('modal-probe-records').textContent = formatCompactNumber(dp.total_records || 0);

    const checksList = document.getElementById('modal-checks-list');
    checksList.innerHTML = '';
    const checks = dp.checks || [];
    if (checks.length === 0) {
      checksList.innerHTML = '<div style="color:#64748b;font-size:0.82rem;">No data pipeline checks recorded.</div>';
    } else {
      checks.forEach((chk) => {
        const item = document.createElement('div');
        item.className = `check-item ${chk.passed ? 'passed' : 'failed'}`;
        item.innerHTML = `
          <div class="check-header">
            <span>${escapeHtml(chk.description || chk.id)}</span>
            <span>${chk.passed ? '✓ PASSED' : '✗ FAILED'}</span>
          </div>
          <div class="check-detail">${escapeHtml(chk.detail || '')}</div>
        `;
        checksList.appendChild(item);
      });
    }

    const rt = run.verification.runtime || {};
    document.getElementById('modal-http-status').textContent = rt.http_status ?? 'n/a';
    document.getElementById('modal-load-time').textContent = rt.load_time_ms ? `${Math.round(rt.load_time_ms)} ms` : 'n/a';
    const dom = rt.dom || {};
    document.getElementById('modal-dom-visuals').textContent = `Canvas: ${dom.canvas_count || 0} / SVG: ${dom.svg_count || 0}`;
    document.getElementById('modal-webgl-context').textContent = dom.webgl_context ? 'Yes' : 'No';
    document.getElementById('modal-console-warnings').textContent = rt.console_warnings_count || 0;

    const errBox = document.getElementById('modal-runtime-errors');
    const errList = document.getElementById('modal-page-errors-list');
    errList.innerHTML = '';
    const pageErrors = rt.page_errors || [];
    if (pageErrors.length > 0) {
      errBox.style.display = 'block';
      pageErrors.forEach((e) => {
        const li = document.createElement('li');
        li.textContent = e;
        errList.appendChild(li);
      });
    } else {
      errBox.style.display = 'none';
    }

    // Tab 2: Tokens & Pricing
    const tok = run.tokens || {};
    document.getElementById('modal-tokens-visible').textContent = formatNumber(tok.visible);
    document.getElementById('modal-tokens-reasoning').textContent = formatNumber(tok.reasoning);
    document.getElementById('modal-tokens-total-output').textContent = formatNumber(tok.total_output);
    document.getElementById('modal-tokens-uncached').textContent = formatNumber(tok.uncached_input);
    document.getElementById('modal-tokens-cache-read').textContent = formatNumber(tok.cache_read);
    document.getElementById('modal-tokens-cache-write').textContent = formatNumber(tok.cache_write);
    document.getElementById('modal-tokens-split-rule').textContent = tok.split_rule || 'standard';

    const cost = run.cost || {};
    document.getElementById('modal-cost-est').textContent = cost.estimated_usd != null ? `$${cost.estimated_usd.toFixed(2)}` : 'n/a';
    document.getElementById('modal-cost-harness').textContent = cost.estimated_with_harness_usd != null ? `$${cost.estimated_with_harness_usd.toFixed(2)}` : 'n/a';
    document.getElementById('modal-cost-billed').textContent = cost.billed_usd != null ? `$${cost.billed_usd.toFixed(2)}` : 'n/a (no CSV)';
    document.getElementById('modal-cost-surcharge').textContent = '$0.25 / 1M tokens';

    const ratesPills = document.getElementById('modal-rates-pills');
    ratesPills.innerHTML = '';
    const rates = cost.rates || {};
    Object.entries(rates).forEach(([k, v]) => {
      const pill = document.createElement('span');
      pill.className = 'rate-pill';
      pill.textContent = `${k}: $${v}`;
      ratesPills.appendChild(pill);
    });

    // Tab 3: Timeline
    setupModalTimeline(run.tool_timeline || []);

    // Tab 4: Metadata
    document.getElementById('modal-meta-run-id').textContent = run.run_id;
    document.getElementById('modal-meta-prompt-id').textContent = run.prompt_id;
    document.getElementById('modal-meta-series-id').textContent = run.series_id;
    document.getElementById('modal-meta-shot').textContent = run.shot;
    document.getElementById('modal-meta-harness').textContent = `${run.harness.name} ${run.harness.version}`;
    document.getElementById('modal-meta-started').textContent = run.wall_clock.started_at || 'n/a';
    document.getElementById('modal-meta-ended').textContent = run.wall_clock.ended_at || 'n/a';
    document.getElementById('modal-meta-wall-time').textContent = formatDurationSec(run.wall_clock.seconds);
    document.getElementById('modal-meta-gen-time').textContent = formatDurationSec(run.model_time.generating_seconds);
    document.getElementById('modal-meta-thinking-time').textContent = formatDurationSec(run.model_time.thinking_seconds);

    // Reset active modal tab
    document.querySelectorAll('.modal-tab').forEach((t) => t.classList.remove('active'));
    document.querySelectorAll('.modal-tab-content').forEach((c) => c.classList.remove('active'));
    document.querySelector('.modal-tab[data-modaltab="verification"]').classList.add('active');
    document.getElementById('modal-tab-verification').classList.add('active');

    modal.style.display = 'flex';
  }

  function setupModalTimeline(timeline) {
    const container = document.getElementById('modal-tool-timeline');
    const searchInput = document.getElementById('timeline-search');
    let activeBucket = 'all';

    function renderTimelineItems() {
      container.innerHTML = '';
      const query = searchInput.value.toLowerCase().trim();

      const filtered = timeline.filter((item) => {
        if (activeBucket === 'failures' && !item.is_failed) return false;
        if (activeBucket !== 'all' && activeBucket !== 'failures' && item.bucket !== activeBucket) return false;
        if (query) {
          const text = `${item.tool_name} ${item.effective_tool_name} ${item.summary}`.toLowerCase();
          if (!text.includes(query)) return false;
        }
        return true;
      });

      if (filtered.length === 0) {
        container.innerHTML = '<div style="color:#64748b;padding:1rem;text-align:center;">No tool calls match criteria.</div>';
        return;
      }

      filtered.forEach((item) => {
        const div = document.createElement('div');
        div.className = `timeline-item ${item.is_failed ? 'failed' : ''}`;
        div.innerHTML = `
          <span class="timeline-idx">#${item.call_index}</span>
          <span class="timeline-bucket ${item.bucket}">${item.bucket}</span>
          <span class="timeline-name" title="${escapeHtml(item.effective_tool_name)}">${escapeHtml(item.effective_tool_name)}</span>
          <span class="timeline-summary" title="${escapeHtml(item.summary)}">${escapeHtml(item.summary)}</span>
          <span class="timeline-dur">${Math.round(item.duration_ms)}ms</span>
          <span class="timeline-status" style="color: ${item.is_failed ? '#f87171' : '#10b981'};">
            ${item.is_failed ? `✗${item.exit_code != null ? item.exit_code : ''}` : '✓'}
          </span>
        `;
        container.appendChild(div);
      });
    }

    document.querySelectorAll('#timeline-bucket-filters button').forEach((btn) => {
      btn.onclick = () => {
        document.querySelectorAll('#timeline-bucket-filters button').forEach((b) => b.classList.remove('active'));
        btn.classList.add('active');
        activeBucket = btn.dataset.bucket;
        renderTimelineItems();
      };
    });

    searchInput.oninput = renderTimelineItems;
    renderTimelineItems();
  }

  function closeModal() {
    modal.style.display = 'none';
  }

  // ==========================================================================
  // SVG Chart Utilities
  // ==========================================================================

  function createSvg(width, height) {
    const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    svg.setAttribute('viewBox', `0 0 ${width} ${height}`);
    svg.setAttribute('class', 'chart-svg');
    return svg;
  }

  function createSvgLine(x1, y1, x2, y2, className) {
    const line = document.createElementNS('http://www.w3.org/2000/svg', 'line');
    line.setAttribute('x1', x1);
    line.setAttribute('y1', y1);
    line.setAttribute('x2', x2);
    line.setAttribute('y2', y2);
    if (className) line.setAttribute('class', className);
    return line;
  }

  function createSvgRect(x, y, width, height, fill) {
    const rect = document.createElementNS('http://www.w3.org/2000/svg', 'rect');
    rect.setAttribute('x', x);
    rect.setAttribute('y', y);
    rect.setAttribute('width', Math.max(0, width));
    rect.setAttribute('height', Math.max(0, height));
    rect.setAttribute('fill', fill);
    rect.setAttribute('rx', '2');
    return rect;
  }

  function createSvgText(x, y, text, className, anchor = 'start') {
    const el = document.createElementNS('http://www.w3.org/2000/svg', 'text');
    el.setAttribute('x', x);
    el.setAttribute('y', y);
    el.setAttribute('class', className);
    el.setAttribute('text-anchor', anchor);
    el.textContent = text;
    return el;
  }

  function getTicks(min, max, count) {
    const span = max - min;
    if (span <= 0) return [min];
    const step = span / count;
    const ticks = [];
    for (let i = 0; i <= count; i++) {
      ticks.push(min + i * step);
    }
    return ticks;
  }

  // ==========================================================================
  // Tooltip Helpers
  // ==========================================================================

  function showTooltip(e, html) {
    tooltip.innerHTML = html;
    tooltip.style.display = 'block';
    moveTooltip(e);
  }

  function moveTooltip(e) {
    const pad = 12;
    let x = e.clientX + pad;
    let y = e.clientY + pad;

    const tw = tooltip.offsetWidth || 220;
    const th = tooltip.offsetHeight || 120;

    if (x + tw > window.innerWidth) {
      x = e.clientX - tw - pad;
    }
    if (y + th > window.innerHeight) {
      y = e.clientY - th - pad;
    }

    tooltip.style.left = `${Math.max(8, x)}px`;
    tooltip.style.top = `${Math.max(8, y)}px`;
  }

  function hideTooltip() {
    tooltip.style.display = 'none';
  }

  // ==========================================================================
  // Formatting Utilities
  // ==========================================================================

  function formatCompactNumber(num) {
    if (num == null) return '-';
    if (num >= 1000000) return `${(num / 1000000).toFixed(1)}M`;
    if (num >= 1000) return `${(num / 1000).toFixed(1)}k`;
    return num.toString();
  }

  function formatNumber(num) {
    if (num == null) return 'n/a';
    return Number(num).toLocaleString();
  }

  function formatDurationSec(sec) {
    if (sec == null) return 'n/a';
    const m = Math.floor(sec / 60);
    const s = Math.round(sec % 60);
    if (m === 0) return `${s}s`;
    return `${m}m ${s < 10 ? '0' : ''}${s}s`;
  }

  function truncate(str, len) {
    if (!str) return '';
    return str.length > len ? `${str.slice(0, len)}…` : str;
  }

  function escapeHtml(str) {
    if (!str) return '';
    return String(str)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }

  function debounce(fn, ms) {
    let timer;
    return (...args) => {
      clearTimeout(timer);
      timer = setTimeout(() => fn(...args), ms);
    };
  }

  // Bootstrap when DOM ready
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
