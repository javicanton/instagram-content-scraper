(function () {
  const params = new URLSearchParams(window.location.search);
  const graphFile = params.get("graph");
  const titleEl = document.getElementById("graph-title");
  const statsEl = document.getElementById("graph-stats");
  const hintEl = document.getElementById("filter-hint");
  const container = document.getElementById("network");
  const degreeSlider = document.getElementById("degree-slider");
  const degreeValue = document.getElementById("degree-value");
  const weightSlider = document.getElementById("weight-slider");
  const weightValue = document.getElementById("weight-value");
  const labelsToggle = document.getElementById("labels-toggle");
  const physicsToggle = document.getElementById("physics-toggle");
  const fitBtn = document.getElementById("fit-btn");
  const resetBtn = document.getElementById("reset-btn");

  if (!graphFile) {
    titleEl.textContent = "Falta parámetro ?graph=";
    return;
  }

  let network = null;
  let rawData = null;
  let nodesDs = null;
  let edgesDs = null;

  function tooltip(label, postCount) {
    return `${label} · ${postCount} posts`;
  }

  function buildGraph(minDegree, minWeight, showLabels) {
    const nodeById = new Map(rawData.nodes.map((n) => [n.id, n]));
    const keptNodes = new Set(
      rawData.nodes
        .filter((n) => n.degree >= minDegree)
        .map((n) => n.id)
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

    const visibleNodes = [...keptNodes].filter((id) => connected.has(id) || keptNodes.size <= 1);

    const visNodes = visibleNodes.map((id) => {
      const n = nodeById.get(id);
      return {
        id: n.id,
        label: showLabels ? n.label : "",
        group: n.community_id,
        color: {
          background: n.color,
          border: n.color,
          highlight: { background: n.color, border: "#ffffff" },
        },
        size: n.size,
        title: tooltip(n.label, n.post_count),
        font: { color: "#e8e8ef", size: showLabels ? 13 : 0 },
      };
    });

    const visEdges = keptEdges
      .filter((e) => visibleNodes.includes(e.from) && visibleNodes.includes(e.to))
      .map((e, i) => ({
        id: i,
        from: e.from,
        to: e.to,
        value: e.value,
        title: `${e.edge_type} (${e.value})`,
        color: { color: "rgba(120,120,150,0.35)", highlight: "#e1306c" },
      }));

    return { visNodes, visEdges, visibleCount: visNodes.length, edgeCount: visEdges.length };
  }

  function applyFilters({ fit = false } = {}) {
    const minDegree = Number(degreeSlider.value);
    const minWeight = Number(weightSlider.value);
    const showLabels = labelsToggle.checked;

    degreeValue.textContent = String(minDegree);
    weightValue.textContent = String(minWeight);

    const { visNodes, visEdges, visibleCount, edgeCount } = buildGraph(
      minDegree,
      minWeight,
      showLabels
    );

    statsEl.textContent = `${visibleCount} nodos · ${edgeCount} aristas · ${rawData.source || ""}`;
    hintEl.textContent = `${rawData.community_count} comunidades (colores) · filtro grado ≥ ${minDegree}`;

    if (!network) {
      nodesDs = new vis.DataSet(visNodes);
      edgesDs = new vis.DataSet(visEdges);
      network = new vis.Network(
        container,
        { nodes: nodesDs, edges: edgesDs },
        {
          nodes: { shape: "dot", borderWidth: 1, borderWidthSelected: 2 },
          edges: { smooth: { type: "continuous" }, scaling: { min: 1, max: 10 } },
          physics: {
            enabled: physicsToggle.checked,
            barnesHut: {
              gravitationalConstant: -12000,
              springLength: 95,
              avoidOverlap: 0.25,
            },
            stabilization: { iterations: 200 },
          },
          interaction: {
            hover: true,
            tooltipDelay: 80,
            navigationButtons: true,
            keyboard: true,
          },
        }
      );
      network.once("stabilizationIterationsDone", () => {
        if (fit) network.fit({ animation: true });
      });
    } else {
      nodesDs.clear();
      edgesDs.clear();
      nodesDs.add(visNodes);
      edgesDs.add(visEdges);
      if (fit) network.fit({ animation: true });
    }
  }

  async function init() {
    const res = await fetch(graphFile);
    if (!res.ok) throw new Error(res.statusText);
    rawData = await res.json();

    titleEl.textContent = rawData.title || "Grafo";

    const filters = rawData.filters || {};
    const defaults = rawData.defaults || {};
    const minDegreeDefault = defaults.min_degree ?? 1;
    const maxDegree = filters.degree_max ?? 100;
    const maxWeight = Math.max(filters.edge_weight_max ?? 10, 1);

    degreeSlider.min = "0";
    degreeSlider.max = String(maxDegree);
    degreeSlider.value = String(minDegreeDefault);

    weightSlider.min = "1";
    weightSlider.max = String(maxWeight);
    weightSlider.value = String(defaults.min_edge_weight ?? 1);

    labelsToggle.checked = defaults.show_labels !== false;
    physicsToggle.checked = true;

    applyFilters({ fit: true });

    degreeSlider.addEventListener("input", () => applyFilters());
    weightSlider.addEventListener("input", () => applyFilters());
    labelsToggle.addEventListener("change", () => applyFilters());
    physicsToggle.addEventListener("change", () => {
      network.setOptions({ physics: { enabled: physicsToggle.checked } });
    });
    fitBtn.addEventListener("click", () => network.fit({ animation: true }));
    resetBtn.addEventListener("click", () => {
      degreeSlider.value = String(minDegreeDefault);
      weightSlider.value = String(defaults.min_edge_weight ?? 1);
      labelsToggle.checked = defaults.show_labels !== false;
      applyFilters({ fit: true });
    });
  }

  init().catch((err) => {
    titleEl.textContent = "Error al cargar el grafo";
    statsEl.textContent = String(err);
    console.error(err);
  });
})();
