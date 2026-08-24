# Quant_chart — Project Reference

## What this project is
A desktop research tool for reading order flow on intraday futures. Five chart types are implemented:

1. **Footprint Chart** — enriched 1-minute candles with per-price buy/sell volume, resting (passive) liquidity, volume delta, anchored VWAPs, cumulative delta, large-trade bubbles, and several kinds of volume profile.
2. **OHLCV Chart** — plain candlestick chart with VWAP overlay and drawing tools. Simpler data requirements (standard OHLCV Parquet, no footprint columns needed).
3. **DOM Heatmap Chart** — order-book liquidity heatmap on 1-second MBO data: resting bid/ask depth drawn as a colored grid over time, a gray OHLC price overlay, and a right-edge per-price quantity ladder for the rightmost visible second.
4. **Options Exposure Chart** — dealer exposure by strike for options on futures: Black-76 Delta/Gamma/Vanna/Charm exposure bars (green/red) per strike, dashed line at the underlying futures price, and a time slider scrubbing the full Globex session in 5-min steps with ▶ autoplay.
5. **Interval Map** — the same exposure engine unrolled over the whole day: time on x, actual strikes on y (ordinal rows), each (time, strike) cell a dot with area ∝ |exposure| (green/red), and a blue underlying-price polyline overlaid.

All time-axis charts share the same drawing tools (horizontal lines, rays, vertical lines, boxes, long/short positions) and every chart shares the same coordinate system (`Viewport`); the options chart has no drawing tools (its x-axis is strikes, not time).

Single desktop process — no server, no web layer. Just Python, PyQt6, pandas/numpy, and Parquet files on disk.

## How to run
```
python main.py
```
**No hot reload.** After editing any file, fully restart `python main.py`.

Flow: `main.py` → `QApplication` + dark theme → `MenuWindow` → user picks chart type → dataset dialog → chart window

## Tech stack
- **Python + PyQt6** — UI and QPainter chart canvas
- **pandas / numpy** — data loading and in-memory models
- **Parquet** — on-disk candle / indicator / big-trade files
- **QSettings** — persists window/menu state and all visual settings (no config file to hand-edit)

---

## Folder structure

```
Quant_chart/
├─ main.py                        # app entry point
├─ core/                          # shared, chart-agnostic
│   ├─ asset_info.py              # tick sizes per instrument
│   ├─ data_paths.py              # folder / asset / dataset / date listing
│   ├─ annotations.py             # plugin overlay renderer (colored ts-anchored drawings)
│   ├─ drawing_anchors.py         # re-anchor drawings by timestamp across reloads
│   ├─ settings.py                # menu (home-screen) state
│   ├─ styles.py                  # app-wide dark theme
│   ├─ timeframes.py              # toolbar timeframe selector (class TimeframeSelector)
│   └─ viewport.py                # coordinate system + pan/zoom (class Viewport)
└─ views/
    ├─ menu/
    │   └─ menu.py                # home window, routes to charts
    ├─ footprint_chart/
    │   ├─ footprint_config.py    # resolved selection (class FootprintConfig)
    │   ├─ footprint_data.py      # candle / indicator / big-trade loaders + models
    │   ├─ open_dialog.py         # 'Open chart' pop-up
    │   ├─ volume_profile.py      # peak-based volume-profile algorithm
    │   ├─ footprint_settings.py  # persisted visual settings (dataclasses)
    │   ├─ settings_dialog.py     # the settings window
    │   ├─ canvas.py              # QPainter chart widget
    │   └─ window.py              # toolbar + canvas container
    ├─ ohlcv_chart/
    │   ├─ ohlcv_config.py        # resolved selection (class OhlcvConfig)
    │   ├─ ohlcv_data.py          # OHLCV loader + OhlcvData model
    │   ├─ ohlcv_settings.py      # persisted visual settings (OhlcvGeneralSettings)
    │   ├─ open_dialog.py         # 'Open chart' pop-up (dataset keyword: "ohlcv")
    │   ├─ settings_dialog.py     # settings window (General: RTH start/end only)
    │   ├─ canvas.py              # QPainter chart widget (OhlcvCanvas)
    │   └─ window.py              # toolbar + canvas container (OhlcvWindow)
    ├─ heatmap_chart/
    │   ├─ heatmap_config.py      # resolved selection (class HeatmapConfig)
    │   ├─ heatmap_data.py        # MBO loader + HeatmapData model (lazy book parse)
    │   ├─ heatmap_settings.py    # persisted visual settings (HeatmapSettings)
    │   ├─ open_dialog.py         # 'Open chart' pop-up (dataset keyword: "mbo")
    │   ├─ settings_dialog.py     # settings window (Heatmap: contrast etc.)
    │   ├─ canvas.py              # QPainter/numpy heatmap widget (HeatmapCanvas)
    │   └─ window.py              # toolbar + canvas container (HeatmapWindow)
    ├─ options_chart/
    │   ├─ options_config.py      # resolved selection (class OptionsConfig)
    │   ├─ black76.py             # pure-numpy Black-76 greeks + vectorized IV solver
    │   ├─ options_data.py        # 5m options loader + OptionsDay model (ffilled grids)
    │   ├─ options_compute.py     # per-time exposure computation (StrikeExposure)
    │   ├─ options_settings.py    # persisted settings (OptionsSettings)
    │   ├─ settings_dialog.py     # settings window (rate, lookback, playback, dim)
    │   ├─ open_dialog.py         # 'Open chart' pop-up (keywords: "5m" + futures "ohlcv")
    │   ├─ canvas.py              # QPainter bar-chart widget (OptionsCanvas)
    │   └─ window.py              # toolbar + canvas + time-slider bar (OptionsWindow)
    ├─ interval_map/
    │   ├─ interval_compute.py    # day-grid builder (IntervalGrid; reuses options_compute)
    │   ├─ canvas.py              # QPainter dot-grid widget (IntervalMapCanvas)
    │   └─ window.py              # toolbar + canvas (IntervalMapWindow; reuses options config/dialogs)
    └─ trade_replay/
        ├─ trades_data.py         # trades parquet loader + TradeSet model
        ├─ filter_expr.py         # per-column filter mini-language (>5, 3..8, 1,4)
        ├─ widgets.py             # CheckableComboBox, FilterHeader, StatCard, sparkline
        ├─ trades_table.py        # table model + mask-based filter/sort proxy
        ├─ helpers.py             # plugin API (ChartHandle/PluginContext) + loader
        ├─ plugins/               # user plugin scripts (hot-reloaded per run)
        └─ window.py              # TradeReplayWindow (nav, detail, table, load-to-charts)
```

**Organising rule:** `core/` = shared by any chart or feature. `views/<feature>/` = used only by that feature. New chart types slot in as siblings of `footprint_chart/`, `ohlcv_chart/`, and `heatmap_chart/`, reusing everything in `core/`.

---

## Data flow

### Footprint chart
```
MenuWindow → OpenChartDialog → FootprintConfig → FootprintWindow
                                                      ├─ load_candles()      → ChartData
                                                      ├─ load_indicators()   → IndicatorData
                                                      └─ load_big_trades()   → BigTradeData
                                                                ↓
                                                         FootprintCanvas
                                                      (owns Viewport, reads settings)
```

### OHLCV chart
```
MenuWindow → OhlcvOpenDialog → OhlcvConfig → OhlcvWindow
                                                 ├─ load_ohlcv()            → OhlcvData
                                                 └─ load_ohlcv_indicators() → IndicatorData
                                                           ↓
                                                      OhlcvCanvas
                                                 (owns Viewport, reads OhlcvGeneralSettings)
```

### DOM heatmap chart
```
MenuWindow → HeatmapOpenDialog → HeatmapConfig → HeatmapWindow
                                                     └─ load_heatmap()         → HeatmapData
                                                               ↓
                                                          HeatmapCanvas
                                                  (owns Viewport, reads HeatmapSettings)
```

### Options exposure chart
```
MenuWindow → OptionsOpenDialog → OptionsConfig → OptionsWindow
                                                     └─ load_options_day()      → OptionsDay
                                                               ↓
                                              compute_exposure(day, t, params)  → StrikeExposure
                                                               ↓  (per slider move)
                                                         OptionsCanvas
                                                 (owns Viewport, reads OptionsSettings)
```

### Interval map
```
MenuWindow → OptionsOpenDialog → OptionsConfig → IntervalMapWindow
                                                     └─ load_options_day()      → OptionsDay
                                                               ↓
                                     build_interval_grid(day, params, interval, step) → IntervalGrid
                                                               ↓  (per param change)
                                                       IntervalMapCanvas
                                                (owns Viewport, reads OptionsSettings)
```

**Key principle: data flows one way.** Loaders turn a config into immutable in-memory models. The canvas only reads those models + settings objects + viewport. Nothing downstream writes back to Parquet files. Never mutate loaded data in place.

---

## File-by-file reference

### core/asset_info.py
Static lookup of contract tick sizes. Single source of truth for price granularity.
- `tick_size_for(asset, default=0.25)` → `float`
- `TICK_SIZES` → `dict[str, float]`

### core/data_paths.py
Filesystem discovery for cascading selectors. All functions are fail-soft (missing folder → empty list, not exception).
- `list_type_folders(root)` → `list[str]`
- `list_assets(root, type_folder)` → `list[str]`
- `list_datasets(root, type_folder, asset)` → `list[str]`
- `list_dates(root, type_folder, asset, dataset)` → `list[str]`

### core/settings.py
Thin QSettings wrapper for home screen remembered state (data root, asset, date, time filters). Survives restarts. Visual chart settings live in chart-specific settings files.
- `AppSettings().get(key, default, type_)` → stored value, typed
- `AppSettings().set(key, value)` → `None`
- `Keys` — constants for setting keys (ROOT, ASSET, DATE, TIME_START, REPLAY_DIR, REPLAY_FILE, …)

### core/drawing_anchors.py
Keeps index-anchored drawings (v-lines, rays, boxes, positions) glued to their *timestamps* across any chart reload (timeframe change, date change). Windows call `capture_anchors(canvas)` before reloading and `restore_anchors(canvas, snapshot)` after; dicts are mutated **in place** so object identity survives (the trade-replay module tracks its auto-drawn position by identity). Each restore stashes `(_anchors: {field: (ts, idx)})` inside the drawing dicts so a drawing clamped off-range by a date jump snaps back to its true spot on return; a user drag invalidates the stash (index wins).
- `times_ns_of(data)` → epoch-ns array for any chart data model (uses `.times_ns` if present)
- `capture_anchors(canvas)` → snapshot | None (no data)
- `restore_anchors(canvas, snapshot)` → None

### core/timeframes.py
The toolbar timeframe selector shared by footprint + OHLCV windows: a value combo (1/4/5/15/30 + "Custom…" → integer prompt) and a unit combo (m/h/d/w/mo/y → `"Minutes"`…`"Years"`).
- `class TimeframeSelector(config, on_change)` — exposes `.value_combo` / `.unit_combo`; calls `on_change(value, unit)` on user picks only

### core/viewport.py
Coordinate system shared by every chart. Holds visible price window + pan/zoom state, converts between data space (candle index, price) and screen space (pixels). Renderers mutate and read this one object so the whole chart stays consistent.
- State: `offset_x`, `candle_w`, `center_price`, `scale_y`, `price_min/max`, screen rect `left/top/right/bottom`
- `price_to_y(price)` / `y_to_price(y)` → `float`
- `candle_x(i)` / `x_to_candle_round(x)` / `x_to_candle_floor(x)`
- `tick_px(tick)` / `pixels_per_price()` / `price_span()` → `float`
- `GAP_RATIO` = 0.025 (gap between candle slots as fraction of candle width)

### views/menu/menu.py
Home window. Cascading selectors for data root / type / asset / dataset / date + time filters. Launches the appropriate open dialog, then the chart window.
- **Footprint Chart** button → `OpenChartDialog` → `FootprintWindow`
- **Simple Chart** button → `OhlcvOpenDialog` → `OhlcvWindow`
- **DOM Heatmap** button → `HeatmapOpenDialog` → `HeatmapWindow`
- **Dealer Exposure** button → `OptionsOpenDialog` → `OptionsWindow`
- **Interval Map** button → `OptionsOpenDialog` (title kwarg) → `IntervalMapWindow`
- **Live Date Control** section: ◄/► step the anchor date ±1 day (calendar for jumps); **"Load date to all open charts"** (`_load_date_to_charts`) calls `window.set_date(date)` on every live (`isVisible()`) open chart, reloading each for that date **keeping its own days-back** (so a far jump still loads `days_back` days, not the gap). Charts with no data for that day show empty without erroring.
- **Trade Replay** button → `TradeReplayWindow(menu=self)` (appended to `open_windows`; it has no `set_date`, so `_live_windows()` keeps it out of date pushes)
- `class MenuWindow` — the home QMainWindow shown first by `main.py`; tracks open charts in `self.open_windows`

### main.py
Entry point. Creates `QApplication`, applies dark stylesheet, shows `MenuWindow`, runs event loop.

---

## Footprint chart — file reference

### views/footprint_chart/footprint_config.py
Plain dataclass — the resolved menu selection handed to a footprint chart window. No behaviour beyond path helpers.
- `class FootprintConfig`: fields: `root`, `type_folder`, `asset`, `dataset`, `date`, `days_back`, `time_start`, `time_end`, `tf_value`, `tf_unit`, `indicators_dataset`, `big_trades_dataset`
- `dataset_path()` / `indicators_path()` / `big_trades_path()` → `str | None`
- `has_dataset()` / `has_indicators()` / `has_big_trades()` → `bool`
- `timeframe_str()` → `str` (e.g. `'5 Minutes'`)

### views/footprint_chart/footprint_data.py
All disk → memory loading. Reads daily Parquet files, stitches the requested day-span chronologically, applies time-of-day filter and resamples to chart timeframe. Defines the enriched candle schema.
- `load_candles(config)` → `ChartData | None`
- `load_indicators(config, candle_times)` → `IndicatorData | None`
- `load_big_trades(config, days_back)` → `BigTradeData | None`
- `load_composite_volume(config, days_back, end_time)` → `(levels: dict{price→total_volume}, days_loaded: int)`
- `select_day_files(folder, date, days_back)` → `list[Path]`
- `resample_dataframe(df, tf_value, tf_unit)` → `DataFrame` — requires `buy_volume`/`sell_volume` columns; **not suitable for plain OHLCV data** (use `ohlcv_data._resample_ohlcv` instead)
- `_bin_keys(index, tf_value, tf_unit)` — reused by `ohlcv_data` for timeframe binning
- `_apply_time_filter(df, start, end)` — reused by `ohlcv_data`
- `_session_starts(times)` — reused by `ohlcv_data`

**In-memory models:**
- `ChartData` — numpy arrays `o/h/l/c`, `volume`, `buy/sell volume`, `delta`, `delta_pct`; lists `tick_volume` & `passive_orders` (per-price dicts); `times` (tz-aware) & `times_ns`; `session_starts`; `n / len()`
- `IndicatorData` — `.has(col)` → bool, `.col(col)` → numpy float array aligned to bars (VWAP bands, `cumulative_delta`, `absorption_score`, …). Shared with the OHLCV chart for VWAP rendering.
- `BigTradeData` — time-sorted arrays `price`, `size`, `side`, `ts_ns`, `tod_min`; `n / len()`

### views/footprint_chart/volume_profile.py
Peak-based volume-profile algorithm. Smooths per-price volume, finds clustered peaks, expands each to 70% value area and keeps the tightest — giving meaningful POC/VAH/VAL even on bimodal profiles.
- `compute_profile(data, start_idx, end_idx, tick_size)` → `Profile | None`
- `class Profile`: `start_idx`, `end_idx`, `levels` (price→{total,buy,sell}), `poc`, `vah`, `val`, `max_total`, `total`

### views/footprint_chart/footprint_settings.py
All persisted visual settings as dataclasses, each with `.load()` and `.save()`. Read live by the canvas — change one + repaint = chart updates without reloading data.
- `OrderFootprintSettings` — imbalance gradient + highlight thresholds
- `VolumeFootprintSettings` — volume footprint gradient + show-delta toggle
- `PassiveOrderSettings` — resting-liquidity gradient + highlight
- `BigTradeSettings` — bubble sizing, ETH/RTH min-contract filters, `days_back`
- `GeneralSettings` — RTH session `start` (incl) / `end` (excl) — shared by big trades & ETH/RTH profiles. QSettings prefix: `general/`
- `VolumeProfileSettings` — RTH profile minutes, composite days/end, vol/delta/composite bar widths

### views/footprint_chart/open_dialog.py
The 'Open chart' pop-up for the footprint chart. Picks dataset (keyword: `"advanced"`), indicators (keyword: `"indicators"`), and big-trades dataset.
- `class OpenChartDialog` — QDialog; on accept builds and stores a `FootprintConfig`
- `.config` → `FootprintConfig`

### views/footprint_chart/settings_dialog.py
Categorised settings window (General, Footprint, Volume Footprint, Passive, Volume Profile, Big Trades). Edits settings dataclasses live, persists them, fires callbacks for repaint/reload.
- `class FootprintSettingsDialog` — non-modal QDialog; takes settings objects + `on_change` / `on_bt_reload` / `on_composite_reload` callbacks

### views/footprint_chart/canvas.py
The heart of the footprint chart. QPainter widget that draws candles and every overlay, handles all mouse interaction (pan, zoom, drawing tools, editing, deletion, tooltips). Owns a `Viewport`, reads data models + settings.
- `set_data(data, tick_size, focus_last_session=True)`
- `set_indicators(indicators)` / `set_big_trades(big_trades)`
- `toggle_layer(name)` — show/hide footprint, volume, passive, vwap, cvd, big_trades
- `set_vwap_type(vtype)`
- `add_session_profiles(kind)` — ETH or RTH volume profiles, one per session
- `set_composite(levels, days)` / `clear_composite()`
- `set_draw_mode(mode)` — hline, ray, vline, box, long, short, delete, vp (no "edit" mode)
- `clear_all()` — removes all drawings

### views/footprint_chart/window.py
Footprint chart window. Builds toolbar, loads data via loaders, wires toolbar actions to canvas.
- `class FootprintWindow` — QMainWindow; constructed with a `FootprintConfig`, opens maximised. Data load lives in `_reload_chart_data()`; `set_date(date)` updates `config.date` + title and re-runs it (used by the menu's Live Date Control).
- Toolbar starts with a **timeframe selector** (`core/timeframes.TimeframeSelector`); `_set_timeframe(value, unit)` mutates `config.tf_value/tf_unit` and reloads. `_reload_chart_data()` wraps the load in `capture_anchors`/`restore_anchors` (plus `_capture_profiles`/`_restore_profiles`, which recompute volume profiles via `compute_profile`), so drawings survive timeframe and date changes; a failed load parks the snapshot in `_pending_snapshot`/`_pending_profiles` until the next successful one.

---

## OHLCV chart — file reference

### views/ohlcv_chart/ohlcv_config.py
Plain dataclass — the resolved menu selection handed to an OHLCV chart window. Same shape as `FootprintConfig` but without `big_trades_dataset`.
- `class OhlcvConfig`: fields: `root`, `type_folder`, `asset`, `dataset`, `date`, `days_back`, `time_start`, `time_end`, `tf_value`, `tf_unit`, `indicators_dataset`
- `dataset_path()` / `indicators_path()` → `str | None`
- `has_dataset()` / `has_indicators()` → `bool`
- `timeframe_str()` → `str`

### views/ohlcv_chart/ohlcv_data.py
Disk → memory loading for OHLCV data. Reuses low-level helpers from `footprint_data` but aggregates only standard OHLCV columns (no `buy_volume`/`sell_volume` required).
- `load_ohlcv(config)` → `OhlcvData | None`
- `load_ohlcv_indicators(config, candle_times)` → `IndicatorData | None` — delegates to `footprint_data.load_indicators`; `IndicatorData` is reused as-is
- `_resample_ohlcv(df, tf_value, tf_unit)` → `DataFrame` — OHLCV-safe resampler; uses `_bin_keys` from footprint_data but only aggregates open/high/low/close/volume

**In-memory model:**
- `OhlcvData` — numpy arrays `o/h/l/c`, `volume`; `times` (tz-aware list); `session_starts`; `n / len()`

### views/ohlcv_chart/ohlcv_settings.py
Single settings dataclass for the OHLCV chart. QSettings prefix: `ohlcv_general/` (separate from footprint's `general/`).
- `class OhlcvGeneralSettings`: `rth_start` / `rth_end` (HH:mm strings), `rth_start_min()` / `rth_end_min()` → int, `.load()` / `.save()`

### views/ohlcv_chart/open_dialog.py
'Open chart' pop-up for the OHLCV chart. No big-trades row. Dataset default keyword: `"ohlcv"`. Indicators default keyword: `"indicators"`.
- `class OhlcvOpenDialog` — QDialog; on accept builds and stores an `OhlcvConfig`
- `.config` → `OhlcvConfig`

### views/ohlcv_chart/settings_dialog.py
Settings window for the OHLCV chart. Single category: **General** (RTH start / RTH end). Changes apply live via `on_change` callback.
- `class OhlcvSettingsDialog` — non-modal QDialog; takes `general_settings` + `on_change` callback

### views/ohlcv_chart/canvas.py
QPainter chart widget for the OHLCV chart. Structurally identical to `FootprintCanvas` but stripped down — no footprint cells, no passive orders, no CVD panel, no big-trade bubbles, no volume profiles.
- Owns `Viewport` and `OhlcvGeneralSettings`
- Layers: only `{"vwap": bool}` — toggled via `toggle_layer("vwap")`
- `set_data(data, tick_size, focus_last_session=True)`
- `set_indicators(indicators)` / `set_vwap_type(vtype)`
- `set_draw_mode(mode)` — hline, ray, vline, box, long, short, delete (no "edit" mode)
- `clear_all()` / `reset_view()`
- Tooltip shows: date/time, O/H/L/C, volume
- Candles always render full-width body (no thin-body/footprint mode)

### views/ohlcv_chart/window.py
OHLCV chart window. Builds toolbar, loads data, wires toolbar to canvas.
- `class OhlcvWindow` — QMainWindow; constructed with an `OhlcvConfig`, opens maximised. `set_date(date)` / `_reload_chart_data()` reload for a new anchor date (menu Live Date Control). `_reload_chart_data()` uses `capture_anchors`/`restore_anchors` + `_pending_snapshot` exactly like the footprint window (no profiles).
- Toolbar: timeframe selector | VWAP toggle + type selector (disabled when no indicators) | drawing tools (hline, ray, vline, box, long, short, delete) | Clear | Reset View | ⚙ settings
- `OhlcvData` now also carries `times_ns` (epoch-ns bar starts), mirroring `ChartData`

---

## DOM heatmap chart — file reference

### views/heatmap_chart/heatmap_config.py
Plain dataclass — the resolved menu selection handed to a heatmap window. Same shape as `OhlcvConfig` minus indicators; `tf_value`/`tf_unit` are kept for parity but ignored (the chart is always 1-second native).
- `class HeatmapConfig`: `root`, `type_folder`, `asset`, `dataset`, `date`, `days_back`, `time_start`, `time_end`
- `has_dataset()` / `dataset_path()` / `timeframe_str()` (returns `"1 Second"`)

### views/heatmap_chart/heatmap_data.py
Disk → memory loader for 1-second MBO snapshots. Reuses `select_day_files`, `_apply_time_filter`, `_session_starts` from `footprint_data`. **No resampling** (a book snapshot can't be aggregated). The depth books are kept as raw JSON strings and parsed **lazily per second** (82,800 rows × ~1,700 levels would be multi-GB if parsed eagerly).
- `load_heatmap(config)` → `HeatmapData | None`
- `_parse_depth(raw)` → `{price: qty}` (single-int values, unlike footprint's `[buy, sell]`)
- `HeatmapData` — numpy `o/h/l/c`, `volume`, `best_bid`, `best_ask`; `times`, `session_starts`, `n / len()`; raw `bid_depth`/`ask_depth` strings; `levels(i)` → cached `(bid_dict, ask_dict)`; `level_arrays(i)` → cached float arrays; `default_ref` (exact-path colormap fallback)
- **Aggregation pyramid** (the renderer at *all* zoom levels): `build_or_load_pyramid(data, config, tick, crop_ticks, progress_cb, cancel_cb)` → `HeatmapPyramid | None`. Builds a multi-resolution max-pooled depth grid on a fixed absolute price grid: **1 s base** (exact per-second), then ×4 levels → **1/4/16/64/256 s**; per level `depth` (int16 `[buckets × bins]` = **max** resting size over the bucket, bid+ask combined) and `o`/`h`/`l`/`c` (OHLC per bucket — O=first, H=max, L=min, C=last — for the gray price overlay). Parsing all books is parallelized across a process pool (`_scatter_chunk`, ~9 s on the test day) with a single-process fallback. `pyr.ref_eth`/`pyr.ref_rth` are the 99.7th-percentile depth references **per session** (RTH books are larger than ETH; one global scale washes ETH out) — split using `HeatmapData.tod_min` + the RTH window passed to `build_or_load_pyramid(..., rth_lo, rth_hi)`. Base grid ≈ 150 MB/day in RAM. Result is cached to `<dataset>/.heatmap_cache/<key>.npz`, invalidated by source mtime/size + build params (which now include the RTH window + crop), so reopening is instant and changing the RTH window/crop rebuilds once. `orjson` is used if installed (else stdlib `json`).

### views/heatmap_chart/heatmap_settings.py
Settings dataclass, persisted via QSettings prefix `heatmap/`. Colors are **per session** (ETH/RTH) because RTH resting size dwarfs ETH.
- General: `rth_start`/`rth_end` (RTH window; also the ETH↔RTH color split + initial-view anchor), `crop_ticks` (± window around touch / pyramid grid margin), `show_dom_panel`.
- Per session: `rth_contrast`/`rth_high_contrast`/`rth_max_ref` and `eth_contrast`/`eth_high_contrast`/`eth_max_ref` (`max_ref` 0 = auto from `pyramid.ref_rth`/`ref_eth`).
- `rth_start_min()` / `rth_end_min()`; `.load()` / `.save()`. Color edits repaint live; RTH-window/crop edits rebuild the pyramid.

### views/heatmap_chart/open_dialog.py
'Open chart' pop-up. No indicators row, no timeframe row. Dataset keyword: `"mbo"`.
- `class HeatmapOpenDialog` — QDialog; builds a `HeatmapConfig` on accept

### views/heatmap_chart/settings_dialog.py
Three-category settings window: **General** (RTH start/end, crop ticks, show-ladder), **RTH heatmap**, **ETH heatmap** (each: contrast, high-level contrast, full-color qty).
- `class HeatmapSettingsDialog(settings, on_change, on_rebuild)` — color edits → `on_change` (live `canvas.apply_settings`); RTH-window/crop edits fire on `editingFinished` → `on_rebuild` (window rebuilds the pyramid behind the progress dialog).

### views/heatmap_chart/canvas.py
QPainter/numpy widget. Owns a `Viewport`, reads `HeatmapData` + `HeatmapSettings` + an optional `HeatmapPyramid`. Shares the full drawing-tool set with the other charts.
- `set_data(data, tick_size, focus_last_session=False)` / `set_pyramid(pyr)` / `toggle_layer(name)` (`"lines"`, `"dom"`) / `apply_settings()` / `set_draw_mode(mode)` / `clear_all()` / `reset_view()`
- **The pyramid renders at every zoom level** (`_use_pyramid()` → `pyramid is not None`). `_draw_heatmap_pyramid()` slices the level chosen by `_pick_level()` (targets ~3 px per bucket, so it never oversamples below pixel resolution), maps the whole `[buckets × bins]` grid to colors in one shot, and `drawImage`-scales it across the chart rect — no per-column loop, <15 ms at any zoom. The 1 s base means zoomed-in stays pixel-crisp. `_draw_heatmap()` (exact per-second numpy blit) remains only as a **fallback when the pyramid is `None`** (build failed/cancelled). **Each column is colored by its own session**: `_draw_heatmap_pyramid` builds per-bucket `ref`/contrast/high arrays from each bucket's session (`data.tod_min` + RTH window) and broadcasts them in the vectorized color map; `_session_params(is_rth)` / `_is_rth(sec)` drive the exact path, DOM ladder, and tooltip.
- `_draw_ohlc(pyramid=…)` a single **gray OHLC-bar** price overlay (vertical high→low line + left tick=open, right tick=close) per time bucket — sidesteps the unknown high/low order. From per-second OHLC when zoomed in, from the pyramid's per-bucket OHLC when zoomed out. Toolbar toggle labelled "OHLC" (layer key still `"lines"`).
- `_draw_dom_panel()` right-edge per-price quantity ladder (bars + numbers) for the rightmost visible second; always exact (one column); tracks pan automatically
- `_init_view()` opens zoomed to the **RTH open** (`rth_start`) + ~30 min, not the whole day
- Tooltip: time, O/H/L/C, volume, best bid/ask, resting qty at the hovered price

### views/heatmap_chart/window.py
Heatmap window. Builds toolbar, loads data + pyramid, wires toolbar to canvas.
- `class HeatmapWindow` — QMainWindow; constructed with a `HeatmapConfig`, opens maximised. `set_date(date)` / `_reload_chart_data()` reload + rebuild/load the pyramid for a new date (menu Live Date Control; the progress dialog appears only on a real build).
- `_load_pyramid()` builds/loads the pyramid behind a `QProgressDialog` shown **only when an actual build happens** (cache hits stay silent); Cancel falls back to the exact-only path
- Toolbar: OHLC overlay toggle | Ladder toggle | drawing tools | Clear | Reset View | ⚙ settings

---

## Options exposure chart — file reference

### views/options_chart/options_config.py
Plain dataclass — the resolved menu selection handed to an options window. Single-day, 5-min native (no days_back / timeframe / time filters).
- `class OptionsConfig`: fields: `root`, `type_folder` (options folder), `asset`, `dataset`, `futures_type_folder`, `futures_dataset` (underlying price source), `date`
- `dataset_path()` / `futures_path()` → `str`; `has_dataset()` / `has_futures()` → `bool`

### views/options_chart/black76.py
Pure-numpy Black-76 math — no Qt, no scipy (normal CDF via vectorized Abramowitz–Stegun erf, |err| < 1.5e-7).
- `price(F, K, T, sigma, r, cp)` / `greeks(F, K, T, sigma, r, cp)` → `(delta, gamma, vanna, charm)`; `cp` = +1 call / −1 put; vanna per 1.00 σ, charm per **year** (callers rescale)
- `implied_vol(mid, F, K, T, r, cp, n_iter=24)` — vectorized bracketed Newton (bisection fallback) on the undiscounted price; no-arbitrage guards (crossed/zero quotes, mid ≤ intrinsic + 0.01, upper bound) → NaN
- `fill_iv_by_strike(iv, strike, expiry_ns)` — fills NaN IVs by per-expiry strike interpolation (calls/puts share vol; flat wing extrapolation; <2 valid points → stays NaN)

### views/options_chart/options_data.py
Loads one day of sparse 5-min option rows and densifies to per-contract forward-filled state grids. Reuses `select_day_files` (weekend fallback like other charts).
- `load_options_day(config, settings, progress_cb, cancel_cb)` → `OptionsDay | None` (None: no options file, empty df, or missing futures file — F is required everywhere)
- `OptionsDay` — `times/times_ns/n_t`; static `strike`, `cp`, `expiry_ns`, `strikes_sorted`, `strike_slot`, `mult`; **ffilled float32 grids `[n_inst × n_t]`**: `bid, ask, oi, est_oi, flow` (~45 MB/day); `quote_backfilled` bool mask; `F` float64 `[n_t]` (futures close ≤ t); `date` = actually loaded date
- Contracts absent from metadata are dropped (count logged). Instruments with no bid/ask all day get quotes backfilled from up to `settings.quote_lookback_files` previous day files (fills only the NaN prefix, preserving most-recent semantics)
- **Gotcha:** the futures parquet index is `datetime64[us]`, options `[ns]` — both normalized via `.as_unit("ns").asi8` before `searchsorted`

### views/options_chart/options_compute.py
Turns a time-column slice into per-strike exposure bars.
- `ExposureParams(greek, oi_source, sign_mode, units, bucket, r)` — frozen, used as cache key
- `bucket_mask(day, bucket, anchor)` — calendar expiry filters: All / 0DTE / This Week / Next Week / This Month / Next Month / This Quarter / This Year (`EXPIRY_BUCKETS`); expired contracts always drop via `T ≤ T_MIN` (1 min)
- `iv_at(day, t, r, cache)` — mid → `implied_vol` → `fill_iv_by_strike`, cached per t
- `compute_exposure(day, t, params, iv_cache, result_cache)` → `StrikeExposure | None` (None iff `F[t]` NaN). Position: OI/est-OI sources = `sign_c × oi` (sign_c from assumption: calls_long / puts_long / all_long); dealer_flow source **ignores the sign assumption entirely** (it is our own exposure algorithm): flow used as-is where traded, contracts with NaN flow fall back to est_oi with the FIXED calls-long/puts-short convention into the separate `fallback` array (drawn dimmed). The window disables the sign combo in dealer-flow mode and pins `sign_mode` in the cache key. Units: `pct` ($/1% move: γ·pos·mult·F²·0.01, others ·mult·F), `point` (·mult), `contracts` (raw); vanna /100 (per vol-pt), charm /365 (per day)
- `StrikeExposure` — per-strike `total/primary/fallback/call_part/put_part/n_contracts/oi_total` + `F`, `time`, `units_label`. `n_contracts` counts option **series** (instruments) per strike, `oi_total` sums raw open_interest (both shown in the tooltip: "OI 12,345 · 95 series")
- **Raw-OI greek modes** (`TOTAL_MODES = ("total_oi", "oi_split")`): raw position views, no greeks/IV (quote-less contracts count too) — puts drawn positive/green, calls negative/red, fixed regardless of sign assumption; units pinned to Contracts (sign+units combos disabled in the windows). `total_oi` nets both sides into one bar per strike; `oi_split` (`StrikeExposure.split=True`, with `put_fb`/`call_fb` fallback splits) draws the put stack up AND the call stack down at each strike simultaneously — bar chart only (the interval map's greek combo filters it out; a dot can't show two sides). `units_label_for(params)` is the shared label helper

### views/options_chart/options_settings.py
- `OptionsSettings` (QSettings prefix `options/`): `risk_free_rate` (%, default 4.0), `quote_lookback_files` (3), `playback_ms` (300), `dim_factor` (0.45); `r()` → decimal; `.load()/.save()`

### views/options_chart/settings_dialog.py
Single-page non-modal dialog. Rate → clears IV+result caches and recomputes; lookback → data reload; playback → live `timer.setInterval`; dim → repaint.

### views/options_chart/open_dialog.py
Asset (from options folder) + options dataset (keyword `"5m"`) + futures dataset (from futures folder, keyword `"ohlcv"`). Both datasets validated on accept.

### views/options_chart/canvas.py
QPainter bar chart. Viewport reused with **ordinal strike slots** on x (`candle_x(i)` over `strikes_sorted`) and **exposure dollars** on y (`price_min/max = ±M`, `center_price=0`). No drawing tools, no `drawing_anchors`.
- `set_day(day)` / `set_result(res)` / `set_message(msg)` / `reset_view()` / `request_rescale()`
- Y autoscale only on load / param change / Reset View — **frozen while scrubbing** so bars move against a stable axis
- Paint: value axis (nice-number steps, $B/M/k labels, bright zero baseline) → strike axis → bars (primary full color green/red; `fallback` stacked at `[primary, primary+fallback]` with `dim_factor` alpha) → dashed yellow underlying line at F → header (time · units · net) → tooltip (strike, total, call/put split, flow/est split, contract count)
- Mouse: drag pans both axes, wheel h-scroll, Ctrl+wheel y-zoom, Shift+wheel x-zoom (same scheme as other charts)

### views/options_chart/window.py
- `class OptionsWindow` — QMainWindow (title "Dealer Exposure · …"); toolbar / canvas / slider bar. Toolbar: Greek ▾ (Delta/Gamma/Vanna/Charm/Total OI/OI Split) | OI source ▾ (Open Interest / Est. OI / Dealer Flow) | Sign ▾ | Units ▾ | Expiry ▾ | Reset View | ⚙. All combos → `_on_param_changed` (clear result cache, rescale, recompute)
- Slider bar: ▶/⏸ (QTimer wraps `(v+1) % n_t`) + QSlider over the day's 5-min timestamps + `%a %H:%M` label
- `_reload_chart_data()` — lazy QProgressDialog (heatmap idiom); restores slider position by nearest minute-of-day across reloads; failed load → message + disabled slider (window stays alive)
- `set_date(date)` — mutate config, retitle, reload → participates in the menu's Live Date Control

---

## Interval map — file reference

Reuses the options chart wholesale: `OptionsConfig`, `OptionsOpenDialog` (via its `title` kwarg), `load_options_day`/`OptionsDay`, `compute_exposure`/`ExposureParams`, `black76`, `OptionsSettings` + `OptionsSettingsDialog` (same QSettings prefix `options/` — rate/lookback deliberately shared with the bar chart; playback/dim rows are harmless no-ops here). The shared toolbar vocabularies (`GREEKS`, `OI_SRCS`, `SIGNS`, `UNITS`) live in `options_compute.py`.

### views/interval_map/interval_compute.py
Qt-free day-grid builder.
- `INTERVALS` (5/10/15/30/60 min), `STRIKE_STEPS` (All/5/10/25/50/100), `DOT_THRESHOLD` (0.005 — cells below this fraction of vmax draw nothing)
- `build_interval_grid(day, params, interval_min, strike_step, iv_cache, progress_cb, cancel_cb)` → `IntervalGrid | None` — samples every k-th 5-min bar (`k = interval_min // 5`), runs `compute_exposure` per column (fresh local result_cache; the **shared `iv_cache` is the warm-rebuild win**: ~1.4 s cold at 10-min, ~0.1 s warm). Rows filtered to strikes divisible by `strike_step` (float-safe `|q − round(q)| < 1e-9`) AND nonzero somewhere; None if no rows or cancelled.
- `IntervalGrid` — `strikes` (rows, ascending), `t_idx`/`times` (cols), `total/call_part/put_part [rows × cols]`, `F` per col (NaN-safe), `f_row` (fractional row of F), `vmax`, `units_label`

### views/interval_map/canvas.py
QPainter dot-grid widget. Viewport y = **fractional strike-row index** (`price_min=0, price_max=n_rows`; row i spans `[i, i+1)`, centered at `i+0.5`; hover row = `floor(y_to_price(my))`); x = ordinal interval columns via `candle_x(j)`.
- `set_grid(grid)` — re-inits the view **only when the row/col axes actually changed** (greek toggles preserve pan/zoom); precomputes a **sparse nonzero-cell list** so paints never loop the full 507×138 grid
- `_init_view()` — all columns visible; y centered on the underlying's day range + padding (≥4 rows)
- Paint: strike axis (labels thinned by row-px) → time axis → dots (visible-window mask, vectorized screen coords, radius `max(1, 0.45·min(slot_w, row_px)·√(|v|/vmax))`, green/red two-pass) → blue underlying polyline (segments broken at NaN F, drawn over dots) → header → tooltip (time, strike, total, calls/puts, underlying)
- Mouse/wheel identical to the other canvases; no drawing tools, no `drawing_anchors`

### views/interval_map/window.py
- `class IntervalMapWindow` — toolbar / canvas (no slider — whole day at once). Toolbar: the five exposure combos (same dealer-flow sign rule: combo disabled + `sign_mode` pinned) | Interval (default 10 min) + Strike step (default All) | Reset View | ⚙. Every combo change rebuilds the grid.
- `_rebuild_grid()` — behind a **deferred** progress dialog (created only if the build exceeds 0.3 s, so warm rebuilds stay silent; cancel → message)
- `set_date(date)` — retitle + reload day + clear IV cache → Live Date Control participant

---

## Trade replay — file reference

A browser for backtest trades (`views/trade_replay/`). Loads one trades parquet (one row per trade), steps through trades, and pushes the selected trade to every open chart: `set_date(trade.date)` on **all** charts, plus an auto-drawn position (`{"dir","idx1","idx2","entry","tp","sl"}` appended to `canvas.positions`) on footprint/OHLCV — **never on the heatmap**. Default folder: `<parquet-root>/../trades` (e.g. `D:\market_data\trades`), persisted via `Keys.REPLAY_DIR`/`REPLAY_FILE`.

### views/trade_replay/trades_data.py
- Canonical columns: `date, direction, trade_type, entry_time/exit_time (tz-aware), entry_price, exit_price, sl, tp (PRICES), exit_reason, pnl_points, ticks, cumulative_ticks, notes (JSON str)`. Only `date, direction, entry_time, exit_time, entry_price` are required — everything else is fail-soft (older files lack `trade_type`/`notes`); unknown extra columns surface as generic detail cards + table columns.
- `load_trades(path)` → `TradeSet | None` — normalizes `date` to `'YYYY-MM-DD'` str, parses notes JSON per row, derives `sl_ticks`/`tp_ticks`/`rr`/`duration_min` (tick size from the `ES_…` filename prefix via `tick_size_for`)
- `TradeSet` — `df`, `notes: list[dict]`, `tick_size`, `extra_cols`, `table_cols`; `column_kind(col)` → `numeric|time|date|categorical`; `filter_values(col)` → numeric array (times → minute-of-day, dates → yyyymmdd)
- `default_trades_dir(root)` / `list_trade_files(folder)` (newest first, fail-soft)

### views/trade_replay/filter_expr.py
Vectorized filter mini-language: comma = OR of terms, columns AND together; `term := (>=|<=|=|==|>|<) value | a..b | value`. Values: numbers, `HH:MM` (time cols), `YYYY-MM-DD` (date col). `parse_spec(spec, kind)` → mask fn | None (syntax error → UI red border, filter ignored); `compute_mask(trade_set, filters)` → bool mask. NaN rows never match.

### views/trade_replay/widgets.py
- `CheckableComboBox` — multi-select combo for categorical filters (no checks = "All"; popup stays open)
- `FilterHeader(QHeaderView)` — filter editor row embedded under the table header (line edit or checkable combo per column), 250 ms debounce, `filters_changed` signal, `mark_invalid(col, bool)`
- `StatCard` — the screenshot-style titled value card (`QFrame[card="true"]` style)
- `EquitySparkline` — tiny cumulative-ticks curve (green/red by sign)

### views/trade_replay/trades_table.py
- `TradesTableModel` — `TradeSet.df` minus notes; formatted DisplayRole (times `HH:MM`, `duration_min` as `1h 05m`), raw UserRole for sorting, direction/ticks sign-colored
- `TradesFilterProxy` — `set_mask(np.ndarray)` row filter; sorts on UserRole with NaNs always last

### views/trade_replay/helpers.py + plugins/
Plugin/scripting system. A plugin is a file in `views/trade_replay/plugins/` defining `run(ctx)` (+ optional `NAME = "..."` shown in the menu; `_`-prefixed files are hidden). **Plugins are re-imported fresh on every run — edit + re-run, no app restart** (unique in this codebase; `run_plugin` uses `spec_from_file_location` without touching `sys.modules`).
- `PluginContext`: `.trade` (pd.Series), `.notes` (dict), `.charts`/`.footprints`/`.ohlcv` (ChartHandles; heatmap never included), `.chart` (first footprint), `.params` (from the window's Params box) + `.param(key, default)`, `.log(*args)` → output dialog.
- `ChartHandle` (wraps a footprint/OHLCV window): colored drawings `hline/vline/ray/box/text` (→ `canvas.annotations`), `position()` (→ real `canvas.positions` dict), `profile(t1,t2)` → `{"poc","vah","val","total","max_total","levels"}` | None (compute only; always None on OHLCV — no tick_volume), `draw_profile(t1,t2)` (also appends a real Profile to `canvas.profiles`), `vwap(on, vtype)` (syncs the toolbar via combo + `toggle_layer`), `clear(everything=False)`, `set_date`, `.window`/`.canvas` escape hatches. Times: `"HH:MM"` (anchor date, Globex-corrected — `"18:30"` → previous evening), `"YYYY-MM-DD HH:MM"`, Timestamp/datetime, epoch ns. Colors: names/hex/tuples, resolved by `_resolve_color` (loud ValueError on typos).
- `parse_params("start=09:30 mult=2 fast")` → typed dict (int/float/bool auto-coerced, bare tokens → True flags, never raises).
- Shipped: `example_vp_levels.py` (VP to entry + POC/VAH/VAL lines + VWAP; honors `start=` param), `_template.py` (full API cheat-sheet, hidden).

### views/trade_replay/window.py
- `class TradeReplayWindow(menu=…)` — horizontal splitter: main area | **plugin side panel**. Main area: file bar (folder Browse + file combo) | nav bar (◄ ► "Trade i / N", **Load to charts**, status label). Side panel (`_build_plugin_panel`): plugin combo (+ ⟳ rescan, selection persisted `Keys.REPLAY_PLUGIN`), multi-line **Params** box (`ctx.params`, persisted `Keys.REPLAY_PARAMS`, 600 ms debounced save), **"Auto-run on every load"** checkbox (`Keys.REPLAY_PLUGIN_AUTORUN`, default on — `_load_to_charts()` re-runs the selected plugin after every load, guarded against recursion by `_plugin_loading`), "Run button loads trade first" checkbox (`Keys.REPLAY_PLUGIN_AUTOLOAD`), accent **Run plugin** button, Clear drawings / Folder buttons, and an inline monospace **Output** log (plugin `ctx.log` lines + error tracebacks — no popups) | stats bar over the **filtered** set (Trades, Win Rate, Total Ticks, Avg Win/Loss, Profit Factor, Max DD + sparkline; cumsum recomputed on the filtered subset) | splitter: a **tab widget** — "Trade Detail" (cards like the mockup + "Trade notes" grid from the JSON dict, hidden when empty) and "Breakdown" (`_update_breakdown`: group-by combo — trade type / exit reason / direction / weekday / entry hour / duration bucket / month — with per-bucket n, win %, total/avg ticks, PF over the **filtered** set) — over the filterable/sortable table. The stats-bar sparkline is clickable → non-modal **equity dialog** (`widgets.EquityCurveView`): full cumulative-ticks curve with drawdown shading, hover readout, and click-a-point → selects that trade in the table/detail (selection syncs back as a marker). Navigation runs in proxy (filtered+sorted) order; double-click row = load to charts.
- `_load_to_charts()`: removes the previously auto-drawn positions **by identity** (user drawings untouched), `set_date` on every `menu._live_windows()` entry, then per footprint/OHLCV chart maps `entry_time`/`exit_time` → candle indices via `np.searchsorted(times_ns, ts, "right")-1` on **that chart's own data** (per-chart timeframes give different indices), appends the position dict + `canvas.update()`, and tracks `(weakref(window), pos)`. Trades fully outside a chart's loaded data are skipped (status message); partial overlap clamps + notes it. Because `restore_anchors` mutates position dicts in place, the auto position survives later timeframe/date reloads and is still found for removal.

---

## Data on disk

```
data/parquet/{type}/{asset}/{dataset}/YYYY-MM-DD.parquet
e.g. .../Futures/ES/ES_1m_advanced/2025-04-30.parquet
     .../Futures/ES/ES_1m_ohlcv/2025-04-30.parquet
```

| Dataset folder | Contents | Used by |
|---|---|---|
| `ES_1m_advanced` | Enriched 1-min candles: OHLC, volume, buy/sell volume, delta, delta_pct, tick_volume (per-price buy/sell JSON), passive_orders (resting liquidity JSON) | Footprint chart |
| `ES_1m_ohlcv` (or any folder with "ohlcv" in name) | Standard OHLCV candles: OHLC + volume | OHLCV chart |
| `ES_1m_indicators` (or any folder with "indicators" in name) | 28 VWAP columns (4 anchors × bands), cumulative_delta, absorption-score columns | Footprint + OHLCV charts |
| `ES_1s_mbo` (or any folder with "mbo" in name) | 1-second MBO snapshots: OHLCV, buy/sell volume, best_bid/best_ask, aggressor_volume + bid_depth + ask_depth (per-price JSON books). 82,800 rows/session, ~200 MB/day | DOM heatmap chart |
| `ES_big_trades` | One row per large trade: price, size, side (B/A/N), tz-aware timestamp index | Footprint chart only |
| `Options_on_futures/ES/ES_options_5m` | Sparse 5-min option rows: instrument_id, OHLCV, bid/ask, open_interest, daily_estimated_oi, dealer_oi_flow (cumulative within day). Full snapshot at 18:00 + morning-update snapshot ~10:05, then only changed instruments. Contract defs (strike/cp_flag/expiry per instrument_id) + point multiplier live in the parquet **schema metadata** (keys `contracts`, `multiplier`). ~8-10k contracts, ~47k rows/day. A stray `_flow_state.parquet` sits in the folder (skipped by `select_day_files`) | Options exposure chart |
| `<root>/../trades/*.parquet` (outside the parquet root, e.g. `D:\market_data\trades`) | One row per backtest trade: date, direction, entry/exit time+price, sl/tp prices, exit_reason, ticks, notes JSON | Trade replay |

One Parquet file per trading day. Indexed by tz-aware `America/New_York` timestamp. Covers full Globex session (18:00 previous evening → 17:00). **The chart never writes to these files.**

---

## Conventions & gotchas

- **core vs view:** if a second chart type would need it → `core/`; otherwise → that chart's folder
- **One-way data flow:** loaders return immutable models; canvas only reads. Never mutate loaded data in place.
- **Settings are live:** visual settings are read on every paint, so change + repaint is enough — *except* composite days/end-time and big-trade `days_back` in the footprint chart, which reload data via callbacks
- **RTH window is per-chart:** footprint uses `GeneralSettings` (QSettings prefix `general/`); OHLCV uses `OhlcvGeneralSettings` (prefix `ohlcv_general/`). They are independent — changing one does not affect the other.
- **Heatmap is 1-second native:** no resampling for the exact view — the order book is a per-second snapshot. The full book is uncapped (~1,700 levels/sec); the exact path crops to `crop_ticks` around the touch and parses depth lazily per second. The heatmap is always drawn via a numpy→`QImage` blit, never per-cell `fillRect`.
- **The heatmap renders from the precomputed pyramid at ALL zoom levels, not just zoomed out:** parsing+looping per column per frame is too slow even at ~15 min (~13 fps). `build_or_load_pyramid` precomputes a max-pooled multi-resolution depth grid once (process-pool parse, ~9 s, 1 s base ≈ 150 MB/day) and caches it to `<dataset>/.heatmap_cache/*.npz`; the canvas uses it whenever it exists, falling back to the exact path only if the build failed. Honors the "**max** of resting per level" rule (traded volume — not rendered here — would be **summed**). If you change the grid params (`_PYR_*` constants) or cache format, bump `_CACHE_VERSION` so stale caches are rejected.
- **Heatmap colors are per-session (ETH/RTH).** RTH resting size ≈3× ETH, so one global scale washes ETH out. Each column is colored on its own session's scale (`pyramid.ref_rth`/`ref_eth`, or the per-session `max_ref` override) split at the RTH window. The dark line that tracks price is the real bid/ask spread (almost nothing rests *at* the trade price), not a bug.
- **Resampling OHLCV vs footprint data:** `footprint_data.resample_dataframe` requires `buy_volume`/`sell_volume` and will crash on plain OHLCV Parquet. Always use `ohlcv_data._resample_ohlcv` for OHLCV datasets.
- **IndicatorData is shared:** `footprint_data.IndicatorData` and `load_indicators` are reused directly by the OHLCV chart — they are generic enough to serve any chart type.
- **Timestamps:** everything is tz-aware `America/New_York`. Don't reintroduce `.view('int64')` hacks.
- **Drawings re-anchor by timestamp:** footprint/OHLCV `_reload_chart_data()` runs `capture_anchors`/`restore_anchors` (`core/drawing_anchors.py`) around every reload, so index-anchored drawings stick to their times across timeframe/date changes. Drawing dicts carry a hidden `"_anchors"` key — don't strip it, and mutate drawings in place rather than replacing the dicts (identity matters to the trade replay).
- **Plugin annotations are timestamp-anchored and resolved at paint time** (`canvas.annotations`, rendered by `core/annotations.py`): they need no `drawing_anchors` support — never add them to capture/restore. They're not hit-testable/editable; cleared by every "Load to charts", by Plugins ▾ → Clear annotations, and by the chart's Clear button. Profiles/positions created by plugins are *real* drawings and follow the normal drawing rules.
- **No hot reload:** restart `python main.py` after any edit
- **Direction strings:** `'long'` / `'short'` (lowercase) — chart and downstream tools match exactly
- **No "edit" draw mode (all charts):** drawings show **always-on draggable circle handles** in the default state (`draw_mode is None` → `_draw_edit_handles`). Press a handle → `_edit_target` sets `edit_drag` and the existing per-role mutation logic runs; press empty space → pan. Only the circle drags (clicking the line elsewhere pans); ray/box/position/VP handles sit on the object. "Delete" mode is unchanged (whole-object `_hovered_*` hit-test).
  - h-line handle: `_h_handle` places the dot just right of the price label, at a **stable x** computed from the widest label the price range can produce (`_price_label_w`, using `price_min/max` + tick decimals) — not the dragged line's own label width, so it doesn't flicker horizontally while dragging.
  - v-line handle: `_v_handle` sits just below the time label (`top + 28`).
  - Position handles (4): `pos_tp` / `pos_sl` (price only), `pos_entry` = left-center, **moves the whole trade in both axes** (price translate + left edge follows the cursor, width preserved, clamped to data), `pos_width` = right-center, extends duration. Footprint VP has `vp_start`/`vp_end` (recomputed via `compute_profile` on release).
- **Dataset auto-selection:** open dialogs pick the first folder whose name contains the keyword. Footprint: `"advanced"` / `"indicators"` / `"big_trades"`. OHLCV: `"ohlcv"` / `"indicators"`. Heatmap: `"mbo"`.
