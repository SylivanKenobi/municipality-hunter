#!/usr/bin/env bash
# Updates the municipality boundaries in assets/ when a newer release exists.
#
#   CH: swisstopo swissBOUNDARIES3D (latest release from the STAC API),
#       layer HOHEITSGEBIET, reprojected from LV95 to WGS84
#   NL: CBS gebiedsindelingen via PDOK WFS (latest year), gemeente_gegeneraliseerd
#
# The release in the repository is recorded in assets/municipality-sources.json.
# Requires curl, jq and ogr2ogr (gdal-bin). Use --force to regenerate anyway.
set -euo pipefail

ASSETS_DIR=${ASSETS_DIR:-"$(cd "$(dirname "$0")/.." && pwd)/assets"}
SOURCES="$ASSETS_DIR/municipality-sources.json"
FORCE=${1:-}

WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT

[ -f "$SOURCES" ] || echo '{}' > "$SOURCES"

current() { jq -r --arg k "$1" '.[$k] // ""' "$SOURCES"; }

record() {
  jq --arg k "$1" --arg v "$2" '.[$k] = $v' "$SOURCES" > "$WORK/sources.json"
  mv "$WORK/sources.json" "$SOURCES"
}

# Fails the run if a converted file looks broken, rather than opening a PR with it.
check_count() {
  local file=$1 filter=$2 min=$3 count
  count=$(jq "[.features[] | select($filter)] | length" "$file")
  echo "  $count municipalities"
  if [ "$count" -lt "$min" ]; then
    echo "  expected at least $min, aborting" >&2
    exit 1
  fi
}

update_ch() {
  local stac=https://data.geo.admin.ch/api/stac/v1/collections/ch.swisstopo.swissboundaries3d/items
  local item version url layer
  item=$(curl -fsS "$stac?limit=100" | jq -c '.features | max_by(.properties.datetime)')
  version=$(jq -r '.id' <<<"$item")
  echo "CH: latest $version, in repository: $(current ch)"
  if [ "$version" = "$(current ch)" ] && [ "$FORCE" != "--force" ]; then
    return
  fi

  url=$(jq -r '.assets[] | select(.type == "application/x.shapefile+zip") | .href' <<<"$item")
  curl -fsS -o "$WORK/ch.zip" "$url"
  layer=$(unzip -Z1 "$WORK/ch.zip" | grep -E 'HOHEITSGEBIET\.shp$')

  ogr2ogr -f GeoJSON "$WORK/ch.json" "/vsizip/$WORK/ch.zip/$layer" \
    -t_srs EPSG:4326 -dim XY -lco RFC7946=YES -lco COORDINATE_PRECISION=6
  check_count "$WORK/ch.json" '.properties.OBJEKTART == "Gemeindegebiet" and .properties.BFS_NUMMER and .properties.NAME' 2000

  mv "$WORK/ch.json" "$ASSETS_DIR/municipality-ch.json"
  record ch "$version"
}

update_nl() {
  local year version="" hits
  # newest yearly dataset that is published
  for year in $(( $(date +%Y) + 1 )) $(date +%Y) $(( $(date +%Y) - 1 )); do
    hits=$(curl -fsS "https://service.pdok.nl/cbs/gebiedsindelingen/$year/wfs/v1_0?request=GetFeature&service=WFS&version=2.0.0&typeName=gemeente_gegeneraliseerd&resultType=hits" 2>/dev/null \
      | grep -o 'numberMatched="[0-9]*"' | grep -o '[0-9]*' || true)
    if [ -n "$hits" ] && [ "$hits" -gt 0 ]; then
      version=$year
      break
    fi
  done
  if [ -z "$version" ]; then
    echo "NL: no dataset found on PDOK" >&2
    exit 1
  fi
  echo "NL: latest $version, in repository: $(current nl)"
  if [ "$version" = "$(current nl)" ] && [ "$FORCE" != "--force" ]; then
    return
  fi

  curl -fsS -o "$WORK/nl-raw.json" \
    "https://service.pdok.nl/cbs/gebiedsindelingen/$version/wfs/v1_0?request=GetFeature&service=WFS&version=2.0.0&typeName=gemeente_gegeneraliseerd&outputFormat=json&srsName=urn:ogc:def:crs:EPSG::4326&count=1000"
  # the loader expects the municipality name in NAME
  ogr2ogr -f GeoJSON "$WORK/nl.json" "$WORK/nl-raw.json" \
    -sql "SELECT statcode, jrstatcode, statnaam AS NAME FROM gemeente_gegeneraliseerd" \
    -nln municipalities -lco RFC7946=YES -lco COORDINATE_PRECISION=6
  check_count "$WORK/nl.json" '.properties.statcode and .properties.NAME' 300

  mv "$WORK/nl.json" "$ASSETS_DIR/municipality-nl.json"
  record nl "$version"
}

update_ch
update_nl
