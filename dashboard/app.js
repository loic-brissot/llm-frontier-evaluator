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
  let cacheChartMode = 'bars'; // 'bars' or 'scatter'
  let selectedCacheRunId = null;
  let currentModalRunId = null;
  let showcasePromptId = null;
  let showcaseRunId = null;

  // DOM Elements
  const tooltip = document.getElementById('chart-tooltip');
  const modal = document.getElementById('run-modal');

  // ==========================================================================
  // Data Loading & Bootstrapping (Decoupled Web Fetching & Offline Fallback)
  // ==========================================================================

  function showLoading() {
    const overlay = document.getElementById('loading-overlay');
    if (overlay) {
      overlay.classList.remove('fade-out');
      overlay.classList.add('active');
    }
  }

  function hideLoading() {
    const overlay = document.getElementById('loading-overlay');
    if (overlay) {
      overlay.classList.remove('active');
      overlay.classList.add('fade-out');
      setTimeout(() => {
        overlay.classList.remove('fade-out');
      }, 400);
    }
  }

  function getEmbeddedData() {
    const embeddedScript = document.getElementById('benchmark-data');
    if (embeddedScript && embeddedScript.textContent.trim().length > 0) {
      try {
        return JSON.parse(embeddedScript.textContent);
      } catch (err) {
        console.warn('Could not parse embedded benchmark data:', err);
      }
    }
    return null;
  }

  async function loadData() {
    const isWeb = typeof window !== 'undefined' &&
      typeof window.location !== 'undefined' &&
      (window.location.protocol === 'http:' || window.location.protocol === 'https:');

    if (isWeb) {
      showLoading();
      try {
        const resp = await fetch('./data.json');
        if (!resp.ok) {
          throw new Error(`Failed to load ./data.json: HTTP ${resp.status}`);
        }
        return await resp.json();
      } catch (err) {
        console.warn('Network fetch of ./data.json failed, falling back to embedded benchmark data:', err);
        const embedded = getEmbeddedData();
        if (embedded) {
          return embedded;
        }
        throw err;
      } finally {
        hideLoading();
      }
    }

    // Offline / file:// protocol mode
    const embedded = getEmbeddedData();
    if (embedded) {
      return embedded;
    }

    // Secondary fallback in case file:// or local environment supports fetch
    try {
      const resp = await fetch('./data.json');
      if (resp.ok) {
        return await resp.json();
      }
    } catch (_) {}

    throw new Error('No benchmark data found: embedded script is empty and local fetch failed');
  }

  // ==========================================================================
  // URL Parameter Synchronization & Deep Linking
  // ==========================================================================

  function updateUrlParams(options = {}) {
    try {
      if (typeof window === 'undefined' || !window.location) return;
      const url = new URL(window.location.href);

      // Active tab (omit default 'pareto' to keep base URL clean)
      if (activeTab && activeTab !== 'pareto') {
        url.searchParams.set('tab', activeTab);
      } else {
        url.searchParams.delete('tab');
      }

      // Prompt / Series (canonical URL param is 'prompt')
      if (filters.series && filters.series !== 'all') {
        url.searchParams.set('prompt', filters.series);
        url.searchParams.delete('series');
      } else {
        url.searchParams.delete('prompt');
        url.searchParams.delete('series');
      }

      // Provider
      if (filters.provider && filters.provider !== 'all') {
        url.searchParams.set('provider', filters.provider);
      } else {
        url.searchParams.delete('provider');
      }

      // Status
      if (filters.status && filters.status !== 'all') {
        url.searchParams.set('status', filters.status);
      } else {
        url.searchParams.delete('status');
      }

      // Sort
      if (filters.sort && filters.sort !== 'pareto') {
        url.searchParams.set('sort', filters.sort);
      } else {
        url.searchParams.delete('sort');
      }

      // Modal run ID
      if (currentModalRunId) {
        url.searchParams.set('run', currentModalRunId);
      } else {
        url.searchParams.delete('run');
      }

      // Showcase params
      if (activeTab === 'showcase') {
        if (showcasePromptId) {
          url.searchParams.set('showcase_prompt', showcasePromptId);
        }
        if (showcaseRunId) {
          url.searchParams.set('showcase_run', showcaseRunId);
        }
      } else {
        url.searchParams.delete('showcase_prompt');
        url.searchParams.delete('showcase_run');
      }

      const queryString = url.searchParams.toString();
      const newUrl = url.pathname + (queryString ? `?${queryString}` : '') + url.hash;
      const currentUrl = window.location.pathname + window.location.search + window.location.hash;

      if (newUrl !== currentUrl) {
        if (options.replace) {
          window.history.replaceState(null, '', newUrl);
        } else {
          window.history.pushState(null, '', newUrl);
        }
      }
    } catch (err) {
      console.debug('Failed to update URL parameters:', err);
    }
  }

  function updateControlsBarVisibility(tabName) {
    const controlsBar = document.getElementById('global-controls-bar') || document.querySelector('.controls-bar');
    if (!controlsBar) return;
    if (tabName === 'showcase' || tabName === 'warehouse') {
      controlsBar.style.display = 'none';
    } else {
      controlsBar.style.display = '';
    }
  }

  function switchTab(tabName, updateHistory = true) {
    const tabBtn = document.querySelector(`.nav-tab[data-tab="${tabName}"]`);
    const tabContent = document.getElementById(`tab-${tabName}`);
    if (!tabBtn || !tabContent) return;

    document.querySelectorAll('.nav-tab').forEach((b) => b.classList.remove('active'));
    document.querySelectorAll('.tab-content').forEach((c) => c.classList.remove('active'));

    tabBtn.classList.add('active');
    tabContent.classList.add('active');
    activeTab = tabName;
    updateControlsBarVisibility(tabName);

    updateControlsBarVisibility(tabName);

    if (updateHistory !== false) {
      updateUrlParams();
    }
  }

  function restoreStateFromUrl(options = { updateHistory: false }) {
    try {
      if (typeof window === 'undefined' || !window.location) return;
      const params = new URLSearchParams(window.location.search);

      // Active tab
      const tabParam = params.get('tab');
      if (tabParam && ['pareto', 'analytics', 'gallery', 'showcase', 'warehouse'].includes(tabParam)) {
        switchTab(tabParam, false);
      }

      // Showcase prompt and run URL params
      const scPrompt = params.get('showcase_prompt');
      if (scPrompt) {
        showcasePromptId = scPrompt;
      }
      const scRun = params.get('showcase_run');
      if (scRun) {
        showcaseRunId = scRun;
      }

      // Prompt / Series filter (supports ?prompt=... or ?series=...)
      const promptParam = params.get('prompt') || params.get('series');
      if (promptParam) {
        filters.series = promptParam;
        const seriesSelect = document.getElementById('filter-series');
        if (seriesSelect) {
          seriesSelect.value = promptParam;
        }
      }

      // Status filter
      const statusParam = params.get('status');
      if (statusParam && ['all', 'passed', 'failed'].includes(statusParam)) {
        filters.status = statusParam;
        const statusSelect = document.getElementById('filter-status');
        if (statusSelect) {
          statusSelect.value = statusParam;
        }
      }

      // Provider filter
      const providerParam = params.get('provider');
      if (providerParam) {
        filters.provider = providerParam;
        const providerSelect = document.getElementById('filter-provider');
        if (providerSelect) {
          providerSelect.value = providerParam;
        }
      }

      // Sort
      const sortParam = params.get('sort');
      if (sortParam) {
        const normalizedSort = sortParam.replace('_', '-');
        if (['pareto', 'cost-asc', 'cost-desc', 'time-asc', 'time-desc', 'tokens-desc', 'name-asc'].includes(normalizedSort)) {
          filters.sort = normalizedSort;
          const sortSelect = document.getElementById('filter-sort');
          if (sortSelect) {
            sortSelect.value = normalizedSort;
          }
        }
      }

      // Run modal
      const runParam = params.get('run');
      if (runParam && benchmarkData && benchmarkData.runs) {
        const targetRun = benchmarkData.runs.find((r) => r.run_id === runParam);
        if (targetRun) {
          openModal(targetRun, false);
        }
      } else if (!runParam && currentModalRunId) {
        closeModal(false);
      }

      if (options.updateHistory) {
        updateUrlParams({ replace: true });
      }
    } catch (err) {
      console.warn('Could not restore state from URL:', err);
    }
  }

  async function init() {
    try {
      benchmarkData = await loadData();
      setupHeaderStats();
      setupFilterDropdowns();
      setupEventListeners();
      restoreStateFromUrl({ updateHistory: false });
      updateControlsBarVisibility(activeTab);
      renderAllViews();
    } catch (err) {
      console.error('Failed to initialize dashboard:', err);
      document.body.innerHTML = `
        <div style="padding: 2rem; color: #f87171; font-family: monospace;">
          <h2>Failed to load benchmark data</h2>
          <p>${escapeHtml(err.message)}</p>
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

    // Cache curve run selector (optional / guarded)
    const cacheRunSelect = document.getElementById('select-cache-run');
    if (cacheRunSelect) {
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
  }

  function setupEventListeners() {
    // Tabs Navigation
    document.querySelectorAll('.nav-tab').forEach((tabBtn) => {
      tabBtn.addEventListener('click', () => {
        switchTab(tabBtn.dataset.tab);
        renderAllViews();
      });
    });

    // Filter controls
    document.getElementById('filter-series').addEventListener('change', (e) => {
      filters.series = e.target.value;
      updateUrlParams();
      renderAllViews();
    });

    document.getElementById('filter-status').addEventListener('change', (e) => {
      filters.status = e.target.value;
      updateUrlParams();
      renderAllViews();
    });

    document.getElementById('filter-provider').addEventListener('change', (e) => {
      filters.provider = e.target.value;
      updateUrlParams();
      renderAllViews();
    });

    document.getElementById('filter-search').addEventListener('input', (e) => {
      filters.search = e.target.value.toLowerCase().trim();
      renderAllViews();
    });

    document.getElementById('filter-sort').addEventListener('change', (e) => {
      filters.sort = e.target.value;
      updateUrlParams();
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

    // Pricing tier chart controls
    document.querySelectorAll('[data-pricing-sort]').forEach((btn) => {
      btn.addEventListener('click', () => {
        pricingState.sort = btn.dataset.pricingSort;
        document.querySelectorAll('[data-pricing-sort]').forEach((b) => b.classList.toggle('active', b === btn));
        renderPricingTiersChart();
      });
    });
    document.querySelectorAll('[data-pricing-scale]').forEach((btn) => {
      btn.addEventListener('click', () => {
        pricingState.scale = btn.dataset.pricingScale;
        document.querySelectorAll('[data-pricing-scale]').forEach((b) => b.classList.toggle('active', b === btn));
        renderPricingTiersChart();
      });
    });

    // Cache efficiency chart mode toggles
    const btnCacheBars = document.getElementById('btn-cache-mode-bars');
    const btnCacheScatter = document.getElementById('btn-cache-mode-scatter');
    if (btnCacheBars) {
      btnCacheBars.addEventListener('click', () => {
        cacheChartMode = 'bars';
        btnCacheBars.classList.add('active');
        if (btnCacheScatter) btnCacheScatter.classList.remove('active');
        renderCacheCurveChart();
      });
    }
    if (btnCacheScatter) {
      btnCacheScatter.addEventListener('click', () => {
        cacheChartMode = 'scatter';
        btnCacheScatter.classList.add('active');
        if (btnCacheBars) btnCacheBars.classList.remove('active');
        renderCacheCurveChart();
      });
    }

    const selectCacheRun = document.getElementById('select-cache-run');
    if (selectCacheRun) {
      selectCacheRun.addEventListener('change', (e) => {
        selectedCacheRunId = e.target.value;
        renderCacheCurveChart();
      });
    }

    // Modal close events
    document.getElementById('modal-close-btn').addEventListener('click', () => closeModal());
    modal.addEventListener('click', (e) => {
      if (e.target === modal) closeModal();
    });
    window.addEventListener('keydown', (e) => {
      if (e.key === 'Escape' && modal.style.display !== 'none') closeModal();
    });

    // Browser history popstate (back / forward navigation)
    window.addEventListener('popstate', () => {
      restoreStateFromUrl({ updateHistory: false });
      renderAllViews();
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
          const isParetoA = Boolean(a.verification && a.verification.passed && a.pareto && a.pareto.is_pareto_series);
          const isParetoB = Boolean(b.verification && b.verification.passed && b.pareto && b.pareto.is_pareto_series);
          const pA = isParetoA ? 1 : 0;
          const pB = isParetoB ? 1 : 0;
          if (pA !== pB) return pB - pA;
          const qA = a.pareto?.quality_score ?? 0;
          const qB = b.pareto?.quality_score ?? 0;
          if (qA !== qB) return qB - qA;
          return costA - costB;
      }
    });
  }

  function renderAllViews() {
    updateControlsBarVisibility(activeTab);
    if (activeTab === 'pareto') {
      renderParetoChart();
    } else if (activeTab === 'analytics') {
      renderTokensChart();
      renderTimeChart();
      renderToolsChart();
      renderCostCompareChart();
      renderCacheCurveChart();
      renderPricingTiersChart();
    } else if (activeTab === 'gallery') {
      renderGallery();
    } else if (activeTab === 'showcase') {
      renderShowcase();
    } else if (activeTab === 'warehouse') {
      renderWarehouse();
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
      if (!r.verification || !r.verification.passed) return false;
      if (r.verification.runtime && r.verification.runtime.passed === false) return false;
      // Pareto efficiency is always evaluated per prompt (series-scoped), never pooled across prompts.
      if (paretoState.mode === 'passing') {
        return Boolean(r.pareto.is_pareto_successful_series ?? r.pareto.is_pareto_series);
      }
      return Boolean(r.pareto.is_pareto_series);
    });

    // Sort Pareto runs by time ascending
    paretoRuns.sort((a, b) => {
      const pc = String(a.prompt_id).localeCompare(String(b.prompt_id));
      if (pc !== 0) return pc;
      const ta = a.model_time.generating_seconds ?? a.wall_clock.seconds;
      const tb = b.model_time.generating_seconds ?? b.wall_clock.seconds;
      return ta - tb;
    });

    // Render one Pareto frontier line per prompt (frontiers are never joined across prompts)
    const paretoByPrompt = new Map();
    paretoRuns.forEach((r) => {
      if (!paretoByPrompt.has(r.prompt_id)) paretoByPrompt.set(r.prompt_id, []);
      paretoByPrompt.get(r.prompt_id).push(r);
    });
    paretoByPrompt.forEach((group) => {
      if (group.length < 2) return;
      let d = '';
      group.forEach((r, idx) => {
        const t = r.model_time.generating_seconds ?? r.wall_clock.seconds;
        const c = r.cost.estimated_with_harness_usd ?? r.cost.estimated_usd;
        d += `${idx === 0 ? 'M' : ' L'} ${scaleX(t)} ${scaleY(c)}`;
      });
      const path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
      path.setAttribute('d', d);
      path.setAttribute('class', 'pareto-line');
      svg.appendChild(path);
    });

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
      g.style.transformBox = 'fill-box';
      g.style.transformOrigin = 'center';

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

    let currentPrompt = null;
    paretoRuns.forEach((r) => {
      if (r.prompt_id !== currentPrompt) {
        currentPrompt = r.prompt_id;
        const count = paretoRuns.filter((x) => x.prompt_id === currentPrompt).length;
        const hdr = document.createElement('tr');
        hdr.className = 'pareto-prompt-group';
        hdr.innerHTML = `<td colspan="8"><span class="series-badge">${escapeHtml(currentPrompt)}</span> <span style="font-size:0.75rem;color:#64748b;">${count} Pareto-optimal run${count === 1 ? '' : 's'} for this prompt</span></td>`;
        tbody.appendChild(hdr);
      }
      const tr = document.createElement('tr');
      const isPass = r.verification.passed;
      const c = r.cost.estimated_with_harness_usd ?? r.cost.estimated_usd ?? 0;
      const t = r.model_time.generating_seconds ?? r.wall_clock.seconds ?? 0;
      const tok = r.tokens.total_output ?? 0;

      const demoBtnHtml = r.demo_url
        ? `<a href="${escapeHtml(r.demo_url)}" target="_blank" rel="noopener noreferrer" class="btn-demo-action" title="Launch packaged demo">🚀 Demo</a>`
        : '';

      tr.innerHTML = `
        <td><span class="badge ${isPass ? 'pass' : 'fail'}">${isPass ? '✓ PASS' : '✗ FAIL'}</span></td>
        <td><strong>${escapeHtml(r.model.name)}</strong> <span style="font-size:0.75rem;color:#64748b;">(${escapeHtml(r.model.provider)})</span></td>
        <td><span class="series-badge">${escapeHtml(r.prompt_id)}</span></td>
        <td style="font-family:var(--font-mono);">$${c.toFixed(2)}</td>
        <td style="font-family:var(--font-mono);">${formatDurationSec(t)}</td>
        <td style="font-family:var(--font-mono);">${((r.pareto.quality_score ?? 0) * 100).toFixed(0)}%</td>
        <td style="font-family:var(--font-mono);">${formatCompactNumber(tok)}</td>
        <td>
          <div class="table-actions">
            <button class="btn-inspect" data-runid="${r.run_id}">Inspect</button>
            ${demoBtnHtml}
          </div>
        </td>
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
  // CHART 5: CONTEXT RE-READ INFLATION & TURN/STEP CACHE EFFICIENCY
  // ==========================================================================

  function renderCacheCurveChart() {
    const container = document.getElementById('chart-cache-curve');
    if (!container) return;
    container.innerHTML = '';

    const allRuns = getFilteredRuns();
    const runs = allRuns.filter((r) => r.tokens && (r.tokens.cache_read != null || r.tokens.uncached_input != null));

    if (runs.length === 0) {
      container.innerHTML = '<div style="display:flex;align-items:center;justify-content:center;height:100%;color:#64748b;padding:3rem;">No context token telemetry available for selected filters.</div>';
      return;
    }

    const width = container.clientWidth || 1100;
    const height = 400;

    if (cacheChartMode === 'bars') {
      // Sort runs by total context re-read tokens ascending (cache_read + uncached_input)
      const sortedRuns = [...runs].sort((a, b) => {
        const totA = (a.tokens.cache_read ?? 0) + (a.tokens.uncached_input ?? 0);
        const totB = (b.tokens.cache_read ?? 0) + (b.tokens.uncached_input ?? 0);
        return totA - totB;
      });

      const pad = { top: 45, right: 65, bottom: 90, left: 80 };
      const innerW = width - pad.left - pad.right;
      const innerH = height - pad.top - pad.bottom;

      const svg = createSvg(width, height);

      const maxTotal = Math.max(
        ...sortedRuns.map((r) => (r.tokens.cache_read ?? 0) + (r.tokens.uncached_input ?? 0)),
        1000
      ) * 1.18;

      // Left Y Axis (Total Context Tokens Re-Read)
      const leftTicks = getTicks(0, maxTotal, 5);
      leftTicks.forEach((val) => {
        const y = pad.top + innerH - (val / maxTotal) * innerH;
        svg.appendChild(createSvgLine(pad.left, y, pad.left + innerW, y, 'grid-line'));
        svg.appendChild(createSvgText(pad.left - 10, y + 4, formatCompactNumber(val), 'axis-text', 'end'));
      });
      const leftLabel = createSvgText(22, pad.top + innerH / 2, 'Total Context Tokens Re-Read', 'axis-label', 'middle');
      leftLabel.setAttribute('transform', `rotate(-90 22 ${pad.top + innerH / 2})`);
      svg.appendChild(leftLabel);

      // Right Y Axis (Cache Hit Rate %)
      [0, 25, 50, 75, 100].forEach((pct) => {
        const y = pad.top + innerH - (pct / 100) * innerH;
        svg.appendChild(createSvgText(pad.left + innerW + 10, y + 4, `${pct}%`, 'axis-text', 'start'));
      });
      const rightLabel = createSvgText(pad.left + innerW + 55, pad.top + innerH / 2, 'Cache Hit Rate (%)', 'axis-label', 'middle');
      rightLabel.setAttribute('transform', `rotate(90 ${pad.left + innerW + 55} ${pad.top + innerH / 2})`);
      svg.appendChild(rightLabel);

      const step = innerW / sortedRuns.length;
      const barW = Math.max(16, Math.min(52, Math.floor(step) - 14));

      // Line points for Cache Hit Rate curve
      const hitPoints = [];

      sortedRuns.forEach((r, idx) => {
        const cx = pad.left + idx * step + step / 2;
        const x = cx - barW / 2;

        const cacheRead = r.tokens.cache_read ?? 0;
        const uncached = r.tokens.uncached_input ?? 0;
        const totContext = cacheRead + uncached;
        const totalOutput = Math.max(1, r.tokens.total_output || 1);
        const numTurns = (r.turns && r.turns.length > 0) ? r.turns.length : 1;
        const toolCalls = r.tool_calls?.total?.calls ?? 0;
        const hitRate = totContext > 0 ? (cacheRead / totContext) * 100 : 0;
        const ampRatio = totContext / totalOutput;

        const hCache = (cacheRead / maxTotal) * innerH;
        const hUncached = (uncached / maxTotal) * innerH;

        const yCache = pad.top + innerH - hCache;
        const yUncached = yCache - hUncached;

        const g = document.createElementNS('http://www.w3.org/2000/svg', 'g');
        g.style.cursor = 'pointer';

        // Cached read rect (bottom portion)
        if (hCache > 0) {
          const rCache = createSvgRect(x, yCache, barW, hCache, '#38bdf8');
          g.appendChild(rCache);
        }
        // Uncached input rect (stacked on top)
        if (hUncached > 0) {
          const rUncached = createSvgRect(x, yUncached, barW, hUncached, '#f59e0b');
          g.appendChild(rUncached);
        }

        // Compact SVG badge label above each bar showing turn count and tool calls: e.g. 1T · 28c or 4T · 173c
        const badgeY = Math.max(pad.top + 6, yUncached - 12);
        const badgeText = `${numTurns}T · ${toolCalls}c`;
        const isMultiTurn = numTurns > 1;
        const badgeWidth = badgeText.length * 6.5 + 10;
        const badgeHeight = 16;
        const badgeX = cx - badgeWidth / 2;

        const badgeRect = document.createElementNS('http://www.w3.org/2000/svg', 'rect');
        badgeRect.setAttribute('x', badgeX);
        badgeRect.setAttribute('y', badgeY - badgeHeight / 2 - 2);
        badgeRect.setAttribute('width', badgeWidth);
        badgeRect.setAttribute('height', badgeHeight);
        badgeRect.setAttribute('rx', '3');
        badgeRect.setAttribute('ry', '3');
        badgeRect.setAttribute('fill', isMultiTurn ? 'rgba(239, 68, 68, 0.22)' : 'rgba(16, 185, 129, 0.16)');
        badgeRect.setAttribute('stroke', isMultiTurn ? '#ef4444' : '#10b981');
        badgeRect.setAttribute('stroke-width', '1');
        g.appendChild(badgeRect);

        const badgeTxt = createSvgText(cx, badgeY + 2, badgeText, 'axis-text', 'middle');
        badgeTxt.setAttribute('font-size', '9px');
        badgeTxt.setAttribute('font-weight', '600');
        badgeTxt.setAttribute('fill', isMultiTurn ? '#fca5a5' : '#6ee7b7');
        g.appendChild(badgeTxt);

        // X Label (rotated model name)
        const xLabel = createSvgText(cx, pad.top + innerH + 16, truncate(r.model.name, 12), 'axis-text', 'end');
        xLabel.setAttribute('transform', `rotate(-45 ${cx} ${pad.top + innerH + 16})`);
        svg.appendChild(xLabel);

        // Tooltip & click handler
        const tooltipHtml = `
          <div class="tooltip-title">${escapeHtml(r.model.name)}</div>
          <div class="tooltip-row"><span>Series:</span> <span class="val">${escapeHtml(r.prompt_id)}</span></div>
          <div class="tooltip-row"><span>Turns &amp; Tools:</span> <span class="val">${numTurns} Turn${numTurns > 1 ? 's' : ''} · ${toolCalls} calls</span></div>
          <div class="tooltip-row"><span>Total Context Re-Read:</span> <span class="val">${formatCompactNumber(totContext)}</span></div>
          <div class="tooltip-row"><span>Cached Context Read:</span> <span class="val">${formatCompactNumber(cacheRead)}</span></div>
          <div class="tooltip-row"><span>Uncached Input:</span> <span class="val">${formatCompactNumber(uncached)}</span></div>
          <div class="tooltip-row"><span>Cache Hit Rate:</span> <span class="val">${hitRate.toFixed(1)}%</span></div>
          <div class="tooltip-row"><span>Re-Read Amplification:</span> <span class="val">${ampRatio.toFixed(1)}x input/output</span></div>
        `;

        g.addEventListener('mouseenter', (ev) => showTooltip(ev, tooltipHtml));
        g.addEventListener('mousemove', moveTooltip);
        g.addEventListener('mouseleave', hideTooltip);
        g.addEventListener('click', () => openModal(r));

        svg.appendChild(g);

        // Cache Hit Rate point on right Y axis
        const yHit = pad.top + innerH - (Math.min(100, Math.max(0, hitRate)) / 100) * innerH;
        hitPoints.push({ cx, yHit, tooltipHtml, run: r });
      });

      // Draw Cache Hit Rate line
      if (hitPoints.length > 1) {
        let lineD = '';
        hitPoints.forEach((pt, idx) => {
          lineD += `${idx === 0 ? 'M' : 'L'} ${pt.cx} ${pt.yHit}`;
        });
        const hitPath = document.createElementNS('http://www.w3.org/2000/svg', 'path');
        hitPath.setAttribute('d', lineD);
        hitPath.setAttribute('fill', 'none');
        hitPath.setAttribute('stroke', '#10b981');
        hitPath.setAttribute('stroke-width', '2.5');
        hitPath.setAttribute('stroke-dasharray', '3,3');
        svg.appendChild(hitPath);
      }

      // Draw Cache Hit Rate dots
      hitPoints.forEach((pt) => {
        const dot = document.createElementNS('http://www.w3.org/2000/svg', 'circle');
        dot.setAttribute('cx', pt.cx);
        dot.setAttribute('cy', pt.yHit);
        dot.setAttribute('r', '4.5');
        dot.setAttribute('fill', '#10b981');
        dot.setAttribute('stroke', '#0f172a');
        dot.setAttribute('stroke-width', '1.5');
        dot.style.cursor = 'pointer';

        dot.addEventListener('mouseenter', (ev) => showTooltip(ev, pt.tooltipHtml));
        dot.addEventListener('mousemove', moveTooltip);
        dot.addEventListener('mouseleave', hideTooltip);
        dot.addEventListener('click', () => openModal(pt.run));

        svg.appendChild(dot);
      });

      // Axis lines
      svg.appendChild(createSvgLine(pad.left, pad.top + innerH, pad.left + innerW, pad.top + innerH, 'axis-line'));
      svg.appendChild(createSvgLine(pad.left, pad.top, pad.left, pad.top + innerH, 'axis-line'));
      svg.appendChild(createSvgLine(pad.left + innerW, pad.top, pad.left + innerW, pad.top + innerH, 'axis-line'));

      container.appendChild(svg);
    } else {
      // Mode 'scatter': Turns & Agentic Tool Steps vs. Total Context Re-Read Scatter/Bubble
      const pad = { top: 35, right: 60, bottom: 60, left: 85 };
      const innerW = width - pad.left - pad.right;
      const innerH = height - pad.top - pad.bottom;

      const svg = createSvg(width, height);

      const maxCalls = Math.max(...runs.map((r) => r.tool_calls?.total?.calls ?? 0), 10) * 1.15;
      const maxContext = Math.max(
        ...runs.map((r) => (r.tokens.cache_read ?? 0) + (r.tokens.uncached_input ?? 0)),
        1000
      ) * 1.15;

      const scaleX = (calls) => pad.left + (calls / maxCalls) * innerW;
      const scaleY = (ctx) => pad.top + innerH - (ctx / maxContext) * innerH;

      // X grid & ticks
      const xTicks = getTicks(0, maxCalls, 6);
      xTicks.forEach((val) => {
        const x = scaleX(val);
        svg.appendChild(createSvgLine(x, pad.top, x, pad.top + innerH, 'grid-line'));
        svg.appendChild(createSvgText(x, pad.top + innerH + 18, Math.round(val).toString(), 'axis-text', 'middle'));
      });
      svg.appendChild(createSvgText(pad.left + innerW / 2, pad.top + innerH + 45, 'Agentic Tool Calls (Steps)', 'axis-label', 'middle'));

      // Y grid & ticks
      const yTicks = getTicks(0, maxContext, 5);
      yTicks.forEach((val) => {
        const y = scaleY(val);
        svg.appendChild(createSvgLine(pad.left, y, pad.left + innerW, y, 'grid-line'));
        svg.appendChild(createSvgText(pad.left - 12, y + 4, formatCompactNumber(val), 'axis-text', 'end'));
      });
      const yLabel = createSvgText(22, pad.top + innerH / 2, 'Total Context Re-Read Tokens (Cached + Fresh)', 'axis-label', 'middle');
      yLabel.setAttribute('transform', `rotate(-90 22 ${pad.top + innerH / 2})`);
      svg.appendChild(yLabel);

      // Shaded efficiency zone in bottom-left for 1-turn low-step low-context runs
      const zoneW = innerW * 0.35;
      const zoneH = innerH * 0.35;
      const zoneRect = document.createElementNS('http://www.w3.org/2000/svg', 'rect');
      zoneRect.setAttribute('x', pad.left);
      zoneRect.setAttribute('y', pad.top + innerH - zoneH);
      zoneRect.setAttribute('width', zoneW);
      zoneRect.setAttribute('height', zoneH);
      zoneRect.setAttribute('fill', 'rgba(16, 185, 129, 0.06)');
      zoneRect.setAttribute('stroke', 'rgba(16, 185, 129, 0.25)');
      zoneRect.setAttribute('stroke-dasharray', '4,4');
      svg.appendChild(zoneRect);

      const zoneText = createSvgText(pad.left + 10, pad.top + innerH - zoneH + 16, '⚡ High Efficiency Zone (1-Turn / Low Re-Read)', 'axis-text', 'start');
      zoneText.setAttribute('fill', '#10b981');
      zoneText.setAttribute('font-size', '10px');
      zoneText.setAttribute('font-weight', '600');
      svg.appendChild(zoneText);

      // Linear reference trend line showing context scaling with steps
      const avgContextPerStep = runs.reduce((acc, r) => {
        const calls = r.tool_calls?.total?.calls ?? 0;
        const tot = (r.tokens.cache_read ?? 0) + (r.tokens.uncached_input ?? 0);
        return acc + (calls > 0 ? tot / calls : 0);
      }, 0) / Math.max(1, runs.length);

      const trendEndX = maxCalls;
      const trendEndY = Math.min(maxContext, avgContextPerStep * maxCalls);
      const trendLine = createSvgLine(scaleX(0), scaleY(0), scaleX(trendEndX), scaleY(trendEndY), 'pareto-line');
      trendLine.setAttribute('stroke', '#64748b');
      trendLine.setAttribute('stroke-dasharray', '5,5');
      svg.appendChild(trendLine);

      // Context Amplification Ratio determines bubble radius
      const maxAmp = Math.max(...runs.map((r) => {
        const tot = (r.tokens.cache_read ?? 0) + (r.tokens.uncached_input ?? 0);
        const out = Math.max(1, r.tokens.total_output || 1);
        return tot / out;
      }), 1);
      const minR = 6;
      const maxR = 22;
      const getRadius = (amp) => minR + (Math.min(amp, maxAmp) / maxAmp) * (maxR - minR);

      // Render Scatter Points
      runs.forEach((r) => {
        const calls = r.tool_calls?.total?.calls ?? 0;
        const cacheRead = r.tokens.cache_read ?? 0;
        const uncached = r.tokens.uncached_input ?? 0;
        const totContext = cacheRead + uncached;
        const totalOutput = Math.max(1, r.tokens.total_output || 1);
        const numTurns = (r.turns && r.turns.length > 0) ? r.turns.length : 1;
        const isMultiTurn = numTurns > 1;
        const hitRate = totContext > 0 ? (cacheRead / totContext) * 100 : 0;
        const ampRatio = totContext / totalOutput;

        const cx = scaleX(calls);
        const cy = scaleY(totContext);
        const radius = getRadius(ampRatio);

        const g = document.createElementNS('http://www.w3.org/2000/svg', 'g');
        g.style.cursor = 'pointer';

        // Bubble Circle
        const circle = document.createElementNS('http://www.w3.org/2000/svg', 'circle');
        circle.setAttribute('cx', cx);
        circle.setAttribute('cy', cy);
        circle.setAttribute('r', radius);
        circle.setAttribute('fill', isMultiTurn ? '#f59e0b' : '#10b981');
        circle.setAttribute('fill-opacity', '0.75');
        circle.setAttribute('stroke', isMultiTurn ? '#d97706' : '#059669');
        circle.setAttribute('stroke-width', '2');
        g.appendChild(circle);

        // Point label: `${truncate(r.model.name, 10)} (${numTurns}T)`
        const pointLabel = createSvgText(cx + radius + 4, cy + 3, `${truncate(r.model.name, 10)} (${numTurns}T)`, 'axis-text', 'start');
        pointLabel.setAttribute('font-size', '10px');
        pointLabel.setAttribute('fill', isMultiTurn ? '#fcd34d' : '#94a3b8');
        g.appendChild(pointLabel);

        // Tooltip
        const tooltipHtml = `
          <div class="tooltip-title">${escapeHtml(r.model.name)}</div>
          <div class="tooltip-row"><span>Series:</span> <span class="val">${escapeHtml(r.prompt_id)}</span></div>
          <div class="tooltip-row"><span>Turns &amp; Tools:</span> <span class="val">${numTurns} Turn${numTurns > 1 ? 's' : ''} · ${calls} calls</span></div>
          <div class="tooltip-row"><span>Total Context Re-Read:</span> <span class="val">${formatCompactNumber(totContext)}</span></div>
          <div class="tooltip-row"><span>Cached Context Read:</span> <span class="val">${formatCompactNumber(cacheRead)}</span></div>
          <div class="tooltip-row"><span>Uncached Input:</span> <span class="val">${formatCompactNumber(uncached)}</span></div>
          <div class="tooltip-row"><span>Cache Hit Rate:</span> <span class="val">${hitRate.toFixed(1)}%</span></div>
          <div class="tooltip-row"><span>Re-Read Amplification:</span> <span class="val">${ampRatio.toFixed(1)}x input/output</span></div>
        `;

        g.addEventListener('mouseenter', (ev) => showTooltip(ev, tooltipHtml));
        g.addEventListener('mousemove', moveTooltip);
        g.addEventListener('mouseleave', hideTooltip);
        g.addEventListener('click', () => openModal(r));

        svg.appendChild(g);
      });

      // Axis lines
      svg.appendChild(createSvgLine(pad.left, pad.top + innerH, pad.left + innerW, pad.top + innerH, 'axis-line'));
      svg.appendChild(createSvgLine(pad.left, pad.top, pad.left, pad.top + innerH, 'axis-line'));

      container.appendChild(svg);
    }
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
      const isPareto = Boolean(run.verification && run.verification.passed && run.pareto && run.pareto.is_pareto_series);
      card.className = `run-card ${isPareto ? 'pareto-border' : ''}`;

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
            ${isPareto ? '<span class="badge pareto">⚡ PARETO</span>' : ''}
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
          <div class="run-card-actions">
            ${
              run.demo_url
                ? `<a href="${escapeHtml(run.demo_url)}" target="_blank" rel="noopener noreferrer" class="btn-demo-action" title="Launch packaged live demo">🚀 Launch Demo</a>`
                : ''
            }
            <button class="btn-inspect" data-runid="${run.run_id}">Inspect Details</button>
          </div>
        </div>
      `;

      card.querySelector('.card-preview-area').addEventListener('click', () => openModal(run));
      card.querySelector('.btn-inspect').addEventListener('click', () => openModal(run));

      grid.appendChild(card);
    });
  }

  // ==========================================================================
  // PROMPT SHOWCASE & LIVE DEMOS VIEW
  // ==========================================================================

  function renderShowcase() {
    if (!benchmarkData || !benchmarkData.prompts || benchmarkData.prompts.length === 0) return;

    const promptSelect = document.getElementById('showcase-prompt-select');
    if (!promptSelect) return;

    // Populate prompts dropdown if not populated or out of sync
    if (promptSelect.options.length === 0) {
      benchmarkData.prompts.forEach((p) => {
        const opt = document.createElement('option');
        opt.value = p.prompt_id;
        opt.textContent = `${p.prompt_id} (${p.runs_count} runs)`;
        promptSelect.appendChild(opt);
      });

      promptSelect.addEventListener('change', (e) => {
        showcasePromptId = e.target.value;
        showcaseRunId = null; // reset selected run when changing prompt
        updateUrlParams();
        renderShowcase();
      });
    }

    // Determine current showcase prompt
    if (!showcasePromptId) {
      if (filters.series && filters.series !== 'all') {
        showcasePromptId = filters.series;
      } else {
        // Prefer prompt with demo_url runs if available
        const runWithDemo = benchmarkData.runs.find((r) => Boolean(r.demo_url));
        showcasePromptId = runWithDemo ? runWithDemo.prompt_id : benchmarkData.prompts[0].prompt_id;
      }
    }
    promptSelect.value = showcasePromptId;

    // Frozen prompt text
    const promptTextEl = document.getElementById('showcase-prompt-text');
    if (promptTextEl) {
      const promptInfo = benchmarkData.prompts.find((p) => p.prompt_id === showcasePromptId);
      const text = promptInfo && promptInfo.text ? promptInfo.text : '';
      promptTextEl.textContent = text || 'Prompt text unavailable.';
      const metaEl = document.getElementById('showcase-prompt-meta');
      if (metaEl) metaEl.textContent = `prompt/${showcasePromptId}.txt`;
    }

    // Runs for this prompt
    const promptRuns = benchmarkData.runs.filter((r) => r.prompt_id === showcasePromptId);
    const modelTabsContainer = document.getElementById('showcase-model-tabs');
    modelTabsContainer.innerHTML = '';

    if (promptRuns.length === 0) {
      document.getElementById('showcase-meta-bar').style.display = 'none';
      document.getElementById('showcase-open-fullscreen').style.display = 'none';
      document.getElementById('showcase-iframe').style.display = 'none';
      const fallback = document.getElementById('showcase-fallback');
      fallback.style.display = 'flex';
      document.getElementById('showcase-fallback-title').textContent = 'No runs found';
      document.getElementById('showcase-fallback-desc').textContent = `No runs recorded for prompt ${showcasePromptId}.`;
      document.getElementById('showcase-fallback-preview').style.display = 'none';
      return;
    }

    // Determine current showcase run
    if (!showcaseRunId || !promptRuns.some((r) => r.run_id === showcaseRunId)) {
      // Pick first run that has demo_url, else first run
      const firstWithDemo = promptRuns.find((r) => Boolean(r.demo_url));
      showcaseRunId = firstWithDemo ? firstWithDemo.run_id : promptRuns[0].run_id;
    }

    // Populate model tabs
    promptRuns.forEach((r) => {
      const btn = document.createElement('button');
      btn.className = `model-tab-btn ${r.run_id === showcaseRunId ? 'active' : ''}`;
      const hasDemoIcon = r.demo_url ? '🎮 ' : '';
      btn.innerHTML = `${hasDemoIcon}${escapeHtml(r.model.name)} <span style="font-size:0.7rem;opacity:0.75;">(${r.verification.passed ? '✓' : '✗'})</span>`;
      btn.addEventListener('click', () => {
        showcaseRunId = r.run_id;
        updateUrlParams();
        renderShowcase();
      });
      modelTabsContainer.appendChild(btn);
    });

    const activeRun = promptRuns.find((r) => r.run_id === showcaseRunId) || promptRuns[0];

    // Update Header Metadata Bar
    const metaBar = document.getElementById('showcase-meta-bar');
    metaBar.style.display = 'flex';

    const statusBadge = document.getElementById('showcase-badge-status');
    const isPass = activeRun.verification.passed;
    statusBadge.textContent = isPass ? '✓ PASSED' : '✗ FAILED';
    statusBadge.className = `badge ${isPass ? 'pass' : 'fail'}`;

    document.getElementById('showcase-model-name').textContent = activeRun.model.label || activeRun.model.name;
    document.getElementById('showcase-provider').textContent = activeRun.model.provider || 'cursor';

    const cost = activeRun.cost.estimated_with_harness_usd ?? activeRun.cost.estimated_usd ?? 0;
    const genTime = activeRun.model_time.generating_seconds ?? activeRun.wall_clock.seconds ?? 0;
    const score = activeRun.pareto.quality_score != null ? `${((activeRun.pareto.quality_score) * 100).toFixed(0)}%` : (isPass ? '100%' : '0%');
    const outTokens = activeRun.tokens.total_output ?? 0;

    document.getElementById('showcase-metric-cost').textContent = `$${cost.toFixed(2)}`;
    document.getElementById('showcase-metric-time').textContent = formatDurationSec(genTime);
    document.getElementById('showcase-metric-score').textContent = score;
    document.getElementById('showcase-metric-tokens').textContent = formatCompactNumber(outTokens);

    // Update Open full page button
    const openBtn = document.getElementById('showcase-open-fullscreen');
    const iframe = document.getElementById('showcase-iframe');
    const fallback = document.getElementById('showcase-fallback');
    const fallbackPreview = document.getElementById('showcase-fallback-preview');
    const fallbackImg = document.getElementById('showcase-fallback-img');

    if (activeRun.demo_url) {
      openBtn.href = activeRun.demo_url;
      openBtn.style.display = 'inline-flex';
      openBtn.target = '_blank';
      openBtn.rel = 'noopener noreferrer';

      // Load iframe if different
      if (iframe.getAttribute('src') !== activeRun.demo_url) {
        iframe.src = activeRun.demo_url;
      }
      iframe.style.display = 'block';
      fallback.style.display = 'none';
    } else {
      openBtn.style.display = 'none';
      iframe.src = 'about:blank';
      iframe.style.display = 'none';
      fallback.style.display = 'flex';

      document.getElementById('showcase-fallback-title').textContent = 'No Live Demo App Packaged';
      document.getElementById('showcase-fallback-desc').textContent = `Run ${activeRun.run_id} does not have a packaged interactive web demo yet. Package it using scripts/package_web_demos.py.`;

      if (activeRun.screenshot_path) {
        fallbackImg.src = activeRun.screenshot_path;
        fallbackPreview.style.display = 'block';
      } else {
        fallbackPreview.style.display = 'none';
      }
    }
  }

  // ==========================================================================
  // WAREHOUSE ANALYTICAL TABLES & DOWNLOADS VIEW
  // ==========================================================================

  const pricingState = { sort: 'output', scale: 'linear', providers: new Set() };

  function renderPricingTiersChart() {
    const grid = document.getElementById('chart-pricing-tiers');
    if (!grid) return;
    const pricing = (benchmarkData && benchmarkData.pricing) || { tiers: [], models: [] };
    const models = pricing.models || [];
    const filterBox = document.getElementById('pricing-provider-filters');
    const providers = Array.from(new Set(models.map((m) => m.provider))).sort();

    if (filterBox) {
      filterBox.innerHTML = '';
      providers.forEach((p) => {
        const b = document.createElement('button');
        b.className = 'pill-btn' + (pricingState.providers.has(p) ? ' active' : '');
        b.textContent = p;
        b.addEventListener('click', () => {
          if (pricingState.providers.has(p)) pricingState.providers.delete(p);
          else pricingState.providers.add(p);
          renderPricingTiersChart();
        });
        filterBox.appendChild(b);
      });
    }

    const visible = models.filter((m) => pricingState.providers.size === 0 || pricingState.providers.has(m.provider));
    const metrics = [
      { key: 'input', label: 'Input' },
      { key: 'output', label: 'Output' },
      { key: 'cache_read', label: 'Cache' },
    ];
    const maxVal = Math.max(1, ...visible.map((m) => Math.max(m.input || 0, m.output || 0, m.cache_read || 0)));
    const width = (v) => {
      if (!v || v <= 0) return 0;
      if (pricingState.scale === 'log') {
        const lo = Math.log10(0.01);
        return Math.max(2, ((Math.log10(Math.max(v, 0.01)) - lo) / (Math.log10(maxVal) - lo)) * 100);
      }
      return Math.max(2, (v / maxVal) * 100);
    };
    const fmt = (v) => (v == null ? 'n/a' : '$' + v.toFixed(2));

    grid.innerHTML = '';
    (pricing.tiers || []).forEach((tier) => {
      const inTier = visible
        .filter((m) => m.tier === tier.id)
        .sort((a, b) => (a[pricingState.sort] ?? 0) - (b[pricingState.sort] ?? 0) || a.name.localeCompare(b.name));
      const col = document.createElement('div');
      col.className = 'pricing-tier-col tier-' + tier.id;
      let html = `<div class="pricing-tier-head"><h4>${escapeHtml(tier.label)}</h4><span class="pricing-tier-count">${inTier.length} models</span></div>
        <p class="pricing-tier-desc">${escapeHtml(tier.description)}</p>`;
      if (inTier.length === 0) html += '<div class="pricing-empty">No models match the provider filter.</div>';
      inTier.forEach((m) => {
        html += `<div class="pricing-model" title="${escapeHtml(m.id)}: in ${fmt(m.input)} / out ${fmt(m.output)} / cache read ${fmt(m.cache_read)} per 1M">
          <div class="pricing-model-head"><span>${escapeHtml(m.name)}</span><span class="pricing-provider-badge">${escapeHtml(m.provider)}</span></div>
          ${metrics.map((x) => `<div class="pricing-bar-row"><span>${x.label}</span><span class="pricing-bar-track"><span class="pricing-bar-fill ${x.key}" style="display:block;width:${width(m[x.key]).toFixed(1)}%"></span></span><span class="pricing-bar-val">${fmt(m[x.key])}</span></div>`).join('')}
        </div>`;
      });
      col.innerHTML = html;
      grid.appendChild(col);
    });
  }

  function renderWarehouse() {
    const tbody = document.getElementById('warehouse-tables-tbody');
    if (!tbody) return;
    tbody.innerHTML = '';

    const wh = (benchmarkData && benchmarkData.warehouse) || {};
    const duckdbLink = document.getElementById('btn-download-duckdb');
    if (duckdbLink) {
      duckdbLink.href = wh.duckdb_path || 'warehouse/benchmark.duckdb';
    }

    const tables = wh.tables || [
      { name: 'fact_runs', type: 'fact', description: 'Core benchmark runs fact table with duration, tokens, cost, and verification status', row_count: benchmarkData?.runs?.length || 0, csv_path: 'warehouse/csv/fact_runs.csv', parquet_path: 'warehouse/parquet/fact_runs.parquet' },
      { name: 'fact_tool_calls', type: 'fact', description: 'Individual tool calls with bucket classification, latency, and failure flags', row_count: null, csv_path: 'warehouse/csv/fact_tool_calls.csv', parquet_path: 'warehouse/parquet/fact_tool_calls.parquet' },
      { name: 'fact_turns', type: 'fact', description: 'Turn-level telemetry capturing cache re-reads and prompt growth across conversational turns', row_count: null, csv_path: 'warehouse/csv/fact_turns.csv', parquet_path: 'warehouse/parquet/fact_turns.parquet' },
      { name: 'fact_thought_blocks', type: 'fact', description: 'Model reasoning and thinking block durations and token counts', row_count: null, csv_path: 'warehouse/csv/fact_thought_blocks.csv', parquet_path: 'warehouse/parquet/fact_thought_blocks.parquet' },
      { name: 'dim_models', type: 'dimension', description: 'Catalog of evaluated frontier LLM models, providers, and pricing rates', row_count: benchmarkData?.models?.length || 0, csv_path: 'warehouse/csv/dim_models.csv', parquet_path: 'warehouse/parquet/dim_models.parquet' },
      { name: 'dim_prompts', type: 'dimension', description: 'Frozen prompt definitions, verification probe criteria, and complexity types', row_count: benchmarkData?.prompts?.length || 0, csv_path: 'warehouse/csv/dim_prompts.csv', parquet_path: 'warehouse/parquet/dim_prompts.parquet' },
    ];

    tables.forEach((t) => {
      const tr = document.createElement('tr');
      const rowCountDisplay = t.row_count != null ? formatNumber(t.row_count) : 'Exported';
      const typeBadge = t.type === 'fact' ? '<span class="badge" style="background:#0284c7;color:#fff;">FACT</span>' : '<span class="badge" style="background:#64748b;color:#fff;">DIM</span>';
      const csvPath = t.csv_path || ('warehouse/csv/' + t.name + '.csv');

      tr.innerHTML = `
        <td><code style="font-weight:700;color:var(--accent-cyan);">${escapeHtml(t.name)}</code></td>
        <td>${typeBadge}</td>
        <td style="color:var(--text-muted);font-size:0.85rem;">${escapeHtml(t.description)}</td>
        <td style="font-family:var(--font-mono);font-weight:600;">${rowCountDisplay}</td>
        <td>
          <a href="${escapeHtml(csvPath)}" download="${escapeHtml(t.name)}.csv" class="btn-download-sm">
            <span>📄</span> CSV
          </a>
        </td>
      `;
      tbody.appendChild(tr);
    });
  }

  function setupModalDownloads(run) {
    const container = document.getElementById('modal-downloads-container');
    if (!container) return;
    container.innerHTML = '';

    const rp = run.results_paths || {
      run_json: `results/${run.prompt_id}/${run.run_id}/run.json`,
      runtime_json: `results/${run.prompt_id}/${run.run_id}/artifacts/runtime.json`,
      data_pipeline_json: `results/${run.prompt_id}/${run.run_id}/artifacts/data_pipeline.json`,
      verification_log: `results/${run.prompt_id}/${run.run_id}/verification.log`,
    };

    const artifacts = [
      {
        id: 'run-json',
        title: 'Run Record Metadata (run.json)',
        icon: '📋',
        desc: 'Canonical run manifest with token usage, pricing calculation, model config, and timing.',
        path: rp.run_json || `results/${run.prompt_id}/${run.run_id}/run.json`,
        filename: `${run.run_id}-run.json`,
      },
      {
        id: 'runtime-json',
        title: 'Runtime Playwright Diagnostics (runtime.json)',
        icon: '🎭',
        desc: 'Browser page load telemetry, HTTP status, console logs, errors, and DOM visual element counts.',
        path: rp.runtime_json || `results/${run.prompt_id}/${run.run_id}/artifacts/runtime.json`,
        filename: `${run.run_id}-runtime.json`,
      },
      {
        id: 'pipeline-json',
        title: 'Data Pipeline & Verification Probe Report (data_pipeline.json)',
        icon: '🔬',
        desc: 'Granular checks, record counts, file match criteria, and authenticity scoring.',
        path: rp.data_pipeline_json || `results/${run.prompt_id}/${run.run_id}/artifacts/data_pipeline.json`,
        filename: `${run.run_id}-data_pipeline.json`,
      },
      {
        id: 'verification-log',
        title: 'Verification Output Log (verification.log)',
        icon: '📜',
        desc: 'Full console execution trace and log output generated during automated verification.',
        path: rp.verification_log || `results/${run.prompt_id}/${run.run_id}/verification.log`,
        filename: `${run.run_id}-verification.log`,
      },
    ];

    artifacts.forEach((art) => {
      const card = document.createElement('div');
      card.className = 'download-artifact-card';
      card.innerHTML = `
        <div class="download-artifact-header">
          <span class="download-artifact-icon">${art.icon}</span>
          <div class="download-artifact-info">
            <h4>${escapeHtml(art.title)}</h4>
            <p>${escapeHtml(art.desc)}</p>
          </div>
        </div>
        <div class="download-artifact-actions">
          <a href="${escapeHtml(art.path)}" download="${escapeHtml(art.filename)}" class="btn-artifact-download">
            <span>⬇</span> Download
          </a>
          <a href="${escapeHtml(art.path)}" target="_blank" rel="noopener noreferrer" class="btn-artifact-view">
            <span>👁</span> View Raw
          </a>
        </div>
      `;
      container.appendChild(card);
    });
  }

  // ==========================================================================
  // DRILL-DOWN MODAL INSPECTOR
  // ==========================================================================

  function openModal(run, updateHistory = true) {
    currentModalRunId = run.run_id;
    const isPass = run.verification.passed;
    const statusBadge = document.getElementById('modal-status-badge');
    statusBadge.textContent = isPass ? '✓ PASSED (100%)' : '✗ FAILED';
    statusBadge.className = `badge ${isPass ? 'pass' : 'fail'}`;

    document.getElementById('modal-model-title').textContent = run.model.label || run.model.name;
    document.getElementById('modal-series-tag').textContent = `${run.prompt_id} / ${run.run_id}`;
    document.getElementById('modal-tool-count').textContent = run.tool_timeline ? run.tool_timeline.length : 0;

    const modalDemoBtn = document.getElementById('modal-launch-demo-btn');
    if (modalDemoBtn) {
      if (run.demo_url) {
        modalDemoBtn.href = run.demo_url;
        modalDemoBtn.style.display = 'inline-flex';
      } else {
        modalDemoBtn.style.display = 'none';
      }
    }

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

    const harnessName = (run.harness && run.harness.name ? run.harness.name : '').toLowerCase();
    const isFirstParty = run.model && (run.model.first_party_in_cursor || ['cursor', 'xai'].includes((run.model.provider || '').toLowerCase()));
    let surchargeRate = '0.00';
    if (cost.rates && cost.rates.harness_surcharge != null) {
      surchargeRate = String(cost.rates.harness_surcharge);
    } else if (cost.rates && cost.rates.harness_token_rate_per_1m != null) {
      surchargeRate = String(cost.rates.harness_token_rate_per_1m);
    } else if (harnessName === 'cursor' && !isFirstParty) {
      surchargeRate = '0.25';
    }
    const surchargeNum = parseFloat(surchargeRate);
    if (!isNaN(surchargeNum) && surchargeNum > 0) {
      document.getElementById('modal-cost-surcharge').textContent = `$${surchargeNum.toFixed(2)} / 1M tokens`;
    } else {
      document.getElementById('modal-cost-surcharge').textContent = '$0.00 (none)';
    }

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

    // Tab 5: Downloads & Raw Artifacts
    setupModalDownloads(run);

    // Reset active modal tab
    document.querySelectorAll('.modal-tab').forEach((t) => t.classList.remove('active'));
    document.querySelectorAll('.modal-tab-content').forEach((c) => c.classList.remove('active'));
    document.querySelector('.modal-tab[data-modaltab="verification"]').classList.add('active');
    document.getElementById('modal-tab-verification').classList.add('active');

    modal.style.display = 'flex';
    if (updateHistory !== false) {
      updateUrlParams();
    }
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

  function closeModal(updateHistory = true) {
    modal.style.display = 'none';
    currentModalRunId = null;
    if (updateHistory !== false) {
      updateUrlParams();
    }
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
