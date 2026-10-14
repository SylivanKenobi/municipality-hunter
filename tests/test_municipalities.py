import json

from municipality_hunter import web
from municipality_hunter.municipalities import load_municipalities, swiss_municipalities


def swiss_feature(name, bfs, canton, icc="CH", objektart="Gemeindegebiet"):
    return {"type": "Feature", "properties": {
        "NAME": name, "BFS_NUMMER": bfs, "KANTONSNUM": canton, "ICC": icc,
        "OBJEKTART": objektart, "EINWOHNERZ": 100,
    }, "geometry": {"type": "Polygon", "coordinates": [[[8, 47], [8.01, 47], [8.01, 47.01], [8, 47]]]}}


def test_swiss_loader_skips_foreign_and_shared_areas(tmp_path):
    path = tmp_path / "ch.json"
    path.write_text(json.dumps({"type": "FeatureCollection", "features": [
        swiss_feature("Basel", 2701, 12),
        swiss_feature("Vaduz", 7001, None, icc="LI"),
        swiss_feature("Büsingen am Hochrhein", 7101, None, icc="DE"),
        swiss_feature("Liechtenstein", None, None, icc="LI", objektart="Kantonsgebiet"),
        swiss_feature("Kommunanz", None, None, objektart="Kommunanz"),
    ]}))

    municipalities = list(swiss_municipalities(path))

    assert [(m["name"], m["code"], m["canton"]) for m in municipalities] == [("Basel", "2701", "12")]


def test_api_returns_canton_names(conn, monkeypatch):
    def source():
        for name, bfs, canton in (("Basel", 2701, 12), ("Riehen", 2703, 12), ("Zürich", 261, 1)):
            feature = swiss_feature(name, bfs, canton)
            yield {"country": "CH", "code": str(bfs), "name": name, "canton": str(canton),
                   "population": 100, "geometry": feature["geometry"]}

    load_municipalities(conn, sources=(source,))
    features = web.app.test_client().get("/api/municipalities").get_json()["features"]

    assert sorted((f["properties"]["name"], f["properties"]["canton"]) for f in features) == [
        ("Basel", "Basel-Stadt"), ("Riehen", "Basel-Stadt"), ("Zürich", "Zürich"),
    ]


def test_canton_outline_is_merged_from_its_municipalities(conn):
    def source():
        # two neighbouring squares in Basel-Stadt, one in Zürich
        for name, bfs, canton, lon in (("Basel", 2701, 12, 8.0), ("Riehen", 2703, 12, 8.01), ("Zürich", 261, 1, 9.0)):
            yield {"country": "CH", "code": str(bfs), "name": name, "canton": str(canton), "population": 100,
                   "geometry": {"type": "Polygon", "coordinates": [[
                       [lon, 47], [lon + 0.01, 47], [lon + 0.01, 47.01], [lon, 47.01], [lon, 47]]]}}

    load_municipalities(conn, sources=(source,))
    features = web.app.test_client().get("/api/cantons").get_json()["features"]

    outlines = {f["properties"]["name"]: f["geometry"] for f in features}
    assert sorted(outlines) == ["Basel-Stadt", "Zürich"]
    # the shared border between Basel and Riehen is gone: one closed ring around both
    basel_stadt = outlines["Basel-Stadt"]
    rings = basel_stadt["coordinates"] if basel_stadt["type"] == "MultiLineString" else [basel_stadt["coordinates"]]
    assert len(rings) == 1
    lons = {round(lon, 5) for lon, lat in rings[0]}
    assert lons == {8.0, 8.02}
