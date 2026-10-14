const map = L.map('map').setView([46.79886210, 7.70807010], 7);

L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
    maxZoom: 19,
    attribution: '&copy; <a href="http://www.openstreetmap.org/copyright">OpenStreetMap</a>'
}).addTo(map);

const COUNTRY_NAMES = { CH: 'Switzerland', NL: 'Netherlands' };
const COLORS = { unvisited: '#058dfc', visited: '#0511fc', cantonComplete: '#f2a900' };

let visits = {};
// canton name -> { visited, total }, for the selected activity types
let cantons = {};
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
    const canton = cantons[props.canton];
    if (canton) {
        lines.push(`Canton ${escapeHtml(props.canton)}: ${canton.visited} / ${canton.total}`
            + (isComplete(canton) ? ' – complete!' : ''));
    }
    this._div.innerHTML = `<h4>Municipality Hunter</h4>${lines.join('<br />')}`;
};

info.addTo(map);

function countVisited(features, key) {
    const totals = {};
    for (const feature of features) {
        const group = key(feature);
        if (!group) {
            continue;
        }
        totals[group] ??= { visited: 0, total: 0 };
        totals[group].total += 1;
        if (visits[feature.id]) {
            totals[group].visited += 1;
        }
    }
    return totals;
}

function isComplete(counts) {
    return counts.visited === counts.total;
}

// visited / total per country, and a list of the Swiss cantons
const stats = L.control({ position: 'bottomleft' });
let cantonListOpen = false;

stats.onAdd = function () {
    this._div = L.DomUtil.create('div', 'info stats');
    L.DomEvent.disableClickPropagation(this._div);
    L.DomEvent.disableScrollPropagation(this._div);
    this._div.addEventListener('toggle', e => { cantonListOpen = e.target.open; }, true);
    this._div.addEventListener('click', e => {
        const row = e.target.closest('[data-canton]');
        if (row) {
            zoomToCanton(row.dataset.canton);
        }
    });
    return this._div;
};
stats.update = function (features) {
    const countries = countVisited(features, f => f.properties.country);
    const lines = Object.entries(countries)
        .map(([country, t]) => `<b>${COUNTRY_NAMES[country] ?? country}</b>: ${t.visited} / ${t.total}`);

    // most visited share first
    const rows = Object.entries(cantons)
        .sort(([a, x], [b, y]) => y.visited / y.total - x.visited / x.total || a.localeCompare(b))
        .map(([name, t]) => `
            <tr data-canton="${escapeHtml(name)}" class="${isComplete(t) ? 'complete' : ''}">
                <td>${isComplete(t) ? '✓ ' : ''}${escapeHtml(name)}</td>
                <td class="count">${t.visited} / ${t.total}</td>
            </tr>`);
    const complete = Object.values(cantons).filter(isComplete).length;
    if (rows.length) {
        lines.push(`<details ${cantonListOpen ? 'open' : ''}>
            <summary>Cantons (${complete} / ${rows.length} complete)</summary>
            <div class="cantons"><table>${rows.join('')}</table></div>
        </details>`);
    }
    this._div.innerHTML = lines.join('<br />');
};

stats.addTo(map);

// Strava connection status / "Connect with Strava" button
const strava = L.control({ position: 'topleft' });

strava.onAdd = function () {
    this._div = L.DomUtil.create('div', 'info strava');
    L.DomEvent.disableClickPropagation(this._div);
    return this._div;
};
strava.update = function (status, error) {
    const button = label => `<a class="strava-connect" href="/auth/strava">${label}</a>`;
    const parts = [];
    if (error) {
        parts.push(`<div class="strava-error">${escapeHtml(error)}</div>`);
    }
    if (!status.configured) {
        parts.push('Set CLIENT_ID and CLIENT_SECRET in .env to connect Strava');
    } else if (status.connected) {
        const who = status.athlete ? ` as <b>${escapeHtml(status.athlete)}</b>` : '';
        parts.push(`Connected to Strava${who}<br /><a href="/auth/strava">Reconnect</a>`);
    } else {
        parts.push(button('Connect with Strava'));
    }
    this._div.innerHTML = parts.join('');
};

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

async function showStravaStatus() {
    const params = new URLSearchParams(window.location.search);
    const error = params.get('strava_error');
    // drop ?strava_error from the address bar so a reload doesn't show it again
    if (window.location.search) {
        history.replaceState(null, '', window.location.pathname);
    }
    strava.addTo(map);
    const status = await getJson('/api/strava');
    strava.update(status, error);
    return status;
}

// a completed canton gets its own color, otherwise visited / not visited
function getColor(feature) {
    const canton = cantons[feature.properties.canton];
    if (canton && isComplete(canton)) {
        return COLORS.cantonComplete;
    }
    return visits[feature.id] ? COLORS.visited : COLORS.unvisited;
}

function style(feature) {
    const canton = cantons[feature.properties.canton];
    return {
        weight: 1,
        opacity: 1,
        color: 'white',
        dashArray: '3',
        fillOpacity: canton && isComplete(canton) ? 0.5 : 0.3,
        fillColor: getColor(feature)
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

// canton outlines above the municipalities but below the routes;
// the pane ignores the mouse so hovering municipalities still works
map.createPane('cantons').style.zIndex = 450;
map.getPane('cantons').style.pointerEvents = 'none';
map.createPane('routes').style.zIndex = 460;

const cantonOutlines = L.geoJson(null, {
    pane: 'cantons',
    interactive: false,
    style: { color: '#333', weight: 2, opacity: 0.8, fill: false }
}).addTo(map);

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

function zoomToCanton(name) {
    const bounds = L.latLngBounds([]);
    municipalities.eachLayer(layer => {
        if (layer.feature.properties.canton === name) {
            bounds.extend(layer.getBounds());
        }
    });
    if (bounds.isValid()) {
        map.fitBounds(bounds);
    }
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
            pane: 'routes',
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
    cantons = countVisited(boundaryFeatures, f => f.properties.canton);
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

const [stravaStatus, types, boundaries, cantonBoundaries] = await Promise.all([
    showStravaStatus(),
    getJson('/api/activity-types'),
    getJson('/api/municipalities?v=2'),
    getJson('/api/cantons')
]);
if (stravaStatus.connected && types.length === 0) {
    strava.getContainer().insertAdjacentHTML('beforeend',
        '<br />Fetching your activities, reload in a minute');
}
addTypeFilter(types);
boundaryFeatures = boundaries.features;
municipalities.addData(boundaries);
cantonOutlines.addData(cantonBoundaries);
await refresh();
