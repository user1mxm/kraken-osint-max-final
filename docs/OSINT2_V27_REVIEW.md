# OSINT2 / KRAKEN v27 review — 2026-09-19

## Scope
Reviewed the user-supplied `Osint2.zip`, with emphasis on `run_v27_socmint_max.sh`, `app.js`, `catalog.json`, `gen_real_media.py`, `gen_thumbs.sh`, and the media viewer/API path.

## Main finding
The viewer is capable of rendering real local media, but the current asset generator manufactures placeholder images and then writes those generated images into both `thumbs/` and `original/`. Consequently, a catalog entry can look like a successful media acquisition even when no source media was acquired.

### Evidence in the supplied source
- `app.js::candidates()` tries poster/src/srcFull and only then a local SVG fallback.
- `gen_real_media.py::make_image()` creates a synthetic gradient card.
- `gen_real_media.py::main()` saves that generated card as both thumbnail and "original".
- Video entries may be mapped to sample MP4s rather than acquired source videos.
- `catalog.json` contains demo-style records and sample-media paths, so it must not be treated as provenance evidence.

## v27 collector issues
1. `BOLD` is referenced by the shell banner but not defined.
2. Package installation suppresses diagnostics, making dependency failures difficult to diagnose.
3. Instagram uses undocumented/private web response shapes and hard-coded query metadata; these are brittle.
4. Broad `except:` blocks suppress actionable errors.
5. Success messages can be emitted even when subprocesses return non-zero.
6. Media provenance, HTTP status, MIME type, magic-byte type, checksum, and acquisition timestamp are not stored consistently.
7. Filenames/extensions are trusted too early; observed supplied ".png" examples can contain JPEG bytes.
8. Static demo catalog and acquired evidence are mixed in one presentation layer.

## Corrected design
Use three states for every catalog item:
- `acquired`: local file exists and checksum/type were verified.
- `remote`: public/authorized source URL recorded but not downloaded.
- `placeholder`: UI-only fallback; never stored as an original.

Never synthesize a file under `original/` when acquisition failed. Generated thumbnails belong in `thumbs/` and carry `syntheticThumb: true`.

For acquired files record:
`sourceUrl`, `acquiredAt`, `sha256`, `mimeDetected`, `bytes`, `localPath`, and `provenanceStatus`.

## Repository hygiene
Before merging any collected material:
- keep credentials/cookies/session files out of Git;
- keep acquired personal/media evidence out of the source repository;
- add runtime output, vault media, cookies and secrets to `.gitignore`;
- only collect public information or data the operator is authorized to access.

## Recommended next implementation
1. Separate demo catalog from evidence catalog.
2. Replace `gen_real_media.py` with an importer that inventories existing local files rather than generating "originals".
3. Validate MIME using file signatures and compute SHA-256.
4. Make subprocess success conditional on return code.
5. Add structured JSONL acquisition logs.
6. Keep platform-specific collectors modular and testable.
