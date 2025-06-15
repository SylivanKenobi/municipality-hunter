const map = L.map('map').setView([46.79886210, 7.70807010], 6);

const tiles = L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
    maxZoom: 19,
    attribution: '&copy; <a href="http://www.openstreetmap.org/copyright">OpenStreetMap</a>'
}).addTo(map);

// control that shows state info on hover
const info = L.control();

info.onAdd = function (map) {
    this._div = L.DomUtil.create('div', 'info');
    this.update();
    return this._div;
};
info.update = function (props) {
    const contents = props ? `<b>${props.NAME}</b><br />${props.EINWOHNERZ} people` : 'Hover over a municipality';
    this._div.innerHTML = `<h4>US Population Density</h4>${contents}`;
};

info.addTo(map);

for (let encoded of encodedRoutes) {
    var coordinates = L.Polyline.fromEncoded(encoded).getLatLngs();

    const polyline = L.polyline(
        coordinates,
        {
            color: 'red',
            weight: 2,
            opacity: 1,
            lineJoin: 'round'
        }
    ).addTo(map);
    polyline.bringToFront();
}

// get color depending on if the municipality has been visited
function getColor(d) {
    return d == 1 ? '#0511fc' :
           d == 0  ? '#058dfc' :
                    '#058dfc';
}

function style(feature) {
    return {
        weight: 1,
        opacity: 1,
        color: 'white',
        dashArray: '3',
        fillOpacity: 0.3,
        fillColor: getColor(feature.properties.visited)
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

    info.update(layer.feature.properties);
}

/* global statesData */
const geojson = L.geoJson(municipalities, {
    style,
    onEachFeature
}).addTo(map);

geojson.bringToBack();
function resetHighlight(e) {
    const layer = e.target;
    geojson.resetStyle(layer);
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