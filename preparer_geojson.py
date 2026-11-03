#!/usr/bin/env python3
"""Prépare les GeoJSON pour le web : reprojection Lambert-93 -> WGS84, simplification, allègement.
Entrée : sources/*.geojson  ->  Sortie : data/*.geojson
Prérequis : pip install pyproj shapely"""
import json
from pathlib import Path
from pyproj import Transformer
from shapely.geometry import shape, mapping
from shapely.ops import transform

TOL = {"communes_spclaci": 0.0003, "contour_france": 0.005, "contour_spclaci": 0.001}  # degrés
GARDER = ["NOM", "INSEE_COM", "INSEE_DEP", "POPULATION"]

def arrondi(c):
    return [round(c[0], 5), round(c[1], 5)] if isinstance(c[0], (int, float)) else [arrondi(x) for x in c]

Path("data").mkdir(exist_ok=True)
for nom, tol in TOL.items():
    src = json.load(open(f"sources/{nom}.geojson", encoding="utf-8"))
    crs = src.get("crs", {}).get("properties", {}).get("name", "")
    t = Transformer.from_crs("EPSG:2154" if "2154" in crs else "EPSG:4326", "EPSG:4326", always_xy=True)
    feats = []
    for f in src["features"]:
        g = transform(t.transform, shape(f["geometry"])).simplify(tol, preserve_topology=True)
        if g.is_empty:
            continue
        m = mapping(g)
        props = {k: f["properties"].get(k) for k in GARDER} if nom == "communes_spclaci" else {}
        feats.append({"type": "Feature", "properties": props,
                      "geometry": {"type": m["type"], "coordinates": arrondi(m["coordinates"])}})
    json.dump({"type": "FeatureCollection", "features": feats},
              open(f"data/{nom}.geojson", "w", encoding="utf-8"), separators=(",", ":"))
    print(nom, len(feats), "entités")