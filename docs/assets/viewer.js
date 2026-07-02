(function () {
  const params = new URLSearchParams(window.location.search);
  const graphFile = params.get("graph");
  const titleEl = document.getElementById("graph-title");
  const statsEl = document.getElementById("graph-stats");
  const hintEl = document.getElementById("filter-hint");
  const container = document.getElementById("network");
  const degreeSlider = document.getElementById("degree-slider");
  const degreeInput = document.getElementById("degree-input");
  const weightSlider = document.getElementById("weight-slider");
  const weightInput = document.getElementById("weight-input");
  const layoutSelect = document.getElementById("layout-select");
  const sizeSelect = document.getElementById("size-select");
  const labelsToggle = document.getElementById("labels-toggle");
  const physicsToggle = document.getElementById("physics-toggle");
  const relayoutBtn = document.getElementById("relayout-btn");
  const fitBtn = document.getElementById("fit-btn");
  const resetBtn = document.getElementById("reset-btn");
  const exportPngBtn = document.getElementById("export-png-btn");
  const legendList = document.getElementById("legend-list");
  const legendHint = document.getElementById("legend-hint");
  const legendShowAllBtn = document.getElementById("legend-show-all");
  const legendHideAllBtn = document.getElementById("legend-hide-all");

  if (!graphFile) {
    titleEl.textContent = "Falta parámetro ?graph=";
    return;
  }

  let network = null;
  let rawData = null;
  let nodesDs = null;
  let edgesDs = null;
  let positionsCache = {};
  let layoutStabilized = false;
  let defaults = {};
  let filterBounds = { maxDegree: 100, maxWeight: 10 };
  let hiddenCommunities = new Set();
  let communityCustomNames = {};
  let lastBaseVisibleIds = [];

  const NODE_FONT = {
    color: "#e8e8ef",
    strokeWidth: 0,
    face: "Segoe UI, system-ui, sans-serif",
    align: "center",
  };

  const LAYOUT_PHYSICS = {
    forceAtlas2Based: {
      solver: "forceAtlas2Based",
      forceAtlas2Based: {
        gravitationalConstant: -65,
        centralGravity: 0.008,
        springLength: 110,
        springConstant: 0.06,
        damping: 0.45,
        avoidOverlap: 0.6,
      },
      stabilization: { iterations: 250, updateInterval: 25, fit: true },
    },
    barnesHut: {
      solver: "barnesHut",
      barnesHut: {
        gravitationalConstant: -12000,
        centralGravity: 0.2,
        springLength: 95,
        springConstant: 0.04,
        damping: 0.12,
        avoidOverlap: 0.25,
      },
      stabilization: { iterations: 200, updateInterval: 25, fit: true },
    },
    repulsion: {
      solver: "repulsion",
      repulsion: {
        centralGravity: 0.15,
        springLength: 140,
        springConstant: 0.04,
        nodeDistance: 120,
        damping: 0.2,
      },
      stabilization: { iterations: 180, updateInterval: 25, fit: true },
    },
    hierarchicalRepulsion: {
      solver: "hierarchicalRepulsion",
      hierarchicalRepulsion: {
        centralGravity: 0.0,
        springLength: 120,
        springConstant: 0.01,
        nodeDistance: 140,
        damping: 0.09,
        avoidOverlap: 0.5,
      },
      stabilization: { iterations: 200, updateInterval: 25, fit: true },
    },
  };

  const SIZE_METRICS = {
    degree: "Grado",
    post_count: "Nº posts",
    uniform: "Uniforme",
  };

  function tooltip(label, postCount) {
    return `${label} · ${postCount} posts`;
  }

  function clamp(value, min, max) {
    return Math.min(max, Math.max(min, value));
  }

  function readMinDegree() {
    return clamp(
      Number(degreeInput.value || degreeSlider.value),
      Number(degreeSlider.min),
      Number(degreeSlider.max)
    );
  }

  function readMinWeight() {
    return clamp(
      Number(weightInput.value || weightSlider.value),
      Number(weightSlider.min),
      Number(weightSlider.max)
    );
  }

  function syncDegree(value) {
    const v = clamp(Math.round(value), Number(degreeSlider.min), Number(degreeSlider.max));
    degreeSlider.value = String(v);
    degreeInput.value = String(v);
    return v;
  }

  function syncWeight(value) {
    const v = clamp(Math.round(value), Number(weightSlider.min), Number(weightSlider.max));
    weightSlider.value = String(v);
    weightInput.value = String(v);
    return v;
  }

  function metricValue(node, metric) {
    if (metric === "uniform") return 1;
    return Number(node[metric] || 0);
  }

  function sizeScale(nodes, metric) {
    const values = nodes.map((n) => metricValue(n, metric));
    return { min: Math.min(...values), max: Math.max(...values) };
  }

  function computeNodeSize(node, metric, scale) {
    if (metric === "uniform") return 14;
    const value = metricValue(node, metric);
    const range = scale.max - scale.min || 1;
    const norm = (value - scale.min) / range;
    return 8 + norm * 28;
  }

  const NODE_SIZE_MIN = 8;
  const NODE_SIZE_MAX = 36;
  const LABEL_SIZE_MIN = 9;
  const LABEL_SIZE_MAX = 18;

  function labelFontSize(nodeSize) {
    const size = Number(nodeSize) || NODE_SIZE_MIN;
    const norm = (size - NODE_SIZE_MIN) / (NODE_SIZE_MAX - NODE_SIZE_MIN || 1);
    return Math.round(LABEL_SIZE_MIN + clamp(norm, 0, 1) * (LABEL_SIZE_MAX - LABEL_SIZE_MIN));
  }

  function labelFont(showLabels, nodeSize) {
    return { ...NODE_FONT, size: showLabels ? labelFontSize(nodeSize) : 0 };
  }

  function savePositions() {
    if (!network) return;
    positionsCache = { ...positionsCache, ...network.getPositions() };
    layoutStabilized = true;
  }

  function applyCachedPosition(node, nodeId) {
    const pos = positionsCache[nodeId];
    if (pos) {
      node.x = pos.x;
      node.y = pos.y;
    }
    return node;
  }

  function legendStorageKey() {
    return `ig-graph-legend:${graphFile}`;
  }

  function loadLegendPrefs() {
    try {
      const raw = localStorage.getItem(legendStorageKey());
      if (!raw) return;
      const data = JSON.parse(raw);
      if (data.names && typeof data.names === "object") {
        communityCustomNames = data.names;
      }
      if (Array.isArray(data.hidden)) {
        hiddenCommunities = new Set(data.hidden.map(String));
      }
    } catch (_) {
      communityCustomNames = {};
      hiddenCommunities = new Set();
    }
  }

  function saveLegendPrefs() {
    try {
      localStorage.setItem(
        legendStorageKey(),
        JSON.stringify({
          names: communityCustomNames,
          hidden: [...hiddenCommunities],
        })
      );
    } catch (_) {
      /* quota or private mode */
    }
  }

  function defaultCommunityLabel(cid) {
    const meta = communityLookup().get(String(cid));
    return (meta && meta.label) || `Comunidad ${cid}`;
  }

  function getCommunityLabel(cid) {
    const key = String(cid);
    return communityCustomNames[key] || defaultCommunityLabel(key);
  }

  function escapeHtml(text) {
    return String(text)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function computeBaseVisible(minDegree, minWeight) {
    const nodeById = new Map(rawData.nodes.map((n) => [n.id, n]));
    const keptNodes = new Set(
      rawData.nodes.filter((n) => n.degree >= minDegree).map((n) => n.id)
    );

    const keptEdges = rawData.edges.filter((e) => {
      if (e.value < minWeight) return false;
      return keptNodes.has(e.from) && keptNodes.has(e.to);
    });

    const connected = new Set();
    keptEdges.forEach((e) => {
      connected.add(e.from);
      connected.add(e.to);
    });

    const baseVisibleIds = [...keptNodes].filter(
      (id) => connected.has(id) || keptNodes.size <= 1
    );

    return { nodeById, keptEdges, baseVisibleIds };
  }

  function buildGraph(minDegree, minWeight, showLabels, sizeMetric) {
    const { nodeById, keptEdges, baseVisibleIds } = computeBaseVisible(minDegree, minWeight);
    lastBaseVisibleIds = baseVisibleIds;

    const afterCommunityFilter = baseVisibleIds.filter((id) => {
      const n = nodeById.get(id);
      return n && !hiddenCommunities.has(String(n.community_id));
    });

    const visibleSet = new Set(afterCommunityFilter);
    const filteredEdges = keptEdges.filter(
      (e) => visibleSet.has(e.from) && visibleSet.has(e.to)
    );

    const connected = new Set();
    filteredEdges.forEach((e) => {
      connected.add(e.from);
      connected.add(e.to);
    });

    const visibleIds = afterCommunityFilter.filter(
      (id) => connected.has(id) || afterCommunityFilter.length <= 1
    );

    const visibleRaw = visibleIds.map((id) => nodeById.get(id));
    const scale = sizeScale(visibleRaw, sizeMetric);

    const visNodes = visibleIds.map((id) => {
      const n = nodeById.get(id);
      const nodeSize = computeNodeSize(n, sizeMetric, scale);
      const node = applyCachedPosition(
        {
          id: n.id,
          label: showLabels ? n.label : "",
          group: n.community_id,
          color: {
            background: n.color,
            border: n.color,
            highlight: { background: n.color, border: "#ffffff" },
          },
          size: nodeSize,
          title: tooltip(n.label, n.post_count),
          font: labelFont(showLabels, nodeSize),
          fixed: false,
        },
        n.id
      );
      return node;
    });

    const visEdges = filteredEdges
      .filter((e) => visibleIds.includes(e.from) && visibleIds.includes(e.to))
      .map((e, i) => ({
        id: `e-${e.from}-${e.to}-${i}`,
        from: e.from,
        to: e.to,
        value: e.value,
        title: `${e.edge_type} (${e.value})`,
        color: { color: "rgba(120,120,150,0.35)", highlight: "#e1306c" },
      }));

    return {
      visNodes,
      visEdges,
      visibleIds,
      baseVisibleIds,
      visibleCount: visNodes.length,
      edgeCount: visEdges.length,
    };
  }

  function communityLookup() {
    const map = new Map();
    (rawData.communities || []).forEach((c) => map.set(String(c.id), c));
    return map;
  }

  function updateLegend(baseVisibleIds, visibleIds) {
    const baseCounts = new Map();
    const visibleCounts = new Map();
    const nodeById = new Map(rawData.nodes.map((n) => [n.id, n]));

    baseVisibleIds.forEach((id) => {
      const n = nodeById.get(id);
      if (!n) return;
      const cid = String(n.community_id);
      baseCounts.set(cid, (baseCounts.get(cid) || 0) + 1);
    });

    visibleIds.forEach((id) => {
      const n = nodeById.get(id);
      if (!n) return;
      const cid = String(n.community_id);
      visibleCounts.set(cid, (visibleCounts.get(cid) || 0) + 1);
    });

    const lookup = communityLookup();
    const items = [...baseCounts.entries()]
      .map(([cid, baseCount]) => {
        const meta = lookup.get(cid);
        const sample = [...nodeById.values()].find((n) => String(n.community_id) === cid);
        const hidden = hiddenCommunities.has(cid);
        const shown = visibleCounts.get(cid) || 0;
        return {
          id: cid,
          label: getCommunityLabel(cid),
          color: (meta && meta.color) || (sample && sample.color) || "#999",
          baseCount,
          shown,
          hidden,
        };
      })
      .sort((a, b) => b.baseCount - a.baseCount);

    legendList.innerHTML = items
      .map(
        (item) => `
      <li class="legend-item${item.hidden ? " legend-item--hidden" : ""}" data-community-id="${escapeHtml(item.id)}">
        <span class="legend-swatch" style="background:${item.color}"></span>
        <span class="legend-label" title="${escapeHtml(item.label)}">${escapeHtml(item.label)}</span>
        <span class="legend-count" title="${item.shown} visibles de ${item.baseCount}">${item.hidden ? item.baseCount : item.shown}</span>
      </li>`
      )
      .join("");

    const hiddenCount = items.filter((i) => i.hidden).length;
    if (items.length === 0) {
      legendHint.textContent = "Ninguna comunidad visible con estos filtros";
    } else if (hiddenCount === 0) {
      legendHint.textContent = `${items.length} comunidades · clic para ocultar · doble clic para renombrar`;
    } else {
      legendHint.textContent = `${items.length} comunidades · ${hiddenCount} oculta(s) · clic para alternar`;
    }
  }

  function toggleCommunity(cid) {
    const key = String(cid);
    if (hiddenCommunities.has(key)) {
      hiddenCommunities.delete(key);
    } else {
      hiddenCommunities.add(key);
    }
    saveLegendPrefs();
    applyFilters({ communitiesOnly: true });
  }

  function setAllCommunitiesVisible(visible) {
    const nodeById = new Map(rawData.nodes.map((n) => [n.id, n]));
    const ids = lastBaseVisibleIds
      .map((id) => nodeById.get(id))
      .filter(Boolean)
      .map((n) => String(n.community_id));

    const unique = [...new Set(ids)];
    if (visible) {
      unique.forEach((cid) => hiddenCommunities.delete(cid));
    } else {
      unique.forEach((cid) => hiddenCommunities.add(cid));
    }
    saveLegendPrefs();
    applyFilters({ communitiesOnly: true });
  }

  function startCommunityRename(item, cid) {
    if (item.dataset.editing === "1") return;
    item.dataset.editing = "1";

    const labelEl = item.querySelector(".legend-label");
    const input = document.createElement("input");
    input.type = "text";
    input.className = "legend-rename-input";
    input.value = getCommunityLabel(cid);
    input.setAttribute("aria-label", "Nombre de la comunidad");
    labelEl.replaceWith(input);
    input.focus();
    input.select();

    const previous = communityCustomNames[String(cid)];
    let cancelled = false;

    const finish = (save) => {
      if (item.dataset.editing !== "1") return;
      if (save) {
        const value = input.value.trim();
        if (value && value !== defaultCommunityLabel(cid)) {
          communityCustomNames[String(cid)] = value;
        } else {
          delete communityCustomNames[String(cid)];
        }
        saveLegendPrefs();
      } else if (previous === undefined) {
        delete communityCustomNames[String(cid)];
      } else {
        communityCustomNames[String(cid)] = previous;
      }
      item.dataset.editing = "0";
      applyFilters({ communitiesOnly: true });
    };

    input.addEventListener("blur", () => {
      if (!cancelled) finish(true);
    });
    input.addEventListener("keydown", (e) => {
      if (e.key === "Enter") {
        e.preventDefault();
        input.blur();
      }
      if (e.key === "Escape") {
        e.preventDefault();
        cancelled = true;
        finish(false);
      }
    });
  }

  function bindLegendEvents() {
    legendList.addEventListener("click", (e) => {
      const item = e.target.closest(".legend-item");
      if (!item || item.dataset.editing === "1") return;
      if (e.target.closest(".legend-rename-input")) return;
      toggleCommunity(item.dataset.communityId);
    });

    legendList.addEventListener("dblclick", (e) => {
      const item = e.target.closest(".legend-item");
      if (!item) return;
      e.preventDefault();
      startCommunityRename(item, item.dataset.communityId);
    });

    legendShowAllBtn.addEventListener("click", () => setAllCommunitiesVisible(true));
    legendHideAllBtn.addEventListener("click", () => setAllCommunitiesVisible(false));
  }

  function physicsOptions(enabled, solver) {
    const base = LAYOUT_PHYSICS[solver] || LAYOUT_PHYSICS.forceAtlas2Based;
    return { enabled, ...base };
  }

  function networkOptions() {
    return {
      nodes: {
        shape: "dot",
        borderWidth: 1,
        borderWidthSelected: 2,
        font: { ...NODE_FONT, size: LABEL_SIZE_MIN },
        scaling: {
          label: {
            enabled: false,
            drawThreshold: 0,
            maxVisible: 10000,
          },
        },
      },
      edges: { smooth: { type: "continuous" }, scaling: { min: 1, max: 10 } },
      physics: physicsOptions(physicsToggle.checked, layoutSelect.value),
      interaction: {
        hover: true,
        tooltipDelay: 80,
        navigationButtons: true,
        keyboard: { enabled: true, bindToWindow: false },
        zoomView: true,
        dragView: true,
        dragNodes: true,
        multiselect: false,
      },
    };
  }

  function stopPhysics() {
    if (!network) return;
    savePositions();
    network.stopSimulation();
    network.setOptions({ physics: { enabled: false } });
    physicsToggle.checked = false;
  }

  function bindStabilization(onDone) {
    network.off("stabilizationIterationsDone");
    network.once("stabilizationIterationsDone", () => {
      stopPhysics();
      if (onDone) onDone();
    });
  }

  function startLayout({ fit = false } = {}) {
    layoutStabilized = false;
    nodesDs.update(
      nodesDs.get().map((n) => ({
        id: n.id,
        fixed: false,
        x: undefined,
        y: undefined,
      }))
    );
    network.setOptions({ physics: physicsOptions(true, layoutSelect.value) });
    physicsToggle.checked = true;
    bindStabilization(() => {
      if (fit) network.fit({ animation: true });
    });
    network.startSimulation();
  }

  function syncNodesToDataset(visNodes) {
    const currentIds = new Set(nodesDs.getIds());
    const nextIds = new Set(visNodes.map((n) => n.id));

    const toRemove = [...currentIds].filter((id) => !nextIds.has(id));
    if (toRemove.length) nodesDs.remove(toRemove);

    const toAdd = visNodes.filter((n) => !currentIds.has(n.id));
    const toUpdate = visNodes.filter((n) => currentIds.has(n.id));

    if (toUpdate.length) nodesDs.update(toUpdate);
    if (toAdd.length) nodesDs.add(toAdd);
  }

  function updateGraphData(visNodes, visEdges, { relayout = false } = {}) {
    if (!network) {
      nodesDs = new vis.DataSet(visNodes);
      edgesDs = new vis.DataSet(visEdges);
      network = new vis.Network(container, { nodes: nodesDs, edges: edgesDs }, networkOptions());
      bindStabilization(() => network.fit({ animation: true }));
      network.startSimulation();
      return;
    }

    if (layoutStabilized) savePositions();

    syncNodesToDataset(visNodes);
    edgesDs.clear();
    edgesDs.add(visEdges);

    if (relayout || !layoutStabilized) {
      startLayout();
    } else {
      network.setOptions({ physics: { enabled: false } });
      network.stopSimulation();
    }
  }

  function patchVisibleNodes(patchFn) {
    if (!nodesDs) return;
    if (layoutStabilized) savePositions();
    nodesDs.update(
      nodesDs.get().map((n) => {
        const base = {
          id: n.id,
          fixed: false,
          x: positionsCache[n.id]?.x,
          y: positionsCache[n.id]?.y,
        };
        return { ...base, ...patchFn(n) };
      })
    );
    network.setOptions({ physics: { enabled: false } });
    network.stopSimulation();
  }

  function updateSizesOnly() {
    const metric = sizeSelect.value;
    const showLabels = labelsToggle.checked;
    const visibleRaw = nodesDs
      .get()
      .map((n) => rawData.nodes.find((x) => x.id === n.id))
      .filter(Boolean);
    const scale = sizeScale(visibleRaw, metric);
    patchVisibleNodes((n) => {
      const raw = rawData.nodes.find((x) => x.id === n.id);
      const nodeSize = computeNodeSize(raw, metric, scale);
      return {
        size: nodeSize,
        font: labelFont(showLabels, nodeSize),
      };
    });
  }

  function updateLabelsOnly() {
    const showLabels = labelsToggle.checked;
    patchVisibleNodes((n) => ({
      label: showLabels
        ? rawData.nodes.find((x) => x.id === n.id)?.label || ""
        : "",
      font: labelFont(showLabels, n.size),
    }));
  }

  function exportPng() {
    if (!network) return;
    const src = network.canvas.frame.canvas;
    const exportCanvas = document.createElement("canvas");
    exportCanvas.width = src.width;
    exportCanvas.height = src.height;
    const ctx = exportCanvas.getContext("2d");
    ctx.fillStyle = "#121218";
    ctx.fillRect(0, 0, exportCanvas.width, exportCanvas.height);
    ctx.drawImage(src, 0, 0);

    const corpus = rawData.corpus_id || "grafo";
    const metric = sizeSelect.value;
    const link = document.createElement("a");
    link.download = `${corpus}_hashtags_${metric}.png`;
    link.href = exportCanvas.toDataURL("image/png");
    link.click();
  }

  function applyFilters({
    fit = false,
    relayout = false,
    labelsOnly = false,
    sizesOnly = false,
    communitiesOnly = false,
  } = {}) {
    if (sizesOnly && network) {
      updateSizesOnly();
      return;
    }
    if (labelsOnly && network) {
      updateLabelsOnly();
      return;
    }

    const minDegree = syncDegree(readMinDegree());
    const minWeight = syncWeight(readMinWeight());
    const showLabels = labelsToggle.checked;
    const sizeMetric = sizeSelect.value;

    const { visNodes, visEdges, visibleIds, baseVisibleIds, visibleCount, edgeCount } =
      buildGraph(minDegree, minWeight, showLabels, sizeMetric);

    const hiddenNote =
      hiddenCommunities.size > 0 ? ` · ${hiddenCommunities.size} comunidad(es) oculta(s)` : "";

    statsEl.textContent = `${visibleCount} nodos · ${edgeCount} aristas · ${rawData.source || ""}`;
    hintEl.textContent =
      `Grado ≥ ${minDegree} · peso ≥ ${minWeight} · tamaño: ${SIZE_METRICS[sizeMetric] || sizeMetric} · ${layoutSelect.selectedOptions[0].text}${hiddenNote}`;
    updateLegend(baseVisibleIds, visibleIds);

    const hadNetwork = Boolean(network);
    const skipRelayout = communitiesOnly && hadNetwork && layoutStabilized;
    updateGraphData(visNodes, visEdges, { relayout: relayout && !skipRelayout });

    if (fit && hadNetwork && layoutStabilized) {
      network.fit({ animation: true });
    }
  }

  async function init() {
    const res = await fetch(graphFile);
    if (!res.ok) throw new Error(res.statusText);
    rawData = await res.json();
    loadLegendPrefs();

    titleEl.textContent = rawData.title || "Grafo";

    const filters = rawData.filters || {};
    defaults = rawData.defaults || {};
    const minDegreeDefault = defaults.min_degree ?? 1;
    filterBounds.maxDegree = filters.degree_max ?? 100;
    filterBounds.maxWeight = Math.max(filters.edge_weight_max ?? 10, 1);

    degreeSlider.min = "0";
    degreeSlider.max = String(filterBounds.maxDegree);
    degreeInput.min = "0";
    degreeInput.max = String(filterBounds.maxDegree);
    syncDegree(minDegreeDefault);

    weightSlider.min = "1";
    weightSlider.max = String(filterBounds.maxWeight);
    weightInput.min = "1";
    weightInput.max = String(filterBounds.maxWeight);
    syncWeight(defaults.min_edge_weight ?? 1);

    labelsToggle.checked = defaults.show_labels !== false;
    physicsToggle.checked = true;
    layoutSelect.value = defaults.layout || "forceAtlas2Based";
    sizeSelect.value = defaults.size_metric || "degree";

    bindLegendEvents();
    applyFilters({ fit: true, relayout: true });

    degreeSlider.addEventListener("input", () => {
      syncDegree(degreeSlider.value);
      applyFilters();
    });
    degreeInput.addEventListener("change", () => {
      syncDegree(degreeInput.value);
      applyFilters();
    });
    degreeInput.addEventListener("keydown", (e) => {
      if (e.key === "Enter") {
        syncDegree(degreeInput.value);
        applyFilters();
      }
    });

    weightSlider.addEventListener("input", () => {
      syncWeight(weightSlider.value);
      applyFilters();
    });
    weightInput.addEventListener("change", () => {
      syncWeight(weightInput.value);
      applyFilters();
    });
    weightInput.addEventListener("keydown", (e) => {
      if (e.key === "Enter") {
        syncWeight(weightInput.value);
        applyFilters();
      }
    });

    labelsToggle.addEventListener("change", () => applyFilters({ labelsOnly: true }));
    sizeSelect.addEventListener("change", () => applyFilters({ sizesOnly: true }));
    exportPngBtn.addEventListener("click", exportPng);

    physicsToggle.addEventListener("change", () => {
      if (physicsToggle.checked) {
        startLayout();
      } else {
        stopPhysics();
      }
    });

    layoutSelect.addEventListener("change", () => {
      layoutStabilized = false;
      positionsCache = {};
      applyFilters({ relayout: true, fit: true });
    });

    relayoutBtn.addEventListener("click", () => {
      layoutStabilized = false;
      positionsCache = {};
      applyFilters({ relayout: true, fit: true });
    });

    fitBtn.addEventListener("click", () => network && network.fit({ animation: true }));

    resetBtn.addEventListener("click", () => {
      syncDegree(defaults.min_degree ?? 1);
      syncWeight(defaults.min_edge_weight ?? 1);
      labelsToggle.checked = defaults.show_labels !== false;
      layoutSelect.value = defaults.layout || "forceAtlas2Based";
      sizeSelect.value = defaults.size_metric || "degree";
      hiddenCommunities = new Set();
      saveLegendPrefs();
      physicsToggle.checked = true;
      layoutStabilized = false;
      positionsCache = {};
      applyFilters({ fit: true, relayout: true });
    });
  }

  init().catch((err) => {
    titleEl.textContent = "Error al cargar el grafo";
    statsEl.textContent = String(err);
    console.error(err);
  });
})();
