const map = L.map('map').setView([46.79886210, 7.70807010], 13);

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
    if (typeof props !== 'undefined')
        var name = props.NAME || props.statnaam
        const contents = props ? `<b>${name}</b><br />${props.EINWOHNERZ} people` : 'Hover over a municipality';
        this._div.innerHTML = `<h4>US Population Density</h4>${contents}`;
};

info.addTo(map);

for (let encoded of encodedRoutes) {
    var coordinates = L.Polyline.fromEncoded(encoded).getLatLngs();

    L.polyline(
        coordinates,
        {
            color: 'blue',
            weight: 2,
            opacity: 1,
            lineJoin: 'round'
        }
    ).addTo(map);
}


// get color depending on population density value
function getColor(d) {
    return d < 100 ? '#800026' :
           d < 10000  ? '#77db74' :
           d < 100000  ? '#74dbd4' :
                    '#FFEDA0';
}

function style(feature) {
    return {
        weight: 2,
        opacity: 1,
        color: 'white',
        dashArray: '3',
        fillOpacity: 0.7,
        fillColor: getColor(feature.properties.EINWOHNERZ)
    };
}

function highlightFeature(e) {
    const layer = e.target;

    layer.setStyle({
        weight: 5,
        color: '#666',
        dashArray: '',
        fillOpacity: 0.7
    });

    layer.bringToFront();

    info.update(layer.feature.properties);
}

/* global statesData */
const geojson = L.geoJson(municipalities, {
    style,
    onEachFeature
}).addTo(map);

function resetHighlight(e) {
    geojson.resetStyle(e.target);
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