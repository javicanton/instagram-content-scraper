(function () {
  const params = new URLSearchParams(window.location.search);
  const graphFile = params.get("graph");
  const titleEl = document.getElementById("graph-title");
  const statsEl = document.getElementById("graph-stats");
  const container = document.getElementById("network");
  const physicsToggle = document.getElementById("physics-toggle");
  const fitBtn = document.getElementById("fit-btn");

  if (!graphFile) {
    titleEl.textContent = "Falta parámetro ?graph=";
    return;
  }

  let network = null;

  async function init() {
    const res = await fetch(graphFile);
    if (!res.ok) throw new Error(res.statusText);
    const data = await res.json();

    titleEl.textContent = data.title || "Grafo";
    statsEl.textContent = `${data.node_count} nodos · ${data.edge_count} aristas · ${data.source || ""}`;

    const nodes = new vis.DataSet(
      data.nodes.map((n) => ({
        id: n.id,
        label: n.label,
        group: n.group,
        color: n.color,
        size: n.size,
        title: n.title,
        font: { color: "#e8e8ef", size: 14 },
      }))
    );

    const edges = new vis.DataSet(
      data.edges.map((e, i) => ({
        id: i,
        from: e.from,
        to: e.to,
        value: e.value,
        title: e.title,
        color: { color: "#55556a", highlight: "#e1306c" },
      }))
    );

    const options = {
      nodes: {
        shape: "dot",
        borderWidth: 1,
        borderWidthSelected: 2,
      },
      edges: {
        smooth: { type: "continuous" },
        scaling: { min: 1, max: 8 },
      },
      physics: {
        enabled: true,
        barnesHut: {
          gravitationalConstant: -8000,
          springLength: 120,
          avoidOverlap: 0.2,
        },
        stabilization: { iterations: 150 },
      },
      interaction: {
        hover: true,
        tooltipDelay: 120,
        navigationButtons: true,
        keyboard: true,
      },
    };

    network = new vis.Network(container, { nodes, edges }, options);

    network.once("stabilizationIterationsDone", () => network.fit({ animation: true }));

    physicsToggle.addEventListener("change", () => {
      network.setOptions({ physics: { enabled: physicsToggle.checked } });
    });

    fitBtn.addEventListener("click", () => network.fit({ animation: true }));
  }

  init().catch((err) => {
    titleEl.textContent = "Error al cargar el grafo";
    statsEl.textContent = String(err);
    console.error(err);
  });
})();
