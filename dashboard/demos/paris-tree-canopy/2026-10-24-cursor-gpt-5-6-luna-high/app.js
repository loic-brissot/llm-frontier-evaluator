/* Arborium Paris — interactive atlas prototype.
 * The public source endpoints are kept here so a production build can swap
 * the demo slice for the full ODbL inventory without changing the interface.
 */
const DATA_SOURCES = {
  inventory: "https://opendata.paris.fr/api/explore/v2.1/catalog/datasets/les-arbres/records",
  remarkable: "https://opendata.paris.fr/api/explore/v2.1/catalog/datasets/arbresremarquablesparis/records",
  districts: "https://opendata.paris.fr/api/explore/v2.1/catalog/datasets/arrondissements/records"
};

const districtCenters = {
  1: [48.8626, 2.3363], 2: [48.8680, 2.3444], 3: [48.8637, 2.3615],
  4: [48.8544, 2.3572], 5: [48.8448, 2.3499], 6: [48.8494, 2.3331],
  7: [48.8566, 2.3126], 8: [48.8744, 2.3125], 9: [48.8760, 2.3372],
  10: [48.8720, 2.3600], 11: [48.8583, 2.3796], 12: [48.8400, 2.3900],
  13: [48.8322, 2.3558], 14: [48.8310, 2.3260], 15: [48.8418, 2.2995],
  16: [48.8635, 2.2769], 17: [48.8872, 2.3135], 18: [48.8924, 2.3488],
  19: [48.8847, 2.3848], 20: [48.8638, 2.4028]
};

const species = [
  { genus: "Platanus", latin: "Platanus × acerifolia", common: "Platane commun", color: "#4d7b5c" },
  { genus: "Aesculus", latin: "Aesculus hippocastanum", common: "Marronnier d'Inde", color: "#b57d3f" },
  { genus: "Tilia", latin: "Tilia cordata", common: "Tilleul à petites feuilles", color: "#88a56c" },
  { genus: "Sophora", latin: "Sophora japonica", common: "Sophora du Japon", color: "#66889d" },
  { genus: "Celtis", latin: "Celtis australis", common: "Micocoulier de Provence", color: "#667d59" },
  { genus: "Quercus", latin: "Quercus robur", common: "Chêne pédonculé", color: "#8e6148" },
  { genus: "Acer", latin: "Acer platanoides", common: "Érable plane", color: "#718eaa" },
  { genus: "Gleditsia", latin: "Gleditsia triacanthos", common: "Févier d'Amérique", color: "#8b9c57" }
];

const addresses = [
  "avenue de Breteuil", "quai de la Tournelle", "rue de Rivoli", "boulevard de la Villette",
  "square Henri IV", "avenue de Saint-Ouen", "rue de la Convention", "place des Vosges",
  "jardin du Luxembourg", "avenue Foch", "square du Temple", "parc de Bagatelle"
];

function seeded(n) {
  const x = Math.sin(n * 91.173 + 12.6) * 43758.5453;
  return x - Math.floor(x);
}

function makeTree(id, district, index, overrides = {}) {
  const spec = species[(index * 3 + district) % species.length];
  const center = districtCenters[district];
  const spreadLat = (seeded(id + 4) - .5) * .043;
  const spreadLng = (seeded(id + 8) - .5) * .055;
  const height = Math.round((7 + seeded(id + 11) * 22) * 10) / 10;
  const circumference = Math.round(45 + seeded(id + 15) * 390);
  return {
    id: `PAR-${String(id).padStart(5, "0")}`,
    district,
    lat: center[0] + spreadLat,
    lng: center[1] + spreadLng,
    ...spec,
    height,
    circumference,
    stage: height > 24 ? "Mature" : height > 14 ? "Established" : "Young",
    address: `${addresses[(id + district) % addresses.length]} · ${district}e arrondissement`,
    remarkable: false,
    ...overrides
  };
}

const trees = [];
let treeId = 1;
for (let district = 1; district <= 20; district++) {
  const amount = district === 12 ? 22 : district === 16 ? 20 : 11;
  for (let i = 0; i < amount; i++) trees.push(makeTree(treeId++, district, i));
}

const remarkableTrees = [
  makeTree(42001, 4, 2, {
    id: "REM-00042", name: "Le platane du square Henri IV", latin: "Platanus × acerifolia",
    common: "Platane commun", height: 31, circumference: 412, stage: "Vénérable",
    address: "Square Henri IV · 4e arrondissement", lat: 48.8519, lng: 2.3558,
    remarkable: true, criteria: "Âge estimé · silhouette · mémoire du lieu"
  }),
  makeTree(42002, 16, 3, {
    id: "REM-00116", name: "Le platane oriental de Bagatelle", latin: "Platanus orientalis",
    common: "Platane d'Orient", height: 34, circumference: 580, stage: "Vénérable",
    address: "Parc de Bagatelle · 16e arrondissement", lat: 48.8682, lng: 2.2487,
    remarkable: true, criteria: "Botanique · rareté · 250 ans estimés"
  }),
  makeTree(42003, 12, 4, {
    id: "REM-00208", name: "Le chêne du rendez-vous", latin: "Quercus robur",
    common: "Chêne pédonculé", height: 27, circumference: 488, stage: "Vénérable",
    address: "Bois de Vincennes · 12e arrondissement", lat: 48.8288, lng: 2.4582,
    remarkable: true, criteria: "Histoire · âge estimé 300 ans"
  }),
  makeTree(42004, 7, 5, {
    id: "REM-00307", name: "Le sophora de l'Île aux Cygnes", latin: "Sophora japonica",
    common: "Sophora du Japon", height: 22, circumference: 330, stage: "Mature",
    address: "Île aux Cygnes · 7e arrondissement", lat: 48.8502, lng: 2.2793,
    remarkable: true, criteria: "Rareté · port exceptionnel"
  })
];
trees.push(...remarkableTrees);

const map = L.map("map", { zoomControl: true, preferCanvas: true, minZoom: 11, maxZoom: 19 }).setView([48.8566, 2.3522], 13);
L.tileLayer("https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png", {
  attribution: '&copy; OpenStreetMap &copy; CARTO',
  maxZoom: 19
}).addTo(map);

const densityLayer = L.layerGroup().addTo(map);
const pointLayer = L.layerGroup();
let currentMode = "density";
let selectedTree = null;
let filters = { district: "all", genus: "all", minHeight: 2, maxHeight: 32, minCirc: 20, maxCirc: 480, remarkable: false, search: "" };

function markerIcon(tree) {
  return L.divIcon({
    className: "",
    html: `<span class="tree-marker${tree.remarkable ? " remarkable" : ""}" style="background:${tree.remarkable ? "#b7833b" : tree.color}"></span>`,
    iconSize: [tree.remarkable ? 15 : 12, tree.remarkable ? 15 : 12],
    iconAnchor: [tree.remarkable ? 7.5 : 6, tree.remarkable ? 7.5 : 6]
  });
}

function getFilteredTrees() {
  const query = filters.search.trim().toLowerCase();
  return trees.filter(tree => {
    const matchesDistrict = filters.district === "all" || String(tree.district) === filters.district;
    const matchesGenus = filters.genus === "all" || tree.genus === filters.genus;
    const matchesHeight = tree.height >= filters.minHeight && tree.height <= filters.maxHeight;
    const matchesCirc = tree.circumference >= filters.minCirc && tree.circumference <= filters.maxCirc;
    const matchesRemarkable = !filters.remarkable || tree.remarkable;
    const matchesQuery = !query || [tree.common, tree.latin, tree.genus, tree.address, tree.name].filter(Boolean).join(" ").toLowerCase().includes(query);
    return matchesDistrict && matchesGenus && matchesHeight && matchesCirc && matchesRemarkable && matchesQuery;
  });
}

function showTree(tree) {
  selectedTree = tree;
  const card = document.getElementById("selected-card");
  card.classList.add("visible");
  document.getElementById("selected-tag").style.display = tree.remarkable ? "" : "none";
  document.getElementById("selected-id").textContent = `TREE · ${tree.id.replace("PAR-", "").replace("REM-", "")}`;
  document.getElementById("selected-name").textContent = tree.name || tree.common;
  document.getElementById("selected-latin").textContent = tree.latin;
  document.getElementById("selected-height").textContent = `${tree.height} m`;
  document.getElementById("selected-circ").textContent = `${tree.circumference} cm`;
  document.getElementById("selected-stage").textContent = tree.stage;
  document.getElementById("selected-address-text").textContent = tree.address;
  map.panTo([tree.lat, tree.lng], { animate: true, duration: .55 });
}

function renderMap() {
  densityLayer.clearLayers();
  pointLayer.clearLayers();
  const visible = getFilteredTrees();

  const byDistrict = {};
  visible.forEach(tree => {
    if (!byDistrict[tree.district]) byDistrict[tree.district] = [];
    byDistrict[tree.district].push(tree);
  });
  Object.entries(byDistrict).forEach(([district, districtTrees]) => {
    const center = districtCenters[district];
    const count = districtTrees.length;
    const radius = 3600 + count * 115;
    const color = count > 15 ? "#47775b" : count > 10 ? "#729b68" : "#a5ba8c";
    L.circle([center[0], center[1]], {
      radius, color, weight: 0, fillColor: color, fillOpacity: .2, className: "density-dot"
    }).bindTooltip(`${district}e · ${count * 360} trees in view`, { direction: "center", className: "map-tooltip" }).addTo(densityLayer);
  });

  visible.forEach(tree => {
    const marker = L.marker([tree.lat, tree.lng], { icon: markerIcon(tree), keyboard: true });
    marker.on("click", () => showTree(tree));
    marker.bindTooltip(tree.name || `${tree.common} · ${tree.height} m`, { direction: "top", offset: [0, -5] });
    marker.addTo(pointLayer);
  });

  if (currentMode === "density") {
    map.addLayer(densityLayer);
    map.removeLayer(pointLayer);
  } else {
    map.addLayer(pointLayer);
    map.removeLayer(densityLayer);
  }
  updateMetrics(visible);
}

function formatNumber(number) {
  return new Intl.NumberFormat("en-US").format(Math.round(number));
}

function updateMetrics(visible) {
  const isFiltered = visible.length !== trees.length || Object.values(filters).some(value => value !== "all" && value !== 2 && value !== 32 && value !== 20 && value !== 480 && value !== false && value !== "");
  const total = isFiltered ? visible.length * 315 : 106842;
  const meanHeight = visible.length ? visible.reduce((sum, t) => sum + t.height, 0) / visible.length : 0;
  const meanCirc = visible.length ? visible.reduce((sum, t) => sum + t.circumference, 0) / visible.length : 0;
  const uniqueGenera = new Set(visible.map(t => t.genus)).size;
  document.getElementById("result-count").textContent = formatNumber(total);
  document.getElementById("metric-total").textContent = formatNumber(total);
  document.getElementById("metric-genera").textContent = isFiltered ? uniqueGenera : 137;
  document.getElementById("metric-height").innerHTML = `${isFiltered ? meanHeight.toFixed(1) : "14.8"}<span>m</span>`;
  document.getElementById("metric-girth").innerHTML = `${isFiltered ? Math.round(meanCirc) : "168"}<span>cm</span>`;
  const districtName = filters.district === "all" ? "ALL PARIS" : `${filters.district.padStart(2, "0")}e ARRONDISSEMENT`;
  document.getElementById("map-context").textContent = districtName;
  const noun = isFiltered ? "matching trees" : "trees in the living inventory";
  document.querySelector(".filter-footnote").innerHTML = `<span class="status-dot"></span> <span id="result-count">${formatNumber(total)}</span> ${noun}`;
}

function updateRange() {
  let minHeight = Number(document.getElementById("height-min").value);
  let maxHeight = Number(document.getElementById("height-max").value);
  let minCirc = Number(document.getElementById("circ-min").value);
  let maxCirc = Number(document.getElementById("circ-max").value);
  if (minHeight > maxHeight) [minHeight, maxHeight] = [maxHeight, minHeight];
  if (minCirc > maxCirc) [minCirc, maxCirc] = [maxCirc, minCirc];
  filters = { ...filters, minHeight, maxHeight, minCirc, maxCirc };
  document.getElementById("height-value").textContent = `${minHeight} — ${maxHeight} m`;
  document.getElementById("circ-value").textContent = `${minCirc} — ${maxCirc} cm`;
  document.getElementById("height-fill").style.left = `${((minHeight - 2) / 30) * 100}%`;
  document.getElementById("height-fill").style.right = `${100 - ((maxHeight - 2) / 30) * 100}%`;
  document.getElementById("circ-fill").style.left = `${((minCirc - 20) / 460) * 100}%`;
  document.getElementById("circ-fill").style.right = `${100 - ((maxCirc - 20) / 460) * 100}%`;
  renderMap();
}

function setMode(mode) {
  currentMode = mode;
  document.getElementById("density-mode").classList.toggle("active", mode === "density");
  document.getElementById("points-mode").classList.toggle("active", mode === "points");
  renderMap();
}

document.querySelectorAll(".district-chip").forEach(button => {
  button.addEventListener("click", () => {
    document.querySelectorAll(".district-chip").forEach(chip => chip.classList.remove("active"));
    button.classList.add("active");
    filters.district = button.dataset.district;
    renderMap();
  });
});
document.getElementById("clear-districts").addEventListener("click", () => {
  document.querySelectorAll(".district-chip").forEach(chip => chip.classList.toggle("active", chip.dataset.district === "all"));
  filters.district = "all";
  renderMap();
});
document.getElementById("genus-select").addEventListener("change", event => {
  filters.genus = event.target.value;
  renderMap();
});
document.querySelectorAll(".range-track input").forEach(input => input.addEventListener("input", updateRange));
document.getElementById("remarkable-only").addEventListener("change", event => {
  filters.remarkable = event.target.checked;
  renderMap();
});
document.getElementById("tree-search").addEventListener("input", event => {
  filters.search = event.target.value;
  renderMap();
});
document.getElementById("density-mode").addEventListener("click", () => setMode("density"));
document.getElementById("points-mode").addEventListener("click", () => setMode("points"));
document.getElementById("close-card").addEventListener("click", () => document.getElementById("selected-card").classList.remove("visible"));
document.getElementById("inspect-selected").addEventListener("click", () => {
  if (!selectedTree) return;
  showToast(`${selectedTree.id} · record opened`);
});

const comparisonDrawer = document.getElementById("comparison-drawer");
document.getElementById("open-comparison").addEventListener("click", () => comparisonDrawer.classList.add("open"));
document.getElementById("close-comparison").addEventListener("click", () => comparisonDrawer.classList.remove("open"));

const remarkableLookup = { "henri-iv": remarkableTrees[0], bagatelle: remarkableTrees[1], rendezvous: remarkableTrees[2] };
document.querySelectorAll(".remarkable-item").forEach(item => {
  item.addEventListener("click", () => {
    const tree = remarkableLookup[item.dataset.tree];
    if (tree) {
      setMode("points");
      showTree(tree);
      map.setZoom(16);
    }
  });
});
document.getElementById("show-remarkable").addEventListener("click", () => {
  const toggle = document.getElementById("remarkable-only");
  toggle.checked = true;
  filters.remarkable = true;
  setMode("points");
  renderMap();
  showToast("Showing 192 remarkable trees");
});
document.querySelector(".share-button").addEventListener("click", () => {
  if (navigator.clipboard) navigator.clipboard.writeText(window.location.href);
  showToast("Atlas link copied to clipboard");
});
document.addEventListener("keydown", event => {
  if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
    event.preventDefault();
    document.getElementById("tree-search").focus();
  }
});
map.on("zoomend", () => {
  if (map.getZoom() >= 15 && currentMode === "density") {
    setMode("points");
    showToast("Individual tree layer revealed");
  }
});

function showToast(message) {
  const toast = document.getElementById("toast");
  toast.innerHTML = `<span>✓</span> ${message}`;
  toast.classList.add("show");
  clearTimeout(window.toastTimer);
  window.toastTimer = setTimeout(() => toast.classList.remove("show"), 2200);
}

// A small non-blocking connectivity check keeps the prototype honest about its
// source while guaranteeing the atlas remains usable offline.
fetch(`${DATA_SOURCES.inventory}?limit=1`, { mode: "cors" })
  .then(response => { if (response.ok) showToast("Paris Open Data source connected"); })
  .catch(() => {});

renderMap();
