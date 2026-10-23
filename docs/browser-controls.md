# Genome browser

BTED embeds JBrowse 4.3.0. **Open full browser** opens its standalone interface.

## Navigation and tracks

Use the coordinate box to select a contig or interval. **Tracks** opens the track list; **Import tracks** adds local or remote files against a matching reference. Indexed formats require their matching index. Local files stay in the browser and may need reselection after reload; remote files require accessible URLs and CORS support.

Click a feature for its attributes and sequence in the **Feature details** panel. **Share view** preserves the location, scale, orientation and registered public tracks. It warns when user-added tracks are omitted.

## Symbols and counts

| Display | Meaning |
|---|---|
| Solid flag | Experimental one-base 3′-end record |
| Bar with hollow flag | Prediction or augmentation interval; flag marks its strand-oriented 3′ boundary |
| Green / red | Positive / negative strand |
| Pale context band | Optional model-input sequence window |

Interval boundaries are displayed from the published GFF3, not resolved to a new single-base endpoint. Feature details retain the original coordinates and score. GFF3 coordinates are 1-based and inclusive.

Track-header counts cover the current contig and both strands, independent of zoom or display filters. Augmentation counts exclude sequence context windows. Missing counts are shown as unavailable, not zero. Multi-contig views do not show a single-contig total.

## BigWig signal

Positive and negative strands share a zero line and the same visible-window maximum within each track. The default scale is linear; **Signal scale** also offers `Log (1 + value)`. Panning and zooming recalculate the visible-window scale. Different conditions and windows scale independently, so their displayed peak heights are not directly comparable. Hover values and downloads retain the original BigWig values.

## Embedded controls

The embedded view retains navigation, track order, strand filters, reference direction and sequence controls. Application-level session/plugin management remains in the full browser. Menus omit unsupported displays, disabled actions and duplicate exports. User-added tracks retain their native controls. Mirrored signal tracks do not support SVG export.

The details and track-list panels use a same-origin React portal with isolated styles. Without an external host, JBrowse uses its native panel. **Reload** creates a fresh browser view while reusing valid cached data.

## Pinned JBrowse fixes

`install_bted_plugin` in `scripts/stage_site.py` patches the fixed 4.3.0 application during assembly. Patch matching fails if the expected code changes.

- The existing sequence-letter patch changes the zoom threshold and caps font size.
- Sequence type selection uses `hasExon`, rather than `hasExonOrCDS`, for exon/intron-specific modes. CDS-only annotations retain **CDS**, **Protein**, **Genomic** and flanking genomic-sequence modes.
- The sequence dialog memoizes its `SimpleFeature` input to avoid repeatedly restarting sequence requests on render. The 4.3.0 sidebar already contains this fix.

The last two changes follow RAPPTOR's `@jbrowse/core` 3.7.0 patch, adapted to the 4.3.0 application. Patched chunks and the runtime use versioned filenames to avoid old immutable browser caches. Coordinates and sequence extraction remain native JBrowse operations.

## Data caching

Fixed HF URLs use HTTP caching. Cache Storage additionally retains up to 128 successful Range slices of at most 512 KiB each (about 64 MiB), keyed by the full revisioned URL and Range. Errors, unversioned URLs, conditional requests and explicit `no-store` requests bypass this cache. Storage failure falls back to normal fetching.

Small registered computational files up to 512 KiB are checked against their registered size and checksum before the proxy serves them. Larger files stream upstream. Registered, version-matched backup URLs can handle upstream failures; arbitrary remote URLs are not accepted.
