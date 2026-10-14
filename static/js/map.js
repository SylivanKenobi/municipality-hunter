const map = L.map('map').setView([46.79886210, 7.70807010], 7);

L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
    maxZoom: 19,
    attribution: '&copy; <a href="http://www.openstreetmap.org/copyright">OpenStreetMap</a>'
}).addTo(map);

const COUNTRY_NAMES = { CH: 'Switzerland', NL: 'Netherlands' };

let visits = {};
let boundaryFeatures = [];
let selectedTypes = [];

async function getJson(url) {
    const response = await fetch(url);
    if (!response.ok) {
        throw new Error(`${url}: ${response.status}`);
    }
    return response.json();
}

function typesQuery() {
    return `types=${encodeURIComponent(selectedTypes.join(','))}`;
}

// control that shows municipality info on hover
const info = L.control();

info.onAdd = function () {
    this._div = L.DomUtil.create('div', 'info');
    this.update();
    return this._div;
};
info.update = function (feature) {
    if (!feature) {
        this._div.innerHTML = '<h4>Municipality Hunter</h4>Hover over a municipality';
        return;
    }
    const props = feature.properties;
    const visit = visits[feature.id];
    const lines = [`<b>${props.name}</b> (${props.country})`];
    if (props.population) {
        lines.push(`${props.population.toLocaleString()} people`);
    }
    lines.push(visit
        ? `Visited ${visit.visits}×, first on ${visit.first_visit}`
        : 'Not visited yet');
    this._div.innerHTML = `<h4>Municipality Hunter</h4>${lines.join('<br />')}`;
};

info.addTo(map);

// visited / total per country
const stats = L.control({ position: 'bottomleft' });

stats.onAdd = function () {
    this._div = L.DomUtil.create('div', 'info');
    return this._div;
};
stats.update = function (features) {
    const totals = {};
    for (const feature of features) {
        const country = feature.properties.country;
        totals[country] ??= { visited: 0, total: 0 };
        totals[country].total += 1;
        if (visits[feature.id]) {
            totals[country].visited += 1;
        }
    }
    this._div.innerHTML = Object.entries(totals)
        .map(([country, t]) => `<b>${COUNTRY_NAMES[country] ?? country}</b>: ${t.visited} / ${t.total}`)
        .join('<br />');
};

stats.addTo(map);

// get color depending on if the municipality has been visited
function getColor(visited) {
    return visited ? '#0511fc' : '#058dfc';
}

function style(feature) {
    return {
        weight: 1,
        opacity: 1,
        color: 'white',
        dashArray: '3',
        fillOpacity: 0.3,
        fillColor: getColor(visits[feature.id])
    };
}

function highlightFeature(e) {
    const layer = e.target;

    layer.setStyle({
        weight: 5,
        color: '#666',
        dashArray: '1',
        fillOpacity: 0.3
    });

    layer.bringToBack();

    info.update(layer.feature);
}

const municipalities = L.geoJson(null, {
    style,
    onEachFeature
}).addTo(map);

function resetHighlight(e) {
    municipalities.resetStyle(e.target);
    info.update();
}

function zoomToFeature(e) {
    map.fitBounds(e.target.getBounds());
}

function onEachFeature(feature, layer) {
    layer.on({
        mouseover: highlightFeature,
        mouseout: resetHighlight,
        click: zoomToFeature
    });
}

const routes = L.layerGroup().addTo(map);

function drawRoutes(activities) {
    routes.clearLayers();
    for (const activity of activities) {
        L.Polyline.fromEncoded(activity.polyline, {
            color: 'red',
            weight: 2,
            opacity: 1,
            lineJoin: 'round',
            interactive: false
        }).addTo(routes);
    }
}

async function refresh() {
    const [newVisits, activities] = await Promise.all([
        getJson(`/api/visits?${typesQuery()}`),
        getJson(`/api/activities?${typesQuery()}`)
    ]);
    visits = newVisits;
    municipalities.setStyle(style);
    stats.update(boundaryFeatures);
    drawRoutes(activities);
}

// checkboxes to filter by activity type, outdoor rides selected by default
function isOutdoorRide(type) {
    return type.endsWith('Ride') && type !== 'VirtualRide';
}

function addTypeFilter(types) {
    selectedTypes = types.map(t => t.sport_type).filter(isOutdoorRide);
    if (selectedTypes.length === 0) {
        selectedTypes = types.map(t => t.sport_type);
    }

    const filter = L.control({ position: 'topright' });
    filter.onAdd = function () {
        const div = L.DomUtil.create('div', 'info types');
        div.innerHTML = '<h4>Activity types</h4>' + types.map(t => `
            <label>
                <input type="checkbox" value="${t.sport_type}" ${selectedTypes.includes(t.sport_type) ? 'checked' : ''}>
                ${t.sport_type} (${t.count})
            </label>`).join('');
        L.DomEvent.disableClickPropagation(div);
        div.addEventListener('change', () => {
            selectedTypes = [...div.querySelectorAll('input:checked')].map(input => input.value);
            refresh();
        });
        return div;
    };
    filter.addTo(map);
}

const [types, boundaries] = await Promise.all([
    getJson('/api/activity-types'),
    getJson('/api/municipalities')
]);
addTypeFilter(types);
boundaryFeatures = boundaries.features;
municipalities.addData(boundaries);
await refresh();
