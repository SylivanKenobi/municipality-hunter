#!/bin/bash

# Reduced version of the create_geojson_year.bash script from this repo here: https://github.com/cartomap/nl

set -e
JAAR="$1"
JAAR=${JAAR:=2025}

mkdir -p build/rd
mkdir -p build/wgs84
mkdir -p build/toc

REGIOTXT=build/toc/regios_$JAAR.txt
SHAPESTXT=build/toc/shapes_$JAAR.txt
POINTSTXT=build/toc/points_$JAAR.txt
WFS=https://service.pdok.nl/cbs/gebiedsindelingen/$JAAR/wfs/v1_0
TOC=build/toc/wfs_$JAAR.xml

# a list of gebiedsindelingen
test ! -f "$REGIOTXT" &&
  curl "$WFS?&request=GetCapabilities&service=WFS" > $TOC

grep "<Title>" $TOC | sed -e 's/.*<Title>\(.*\)<[/]Title>/\1/' | sort |uniq > $REGIOTXT

cat $REGIOTXT | grep  '_gegeneraliseerd' | grep -v '_niet_' - > $SHAPESTXT
cat $REGIOTXT | grep "point" - > $POINTSTXT

#PDOKNAMES=`head -n 1 $SHAPESTXT`
PDOKNAMES=`cat $SHAPESTXT`

for TYPENAME in $PDOKNAMES 
do
  REGION=${TYPENAME/cbs_/}
  REGION=${REGION%_*}_$JAAR

  JSON="build/wgs84/$REGION.json"
  GEOJSON="build/wgs84/$REGION.geojson"
  TOPOJSON="build/wgs84/$REGION.topojson"

 
  # pdok kapt de grootte van downloads op 1000 af
  SIZE=`curl "$WFS?request=GetFeature&service=WFS&version=2.0.0&typeName=${TYPENAME}&resultType=hits" \
      | grep numberMatch | sed 's/.*numberMatched="//' | sed 's/".*//'`

  STEPS=`seq 0 1000 $SIZE`
  PARTS=""
  # get WGS84 (EPSG:4326)
  for STARTINDEX in $STEPS
  do
    PART="build/wgs84/${REGION}_${STARTINDEX}.json"
    curl "$WFS?request=GetFeature&service=WFS&version=2.0.0&typeName=${TYPENAME}&outputFormat=json&srsName=urn:ogc:def:crs:EPSG::4326&STARTINDEX=$STARTINDEX" > $PART
    PARTS="$PARTS $PART"
  done
  echo "**** PARTS=$PARTS"
done

# remove all original files
rm -rf build/toc

if [ -z "$(ls -A ./build/wgs84)" ] 
then
  echo "Failed to build files..."
  exit 1
fi

sed -E 's/"statnaam": "([^"]+)"/"NAME": "\1"/g' build/wgs84/gemeente_2025_0.json > ../assets/municipality-nl.json