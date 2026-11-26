# Map and interface assets

The local map has no external tile, glyph, font, or telemetry requests. Flight data
comes from the local preview API and is not bundled in the frontend or this directory.

## Natural Earth geography

`public/map/*.geojson` contains deliberately selected, simplified geographic context
from [Natural Earth](https://www.naturalearthdata.com/about/terms-of-use/), public domain.
Downloaded on 2026-11-26 from the
[natural-earth-vector repository](https://github.com/nvkelso/natural-earth-vector/tree/master/geojson):

- `countries.geojson`: `ne_50m_admin_0_countries.geojson`, 15 regional countries;
  retained ISO code, name and label coordinates.
- `lakes.geojson`: `ne_50m_lakes.geojson`, Lake Balaton.
- `rivers.geojson`: `ne_50m_rivers_lake_centerlines.geojson`, four regional river features.
- `cities.geojson`: `ne_50m_populated_places.geojson`, four regional city points.

These low-resolution outlines provide visual context, not authoritative airspace,
navigation or procedure boundaries. The dashed rectangle is the recording scope.
The airport reference coordinates come from the existing Python airspace module.

## Typography and icons

Manrope Variable is self-hosted through the locked `@fontsource-variable/manrope`
dependency, under the SIL Open Font License. Its license ships in that npm package.
MapLibre GL JS is BSD-3-Clause licensed; dependencies retain their package licenses.
Interface icons, aircraft silhouette, brand mark and favicon are authored SVG code.
No stock or generated raster imagery is used.
