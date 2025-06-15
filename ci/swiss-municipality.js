const axios = require("axios");
const fs = require("fs");
const path = require("path");
const prettyCompact = require("json-stringify-pretty-compact");
const shapefile = require("shapefile");
const shelljs = require("shelljs");
const swissgrid = require("swissgrid");
const turfBbox = require("@turf/bbox").default;
const turfMeta = require("@turf/meta");
const unzipper = require("unzipper");

const versions = [
  {
    version: "2025",
    encoding: "utf-8",
    layerRegExp: /.*/,
    url:
      "https://data.geo.admin.ch/ch.swisstopo.swissboundaries3d/swissboundaries3d_2025-04/swissboundaries3d_2025-04_2056_5728.shp.zip",
  }
];

const dataDir = path.resolve(__dirname, "data");

run();

async function run() {
  for (const { version, url, ...options } of versions) {
    const downloadDir = path.resolve(dataDir, "download");
    const file = await download(url, downloadDir);

    const shapefilesDir = path.resolve(dataDir, "shapefiles", version);
    await extract(file, shapefilesDir, options);

    const geojsonLv95Dir = path.resolve(
      dataDir,
      "geojson-lv95",
      version
    );
    await convert(shapefilesDir, geojsonLv95Dir, options);

    const geojsonDir = path.resolve(dataDir, "geojson", version);
    await reproject(geojsonLv95Dir, geojsonDir);
  }

}

async function download(url, targetDir) {
  shelljs.mkdir("-p", targetDir);

  const filename = path.basename(new URL(url).pathname);
  const targetFile = path.join(targetDir, filename);

  if (fs.existsSync(targetFile)) {
    console.log(`${filename} already exists`);
    return Promise.resolve(targetFile);
  }

  console.log(`${filename} is downloading...`);
  const response = await axios.get(url, { responseType: "stream" });
  const stream = response.data.pipe(fs.createWriteStream(targetFile));
  return new Promise((resolve) => {
    stream.on("finish", () => resolve(targetFile));
  });
}

async function extract(srcFile, targetDir, { archiveName, layerRegExp }) {
  shelljs.mkdir("-p", targetDir);

  const outerZipStream = fs.createReadStream(srcFile);
  const innerZipStream = archiveName
    ? outerZipStream.pipe(unzipper.ParseOne(archiveName))
    : outerZipStream;
  const contentStream = innerZipStream
    .pipe(unzipper.Parse())
    .on("entry", (entry) => {
      const filename = entry.path;
      if (layerRegExp.test(filename)) {
        const targetFile = path.join(targetDir, path.basename(filename));
        entry.pipe(fs.createWriteStream(targetFile));
      } else {
        entry.autodrain();
      }
    });

  return new Promise((resolve) => {
    contentStream.on("finish", () => resolve());
  });
}

async function convert(sourceDir, targetDir, { encoding }) {
  shelljs.mkdir("-p", targetDir);

  const shapefiles = shelljs.ls(path.resolve(sourceDir, "*.shp"));
  for (const filename of shapefiles) {
    const basename = path.basename(filename, ".shp");
    console.log(`Convert ${basename}`);

    const geojson = await shapefile.read(filename, undefined, { encoding });
    geojson.crs = {
      properties: {
        name: "urn:ogc:def:crs:EPSG::2056",
      },
      type: "name",
    };

    geojson.features
      .filter(({ properties: { BFS_NUMMER } }) => BFS_NUMMER === 261)
      .forEach(({ properties: { NAME } }) => {
        console.log("Name of Zurich:", NAME);
      });

    const targetFile = path.join(targetDir, `${basename}.geojson`);
    fs.writeFileSync(targetFile, prettyCompactGeojson(geojson, 5));
  }
}

function reproject(sourceDir, targetDir) {
  shelljs.mkdir("-p", targetDir);

  const lv95Files = shelljs.ls(path.resolve(sourceDir, "*.geojson"));
  for (const lv95File of lv95Files) {
    console.log("Reproject", path.basename(lv95File, ".geojson"));

    const geojson = JSON.parse(fs.readFileSync(lv95File));

    delete geojson.crs;
    turfMeta.coordEach(geojson, (coordinates) => {
      [coordinates[0], coordinates[1]] = swissgrid.unproject(coordinates);
    });

    const targetFile = path.join(targetDir, path.basename(lv95File));
    fs.writeFileSync(targetFile, prettyCompactGeojson(geojson, 7));
  }
}

function prettyCompactGeojson(geojson, precision) {
  const factor = 10 ** precision;
  const roundToPrecision = (coordinate) =>
    Math.round(coordinate * factor) / factor;

  turfMeta.coordEach(geojson, (coordinates) => {
    for (let i = 0; i < coordinates.length; i++) {
      coordinates[i] = roundToPrecision(coordinates[i]);
    }
  });

  if (geojson.bbox) {
    geojson.bbox = turfBbox(geojson);
  }

  return prettyCompact(geojson) + "\n";
}
