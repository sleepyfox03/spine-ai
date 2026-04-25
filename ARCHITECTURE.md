# Spine AI — Architecture

This document explains how the app is wired: process layout, threads, data flow, responsibilities per module, and the formulas behind the derived metrics.

## 1. High-level process model

```
┌────────────────── Tkinter main thread (UI) ─────────────────┐
│                                                             │
│   SpineAIApp  (app.py)                                      │
│   ├── Sidebar, tab router, live views                       │
│   ├── root.after(1000, _poll) ── single 1 Hz UI ticker ─┐   │
│   └── reads from: posture_queue, eye_queue, shared attrs│   │
│                                                         │   │
└─────────────────────────────────────────────────────────┼───┘
                                                          │
                                                          │ polls every 1000 ms
                                                          │
┌── MonitoringThread (core/monitor.py) ─── 2 fps capture ─┼───┐
│                                                         ▼   │
│   cap.read() → PostureEngine.process(frame) → (PostureResult, EyeResult)
│                                                             │
│   writes → posture_queue / eye_queue (non-blocking)         │
│   writes → self.latest_* shared attrs (camera status, score,│
│            label, blink, distance_cm, annotated frame)      │
│   every 1 s → session_ticker_callback(is_active)            │
│                                                             │
└───────────────────────────┬─────────────────────────────────┘
                            │
                            │ ticks 1/sec
                            ▼
┌── SessionTracker (core/session_tracker.py) ─── tick lock ───┐
│   accumulates sitting / active / break / slouch / stretch   │
│   seconds, good_streak, best_streak, breaks_taken           │
│   fires on_break_needed / on_good_streak callbacks          │
│   (both dispatched on short-lived worker threads)           │
└─────────────────────────────────────────────────────────────┘

┌── ActivityDetector (core/activity_detector.py) ─────────────┐
│   pynput-based global input listener                        │
│   used by MonitoringThread / SessionTracker as the          │
│   "user is actually here" gate                              │
└─────────────────────────────────────────────────────────────┘
```

There is **one** polling loop in the UI thread (`SpineAIApp._poll`). Every 1 s it:

1. Drains `posture_queue` and `eye_queue` and dispatches to the active tab.
2. Advances the 20-20-20 timer.
3. Flushes session stats to SQLite every 60 s.
4. Calls `refresh()` / `tick_active()` on the active tab (Phase 5 additions).

No tab owns a timer. This avoids multiple competing `after()` loops and keeps UI work predictable.

## 2. Module responsibilities

### `main.py` — entry point

- Sets OpenCV env vars **before** `cv2` is imported (`OPENCV_LOG_LEVEL=ERROR`, `OPENCV_VIDEOIO_PRIORITY_MSMF=0`) — this is load-bearing on Windows.
- Shows a splash screen, runs `CalibrationWizard` on first launch, then constructs `SpineAIApp` and enters the Tk mainloop.

### `app.py` — `SpineAIApp`

- Owns the root Tk window, sidebar, clock, and status pulse.
- Lazily constructs tabs on demand — `tab_map` (search for `"Dashboard"` / `"Spine Health"` / `"Eye Health"` / `"Sitting Time"`) passes `app_ref=self` to every tab so tabs can reach `session_tracker`, `monitor_thread`, and `alert_manager`.
- Runs the 1 Hz `_poll` loop that drives all live updates.
- Owns the `SessionTracker` instance and wires its `on_break_needed` → `AlertManager.trigger_break_alert` and `on_good_streak` → `AlertManager.trigger_good_streak` callbacks.

### `core/camera.py` — `open_webcam(index)`

Single source of truth for opening a `cv2.VideoCapture`. Picks `CAP_DSHOW` on Windows and `CAP_ANY` elsewhere. Returns `None` if the device can't be opened. Used by `MonitoringThread`, `CalibrationWizard`, and `calibrate_knn.py` — so backend / failure semantics are consistent.

### `core/posture_engine.py` — `PostureEngine`

The ML heart of the app. On each `process(frame)` call:

1. Runs **YOLOv8-pose** (`yolov8n-pose.pt`) to extract 17 keypoints.
2. Normalises keypoints and derives features (neck angle, shoulder tilt, ear-to-shoulder triangle area, FHP offset, lateral tilt).
3. Classifies posture via a **KNN** trained from the calibration wizard (falls back to rule-based thresholds if the model is missing).
4. Runs **MediaPipe Face Mesh** to compute:
   - **Blink rate (BPM)** via EAR (Eye Aspect Ratio) on landmarks 33/133/159/145 (right) and 362/263/386/374 (left), rolling over a 60 s window.
   - **Screen distance** from the inter-pupillary pixel distance and a focal-length constant: `depth_cm = clip(6.3 * 600 / eye_dist_px, 20, 150)`.
   - **Strain score** (engine-side fallback formula — the Phase 5 Eye Health tab overrides this with its own formula; see §4.3).
5. Returns a tuple `(PostureResult, EyeResult)` — both are `@dataclass` instances. `PostureResult.frame_annotated` is a BGR numpy frame with the skeleton drawn.

### `core/monitor.py` — `MonitoringThread`

- 2 fps (`FRAME_INTERVAL = 0.5`) background capture loop.
- **Shared attributes** read by the UI thread (no locking — simple reads are atomic enough for these floats):
  - `latest_annotated`, `latest_score`, `latest_label`, `latest_neck`, `latest_sh_tilt`, `latest_triangle`, `latest_blink`, `latest_distance_cm`, `latest_triangle`
  - `camera_status` — `"OK"` / `"RECONNECTING"` / `"FAILED"` (surfaces in the main-window status label).
- **Queues** (`posture_queue`, `eye_queue`, `maxsize=20`, non-blocking) — consumed by the UI `_poll` loop.
- **Read-failure resilience** (see `_REOPEN_AFTER`, `_GIVE_UP_AFTER`): 10 consecutive `cap.read()` failures trigger a reopen via `open_webcam`; 30 consecutive failures set `camera_status = "FAILED"` and drop `cap`.
- Pause / resume are honoured (used during recalibration).

### `core/session_tracker.py` — `SessionTracker`

- Single `tick(is_active, label, score)` called once per second by `MonitoringThread`.
- Accumulators (all seconds): `sitting_seconds`, `active_seconds`, `break_seconds`, `slouch_seconds`, `stretch_seconds`, `breaks_taken`, `good_streak`, `best_streak`.
- `get_stats()` returns a flat dict read by the tabs. `total_seconds = sitting + break` (session-elapsed convenience).
- `spine_age(bio_age)` implements the BioAge formula described in §4.1.
- Break/streak callbacks are dispatched on a daemon thread so Tk never blocks on UI-thread callbacks from inside `tick`.

### `core/alert_manager.py` — `AlertManager`

Centralises popups with per-type cooldowns so the same alert doesn't spam the user. Uses `components.notification_popup.NotificationPopup` under the hood.

### `core/calibration.py` — `CalibrationWizard`

A Tk `CTkToplevel` that runs a YOLO pose loop at ~30 fps, draws a ghost skeleton over the camera feed, and collects ~100 frames each for Good and Bad posture. Trains a KNN classifier on exit, persists it to `posture_knn.pkl`, and notifies the engine to hot-reload.

### `database/db_manager.py` — `DBManager`

Thin SQLite wrapper. Tables: `sessions`, `posture_records`, `eye_records`, `profile`. `SpineAIApp._poll` calls `_flush_db()` every 60 s to batch-insert averaged records.

### `components/` and `tabs/`

UI only — no business logic. `MetricCard` and `RingChart` have animated `set_value` / `set_progress` APIs. Tabs pull from `app_ref.session_tracker` / `app_ref.monitor_thread` on each `refresh()` call from `_poll`.

## 3. Data flow — one frame end-to-end

1. **MonitoringThread** (2 fps): `cap.read() → engine.process(frame)`.
2. Engine produces `(PostureResult, EyeResult)` — both go into their respective queues.
3. Engine's `EyeResult.screen_distance_cm` is copied into `MonitoringThread.latest_distance_cm`; the same for `score`, `label`, `blink_rate`, etc.
4. **SessionTracker** gets a 1 Hz `tick(is_active, label, score)` from `MonitoringThread` via `session_ticker_callback`.
5. **UI `_poll`** (1 Hz) drains the two queues:
   - Posture → `_on_posture` → `_push_dashboard` → `DashboardTab.push_posture(label, score, stats)`.
   - Eye → `_on_eye` → `EyeHealthTab.update_blink(bpm, dist_cm, strain=None)` — the tab computes strain itself.
6. `_poll` then calls `refresh()` / `tick_active()` on whichever tab is currently displayed. Tabs that aren't on screen don't run anything (no wasted work).

## 4. Formulas

### 4.1 Spine Age (`SessionTracker.spine_age`)

```
slouch_hours = slouch_seconds / 3600
stretch_minutes = stretch_seconds / 60
raw_age = bio_age + 1.2 × slouch_hours − 0.5 × stretch_minutes
spine_age = clamp(raw_age, bio_age − 5, bio_age + 20)
```

Clamping keeps a 5-minute session from swinging the number wildly.

### 4.2 Spine Score (Dashboard)

```
spine_score = clamp(
    0.7 × good_posture_pct + 0.3 × min(breaks_taken × 20, 100),
    0, 100
)
```

Posture quality dominates (70%); break cadence is a smaller but non-zero factor (30%), capped after 5 breaks so the bonus doesn't run away.

### 4.3 Eye Strain (EyeHealthTab)

```
strain = clamp(
    max(0, (15 − bpm) × 5) + max(0, (50 − distance_cm) × 1.2),
    0, 100
)
```

Low blink rate dominates; close screen distance adds a smaller linear penalty. The ring colors at thresholds: `≥ 70 red`, `≥ 40 orange`, else green.

### 4.4 Screen-distance ranges

```
distance_cm ≥ 70 → "TOO FAR"      (orange)
55–70          → "IDEAL"         (green)
40–55          → "CLOSE"         (orange)
< 40           → "TOO CLOSE"     (red)
```

### 4.5 Best Streak

Tracked inside `SessionTracker.tick`: every time `good_streak` increments, `best_streak = max(best_streak, good_streak)`. Reset on app restart (no DB persistence by design — Phase 5 scoped it as session-only).

## 5. Threading rules

- **Tk calls only on the main thread.** `MonitoringThread` and `SessionTracker` callbacks that need to show popups schedule via `AlertManager`, which builds the `NotificationPopup` (a `CTkToplevel`) — popups are constructed from short-lived daemon threads spawned inside `SessionTracker.tick` to avoid blocking the tracker's lock. This works because `NotificationPopup` doesn't touch the main window's widget tree.
- **No locking on `MonitoringThread.latest_*` reads.** Python's GIL + single-writer pattern makes scalar reads safe enough for a 1 Hz UI poll.
- **`SessionTracker._lock`** guards all state mutations in `tick` and all reads in `get_stats` / `spine_age`.
- **Activity gating.** Both `MonitoringThread` and `_poll` consult `ActivityDetector.is_active()` to decide whether to run the engine and whether to advance the Eye Health 40-min timer.

## 6. Design system (config.py)

"Minimal & Professional" means:

- **Colors:** flat dark green (`BG_PRIMARY = #050a06`, `BG_SECONDARY = #0a140c`, `BG_CARD = #102114`, `BG_CARD_HOVER = #172e1c`), neon green accent (`ACCENT_PRIMARY = #00ff66`), single red (`ACCENT_RED = #ff4444`), off-white text (`TEXT_PRIMARY = #e6f5ea`), muted green-gray secondary text (`TEXT_SECONDARY = #8ab397`).
- **No gradients.** Solid fills only. Hover affordance is a 2 px border color flip (`BG_SECONDARY` → `ACCENT_PRIMARY`) plus a background bump to `BG_CARD_HOVER` — see `components/metric_card.py:36-40` for the canonical pattern; `tabs/spine_health_tab.py` exercise cards mirror it.
- **Typography:** `FONT_DISPLAY` (28, bold), `FONT_HEADING` (16, bold), `FONT_BODY` (12, bold), `FONT_SMALL` (10).
- **Borders:** 1–2 px. `BG_SECONDARY` for inactive, `ACCENT_PRIMARY` for hover/active.

## 7. Phase 5 — what "live wiring" added

| Change | File | Why |
|---|---|---|
| `best_streak` field + stat | `core/session_tracker.py` | Dashboard Best Streak card |
| `total_seconds` stat | `core/session_tracker.py` | Sitting Time tab "since app opened" |
| `latest_distance_cm` attr | `core/monitor.py` | Eye Health Screen Distance card |
| 4-card stats block rewrite | `tabs/dashboard_tab.py` | New formulas (Good%/Slouch%/Best Streak HH:MM/Spine Score) |
| `refresh()` + `USER_AGE` + status label | `tabs/spine_health_tab.py` | Live Spine Age + verdict |
| `tick_active()` + 40-min popup + range labels + strain formula | `tabs/eye_health_tab.py` | Phase 5 eye timer and spec mappings |
| `refresh()` replacing `load_mock_data()` | `tabs/sitting_time_tab.py` | Swap mock for live stats |
| `tick_active` / `refresh` dispatch in `_poll` | `app.py` | Single tick to drive all Phase 5 tabs |

No new threads. No new `after()` loops. Every live number flows through `SessionTracker.get_stats()` or `MonitoringThread.latest_*` — that's the state contract.

## 8. Where to extend next

- **Persistent best-streak** — add a `best_streak_sec` column to `sessions` and read it in `SpineHealthTab` for a lifetime streak.
- **Live activity timeline** on `SittingTimeTab` — segment-color each minute and redraw the Matplotlib bar in `refresh()` (keep the redraw cheap; Matplotlib + Tk is slow past ~100 ms/redraw).
- **Configurable `USER_AGE`** — replace the hardcoded constant with `db_manager.get_profile()` once the profile-edit UI exists.
- **Externalize formulas** — move `spine_age`, `spine_score`, and `strain` into `core/formulas.py` so they're unit-testable without spinning up Tk.
