# BiliX GUI Usability Review (v1.7.1)

| | |
|---|---|
| Date | 2026-10-10 |
| Product version reviewed | 1.7.1 (`main` branch as fetched on this date) |
| Scope | PySide6 GUI only (CLI deliberately excluded) |
| Method | Static review of source code and project docs. The app was not run and no screenshots were available. |
| Audience | Maintainer, for later review and planning |

UI strings are Chinese. They are quoted as `"原文"` followed by an English translation in parentheses.

---

## 0. Basis and limits of this review

**Read in full or nearly in full**

- `README.md`, `docs/gui-usage.md`, `docs/architecture.md`, `docs/cli-gui-ux-review.md` (your own 1.7.x design guide, including the A/B/C scope and the 1.7.2 plan).
- `src/djhx_bilix/gui/app.py`, lines 1 to about 1000 of 1288. This covers every widget's construction, all four tab builders, input validation, busy/idle handling, retry/selection logic and the info/source/attempt detail views.

**Not read**

- The last ~290 lines of `app.py` (task-row event handling, progress text, completion messages, `_error`, close handling, QR dialog updates, `main()`), `worker.py`, `tasks.py`, tests, and any stylesheet. GitHub blocked raw-file access for these.
- Consequently, statements about progress text, completion feedback, error dialogs and styling are either marked **[Inferred]** or listed in section 7 for verification.

**Confidence tags used below**

| Tag | Meaning |
|---|---|
| **[Code]** | Confirmed directly in the source I read (function names are given so you can find it) |
| **[Docs]** | Taken from the project's own documentation |
| **[Inferred]** | Reasoned from code but needs a real screenshot or run to confirm |

**Severity** = effect on an ordinary user's ability to finish "paste a link, get a file". **Effort**: S = localized edit in one method, M = several methods or one new widget, L = restructuring or a backend contract change.

---

## 1. Executive summary

### Diagnosis

The interface mirrors the **internal task model** (Session → Source request → Batch → Task → Attempt → Snapshot) rather than the **user's mental model** (a video → downloading → done / failed). Everything the engine can do is on one page at once: input, options, run controls, three kinds of history, selection-scoped actions, and a detail dump. The result is a screen with 16 buttons, three nested views and four separate button rows, where the one thing most users want to do ("download this video") is not visually distinguished from the power-user features around it.

The engine, retry semantics and safety behavior are carefully designed and should be kept. The problem is almost entirely **presentation and flow**, which makes it fixable without touching the download core.

### Top findings

| # | Finding | ID | Severity |
|---|---|---|---|
| 1 | One scrolling Download page does three jobs (configure, monitor, manage history) | A1 | High |
| 2 | Tabs inside tabs, with three overlapping per-URL/per-task views and a shared text dump | A2, A4 | High |
| 3 | While anything runs, the URL box and all options are disabled, so a second link cannot be queued | B1 | High |
| 4 | "See what I'll get" is split across three controls, and episode selection lives in a bottom tab with two interacting selection mechanisms | B2 | High |
| 5 | Selection-dependent actions are far from the selection, and what "Retry selected" acts on depends on which inner tab is open | A3, B4 | Medium |
| 6 | Internal vocabulary and IDs (source, batch, attempt, CID, EP, request ID) are shown to ordinary users | C1 | Medium |
| 7 | Quality list shows numeric codes and unavailable choices; codec / audio / strict options have no plain-language guidance | C2, C3 | Medium |

### Recommended direction

Keep the engine and the task model. Change what the user sees:

1. **Make the first screen one task:** paste → see what will be downloaded → Download.
2. **Reduce the Download page to an "add area" plus a "download list".** Move IDs, attempts, batches, source records and conflict details behind a per-row **Details** view.
3. **Collapse Account / Settings / Diagnostics** into one Settings dialog and show login state in the main window.

Delivery is phased (section 6): Phase 1 is a set of small, low-risk edits to `app.py` that already remove much of the clutter; Phase 2 restructures the page; Phase 3 depends on backend work you have already scheduled (roadmap B-01 / B-02).

---

## 2. Current GUI map

### 2.1 Window and tabs **[Code]**

- Window title `BiliX {version}`. Minimum size 760×590 (clamped to screen), default 940×760. Status bar with "就绪" (Ready).
- Four top-level tabs:

| Tab | Content | Notes |
|---|---|---|
| "下载" (Download) | Everything about downloading, inside one `QScrollArea` | 16 buttons, 3 inner tabs, see 2.2 |
| "账号" (Account) | One status label + "扫码登录" (QR login), "查询状态" (check status), "退出登录" (log out) | Nearly empty page |
| "设置" (Settings) | Default download folder, FFmpeg path, config file path, "保存设置", "打开配置目录", long hint text | Two editable fields |
| "诊断" (Diagnostics) | One sentence, "运行诊断" (run diagnostics) button, read-only text box | Offline check |

### 2.2 The Download tab, top to bottom **[Code]**

```
┌ [ Download | Account | Settings | Diagnostics ] ──────────────────────────┐
│ ┌ Links / BV IDs, one per line ────────────────────────────────────────┐ │
│ │ [ text box, max height 100px ]                                       │ │
│ │ [Import URL file] [View info]                                        │ │
│ └──────────────────────────────────────────────────────────────────────┘ │
│ ┌ Download options ────────────────────────────────────────────────────┐ │
│ │ Save to  [......................] [Choose…]                          │ │
│ │ Quality  [Auto / highest available ▾]                                │ │
│ └──────────────────────────────────────────────────────────────────────┘ │
│ ☐ Advanced options  → (hidden) codec, audio, page rule, strict, overwrite  │
│ One-line summary of ALL options (always visible)                           │
│ [Start download] [Preview plan] [Retry all failed] [Cancel current op]     │
│ [Retry selected (orig params)] [Retry selected (current)] [Retry all canceled]
│ ┌ inner tabs: Info & parts | Source records | Session tasks ─────────────┐ │
│ │ (tree)         (tree)         (filter ▾, batch ▾, 4-column table)      │ │
│ │ min height 220px                                                       │ │
│ └────────────────────────────────────────────────────────────────────────┘ │
│ [ progress bar ............................. ] [Open output folder]        │
│ [Open file] [Copy path] [Clear completed] [Clear failed/canceled]          │
│ ┌ Info / attempt details / conflict preview ─────────────────────────────┐ │
│ │ [ read-only text box, max height 145px ]  [Copy selected source JSON]  │ │
│ └────────────────────────────────────────────────────────────────────────┘ │
└────────────────────────────────────────────────────────────────────────────┘
```

Control count on this page: **16 buttons**, 5 combo boxes, 3 checkboxes, 2 line edits, 1 multi-line input, 2 trees, 1 table, 1 read-only text box, 1 progress bar. With "Advanced options" collapsed, 15 buttons are still visible.

---

## 3. What already works well (keep these)

- **Sensible defaults.** Quality "Auto / highest available", audio AAC, no overwrite, no strict mode. A new user can download without touching any option.
- **Safe-by-default file handling.** Existing files are skipped, overwrite happens only after the new file is verified [Docs]. This is invisible when working correctly, which is the right outcome.
- **Good input validation messages.** Errors name the offending line: `第 N 行：…` (Line N: …) [Code, `_inputs`].
- **Confirmation where it matters.** "Retry with current parameters" lists the parameters first; log-out asks for confirmation; closing mid-download asks before stopping [Code, `_retry_ids`, `_logout`; Docs].
- **Offline account status on startup.** No network call just to display login state [Code, `_offline_account`].
- **Thoughtful platform work.** IME placeholder handling (`UrlInput`), `setTabChangesFocus`, high-DPI/small-screen clamping of the window size [Code].
- **Honest wording about limits.** "跳过（已存在，未校验）" (skipped: exists, not verified) rather than claiming success [Code, preview labels].
- **Correct retry semantics.** Per-task snapshots and identity checks [Docs]. The recommendations below change how retry is *presented*, not how it works.

---

## 4. Findings

Each finding lists evidence, the problem for the user, and a recommendation. IDs are referenced by the plan in section 6.

### A. Structure and layout

#### A1. One page does three jobs — **High** · [Code]
- **Evidence:** `_make_download_tab` places input, options, run controls, retry controls, three history views, progress, record actions and a detail box in a single vertical stack inside one `QScrollArea`.
- **Problem:** Configuring a new download, watching a running one and managing finished ones compete for the same space and attention. The primary path (paste → download) has no visual priority over retry/clear/copy-JSON features.
- **Recommendation:** Separate the page into an *add area* (top), a *download list* (main body) and a *details view* (on demand). See section 5.2. **Effort: L** for the full layout; Phase 1 reduces the clutter without restructuring.

#### A2. Tabs inside tabs, and overlapping views — **High** · [Code]
- **Evidence:** An outer `QTabWidget` (4 tabs) contains, on the Download tab, an inner `QTabWidget` with "信息与选集" (Info & parts), "来源记录" (Source records) and "会话任务" (Session tasks). Two of these are per-URL trees ("来源 / 可选选集" and "批次 / 来源").
- **Problem:** Nested tabs hide state. A user who clicks "查看信息" is switched to the first inner tab, and one who clicks "开始下载" is switched to the third; the middle one ("Source records") is a concept most users cannot name. Two trees describing the same URLs at different times (before vs after starting) look like duplicates.
- **Recommendation:** One tree/list: **source → parts**, with state per node, used before *and* after download starts. Remove the inner tab strip. Filtering ("All / Active / Failed / Done") becomes a segmented control with counts above the list. **Effort: M–L.**

#### A3. Actions are scattered over four rows and their scope is hidden — **Medium** · [Code]
- **Evidence:** Run row (Start / Preview / Retry all failed / Cancel), a second retry row, a progress row with "打开输出目录" (Open output folder), a record row with "打开文件" (Open file) / "复制路径" (Copy path) / two Clear buttons, and "复制选中来源 JSON" inside the detail box. `_selected_ids` returns task IDs only when inner tab index is 2 and source IDs only when it is 1.
- **Problem:** Actions that apply to *the selected row* sit far from the row, some actions that apply to "everything" sit next to them, and "Retry selected" silently changes target depending on which inner tab is open.
- **Recommendation:** Put selection-scoped actions on the row (hover buttons) and in a right-click menu: Open file, Open folder, Copy path, Retry, Remove, Details. Keep only global actions in a toolbar: Download all, Cancel, Clear finished. Never infer scope from the active tab. **Effort: M.**

#### A4. One text box shows five different things — **Medium** · [Code]
- **Evidence:** `info_text` (max height 145px) is reused by `_show_metadata`, `_show_source`, `_show_attempts`, `_show_batch`, and the preview path (`_start_download` with `dry_run` writes its first line there).
- **Problem:** What the box shows depends on what was clicked last, and it is not labelled accordingly (its group title lists three of the five). The output of "预览计划" (Preview plan), a primary user-triggered action, appears in a small box near the bottom of the page, far from the button. **[Inferred]** that per-item preview lines are appended to the same box; the event handler is in the part of the file I could not read.
- **Recommendation:** Show the plan where the user is looking: as a dialog or an inline panel listing each file with a New / Skip / Replace / Blocked badge and a "Start" button. Move metadata and attempt history into a Details view. **Effort: M.**

#### A5. Probable scroll-in-scroll and results below the fold — **Medium** · [Inferred]
- **Evidence:** The page is wrapped in a scroll area, and inside it the URL box, trees, table and info box each scroll independently. Minimum heights in code: history tabs ≥ 220px, jobs table ≥ 140px, tree ≥ 120px, plus URL box up to 100px, info box up to 145px, ~7 control rows and 9px spacing.
- **Problem:** By arithmetic the content likely exceeds the 590px minimum window height and probably the 760px default, so progress and result controls may be below the fold, and mouse-wheel scrolling can get captured by an inner widget.
- **Recommendation:** Verify with screenshots at 760×590 (section 7). The A1/A2 restructure removes the problem by design; a quick mitigation is to collapse the detail box by default.

#### A6. Four top-level tabs for three thin pages — **Low** · [Code]
- **Evidence:** Account (1 label, 3 buttons), Settings (2 fields), Diagnostics (1 button + text).
- **Recommendation:** Single Settings dialog (gear icon) with sections *Account*, *Downloads*, *About & diagnostics*. The main window then has no top-level tabs at all. **Effort: M.**

### B. Workflow

#### B1. The UI locks during any operation; a second link cannot be queued — **High** · [Code] / [Docs]
- **Evidence:** `_set_busy(True)` disables the URL box, folder, page rule, all three combos, both checkboxes and the info tree, plus every button created with the default `busy_sensitive=True`. The docs confirm: no append-while-running, no single-item cancel, no pause [Docs, `gui-usage.md`]. Already planned as B-01 in 1.7.2 [Docs].
- **Problem:** The natural behavior for a downloader is "keep pasting links while it works". Today the user waits for the whole batch, and a long batch blocks the entire app.
- **Recommendation:** This is the single biggest workflow gap. Until B-01 lands, at least keep the input and "add to next batch" enabled and show a clear "Waiting for current batch" state. When B-01 lands, the add area should never be disabled. **Effort: L (backend).**

#### B2. "Look before downloading" is split across three controls; part selection is hidden — **High** · [Code]
- **Evidence:**
  - "查看信息" (View info) fetches metadata and fills a tree *in an inner tab at the bottom of the page*; that tree holds the per-part checkboxes.
  - "预览计划" (Preview plan) computes outputs and conflicts and prints them in the text box.
  - "批量选集规则" (Batch part rule; "1,3,5-7", "all") is a text field in the hidden Advanced section.
  - In `_inputs`, checked parts from the tree *override* the text rule once info has been read, while editing the text rule resets the checkboxes (`_reset_part_checks`).
- **Problem:** Three controls all "look at" the URL, and the difference between the first two is not obvious. Parts can be chosen by two mechanisms that overwrite each other. If the user never clicks "查看信息", a multi-part video downloads **all** parts by default [Docs], and the summary line only says "按来源勾选 / 链接默认" (per source selection / link default), which does not tell them what will happen.
- **Recommendation:** Parse automatically on paste (debounced), show a result card with title, uploader, duration, part list with *Select all / none / invert*, and the actually available qualities. Make the text rule an optional advanced shortcut that updates the checkboxes in one direction only. "Preview plan" becomes a secondary action ("Preview files and conflicts") next to Download. For very long pasted lists, parse lazily and show "N links added" rather than fetching all at once. **Effort: M–L.**

#### B3. Fetched info is discarded on any edit of the URL box — **Medium** · [Code]
- **Evidence:** `self.urls_edit.textChanged.connect(self._invalidate_info)` clears `_metadata` and the info tree on every change, including adding a trailing newline or fixing whitespace.
- **Problem:** The user loses information they just waited for, and any later part selection with it.
- **Recommendation:** Compare the *normalized list of sources* before and after the edit and invalidate only entries that actually changed. **Effort: S.**

#### B4. Retry has four entry points; two are always enabled — **Medium** · [Code]
- **Evidence:** "重试全部失败" (Retry all failed) in the primary row, then "重试选中（原参数）" (Retry selected, original params), "重试选中（当前参数）" (… current params) and "重试全部取消" (Retry all canceled) on a second row. Only the first is created disabled (`retry_button.setEnabled(False)`); the others appear to stay enabled when nothing is failed or selected. **[Inferred]** that clicking them then shows an error dialog.
- **Problem:** The distinction "original vs current parameters" is an expert concept (it is correct and valuable, but not for the first-line control). Buttons that cannot do anything useful are enabled.
- **Recommendation:** One **Retry** button on the row (default: original parameters). Put *"Retry with current settings…"* in a drop-down on the same button or in the context menu, keeping the existing confirmation dialog. Provide "Retry all failed" as a toolbar action that is enabled only if failures exist. Keep canceled items retryable through the same row action. **Effort: S–M.**

#### B5. Row interactions are surprising — **Medium** · [Code]
- **Evidence:** `jobs_table.doubleClicked` is wired to `_open_selected_folder`. "打开输出目录" (Open output folder) is busy-sensitive and therefore disabled while a download is running, whereas "打开文件" and "复制路径" are not.
- **Problem:** Double-click on a finished download normally means "open it". Opening a folder is harmless during a download, yet the button is disabled while neighbours stay enabled, so enablement looks arbitrary.
- **Recommendation:** Double-click on a completed row opens the file; the row's folder icon opens the folder. Mark the open/copy actions as not busy-sensitive. **Effort: S.**

#### B6. Thin progress and cancel feedback — **Medium** · [Docs]
- **Evidence:** One global progress bar initialized as "等待任务" (waiting for tasks); indeterminate "准备批次…" (preparing batch) at start. No speed or time-remaining in the GUI, cancel applies to the whole batch, and the cancel button changes its label by operation ("取消整个批次" etc.) [Code]. Speed/ETA is planned as B-02 [Docs].
- **Problem:** Users cannot tell whether a slow download is progressing normally, and "cancel" does not mean "cancel this one".
- **Recommendation:** When B-02 lands, show per-row progress with speed and remaining time (only when estimable). Until then, show bytes done / total per row if available. Keep the cancel label fixed ("Cancel") and put the scope in a tooltip or confirmation. **Effort: M–L.**

#### B7. The save folder is set in two places — **Medium** · [Code]
- **Evidence:** "保存到" on the Download page and "默认下载目录" in Settings. `_output_edited` decides whether the Download page follows the saved default.
- **Problem:** A user who once edited the folder on the Download page and then changes the default in Settings sees no effect, with no explanation. The distinction (task override vs saved default) is a developer concept.
- **Recommendation:** One visible folder control on the main screen that remembers the last choice. Offer "Set as default" next to it if a separate default is still wanted. Environment-variable overrides can remain, but explain them only in Details. **Effort: S–M.**

#### B8. Login state is invisible where it matters — **Medium** · [Code] / [Inferred]
- **Evidence:** Login state exists only on the Account tab. The Download page shows no account state, and available qualities appear only in a text box after "查看信息".
- **Problem:** A user who is not logged in may silently get a lower quality than they expect (the engine downloads "the highest quality the *current account* can obtain" [Docs]) and has no hint that logging in could change that.
- **Recommendation:** Account chip in the header or status bar ("Not logged in" / "Logged in"). In the parse result, if the available list is limited, show a one-line hint with a "Log in" action. Word it carefully: availability depends on the video and account. **Effort: S–M.**

#### B9. No drag-and-drop, clipboard detection or keyboard shortcuts in the reviewed code — **Low** · [Code, within the portion read]
- **Evidence:** No `dragEnterEvent`, `QShortcut`, `setShortcut`, `setDefault` or mnemonic `&` in the first ~1000 lines.
- **Recommendation:** Add Ctrl+Enter = Download, drag-and-drop for links and `.txt` lists, optional "paste from clipboard" button or detection of a Bilibili link on window focus, and Enter on the primary action. **Effort: S.** (Re-check against the unread tail first.)

### C. Controls, labels and wording

#### C1. Internal vocabulary and IDs leak into the UI — **Medium** · [Code]
- **Evidence:** UI terms "来源" (source), "批次" (batch), "尝试" (attempt), "冲突预览" (conflict preview), "已结束批次汇总" (finished batch summaries). `_show_source` prints `来源 ID …`, `原来源 …`; `_show_attempts` prints `批次 {id}`, `类别 {error_code}`; `_show_metadata` prints BV, CID and EP.
- **Problem:** These are accurate for the engine and meaningless to most users.
- **Recommendation:** User-facing words: video, part, download, retry, "already exists". Keep IDs and attempt history in a Details view (collapsed or behind a "Technical details" section), plus a copy button for bug reports. **Effort: S–M.**

#### C2. The quality list shows numeric codes and unavailable choices — **Medium** · [Code]
- **Evidence:** `addItem(f"{QUALITY_NAMES[quality]} ({quality})", quality)` for every known quality, sorted descending; the value is the numeric code passed to `parse_quality`.
- **Problem:** The number in brackets means nothing to users, and the list does not change after a video is parsed, so users can pick a quality the video does not offer.
- **Recommendation:** Hide the codes (keep them in tooltips or Details). After parsing, populate or grey out the list from the available streams. Keep "Highest available" as the default. **Effort: S (hide codes), M (availability).**

#### C3. Codec, audio and strict mode need plain-language framing — **Medium** · [Code]
- **Evidence:** "编码" (codec): 自动 / AVC / HEVC / AV1. "音轨" (audio track): AAC / FLAC / Dolby / 最佳. Checkboxes "必须精确匹配画质 / 编码" (must exactly match quality/codec) and "校验成功后覆盖同名文件" (overwrite same-name files after verification).
- **Problem:** Most users cannot choose between AVC and AV1, and "strict matching" does not say what happens otherwise.
- **Recommendation:** Add short helper text and consider two presets: *Best compatibility* (AVC) and *Smaller files* (HEVC/AV1; may not play on older devices). Reword strict mode as "If the chosen quality isn't available, fail instead of using a lower one". Reword overwrite as "Replace the file if it already exists". Keep all raw options available under "More options". **Effort: S.**

#### C4. "Advanced options" is a checkbox, and the summary repeats defaults — **Low–Medium** · [Code]
- **Evidence:** `QCheckBox("高级选项")` shows and hides a group. `option_summary` always shows all six settings, defaults included, even when the same controls are visible right above it.
- **Problem:** A checkbox suggests "enable a feature", not "reveal more settings". The always-on summary adds a dense line of text while carrying little information when everything is default.
- **Recommendation:** Use a disclosure control (`▸ More options`). Show only **non-default** settings as chips or a badge (for example "Overwrite on", "Strict on", "2 parts"). This also matches the intent of your A-05 item (dangerous options stay visible when folded). **Effort: S.**

#### C5. Part-list details — **Low** · [Code]
- **Evidence:** Durations print as raw seconds (`f"{duration:.0f} 秒"`), each part row says "媒体待检查" (media not yet checked) with no way to check, and there is no select-all / select-none / invert control.
- **Recommendation:** Format as `h:mm:ss`, drop or explain the dead-end text (for example "Availability checked when download starts"), add select-all / none / invert, and optionally a search or range field for long lists. **Effort: S.**

#### C6. Visual hierarchy and polish — **Low** · [Code, within the portion read]
- **Evidence:** All buttons are plain `QPushButton`s; no default button or accent in the reviewed code. Group boxes frame most regions. The input box title ("视频链接 / BV 号（每行一个）") and its placeholder ("粘贴 … 每行一个") both say "one per line". The cancel button's label changes with the operation.
- **Recommendation:** Make **Download** the only emphasized button (default button, accent colour). Replace group-box frames with section labels and whitespace. Say "one per line" once. Keep a fixed Cancel label. **Effort: S.** (Re-check whether the unread tail applies a stylesheet.)

#### C7. Settings text exposes implementation details — **Low** · [Code]
- **Evidence:** `_load_settings_view` fills `settings_hint` with a three-line block: the effective download folder and FFmpeg, each followed by a "source" label, and a sentence saying that environment variables take priority and that path validity should be checked via Diagnostics. (The initial hint naming `BILIX_DOWNLOAD_DIR` / `BILIX_FFMPEG` is overwritten at startup, so users normally do not see those names. The wording of the source labels is defined in `config.py`, which I did not read.)
- **Problem:** "Effective value", "source" and "file value vs environment" are configuration-layer concepts. A user who only wants to change a folder has to read a paragraph to learn that an environment variable may override what they typed.
- **Recommendation:** Show the effective folder plainly. Show the source and the override explanation only when an override is actually active (for example "This folder is set by an environment variable"), or inside a collapsible "Details". On Windows, where FFmpeg is bundled [Docs], move the FFmpeg path under "Advanced". **Effort: S.**

### D. Implementation notes that affect a redesign

#### D1. Everything lives in one 1,288-line `MainWindow` — **Medium** · [Code]
- UI structure, event handling, selection logic and session wiring are in one class, and behavior is coupled to widget structure (for example `history_tabs.currentIndex() == 2`).
- **Recommendation:** Before restructuring, split into page/panel widgets (input panel, options panel, task list, details panel, settings dialog) with signals between them. Your own design guide already says to split progressively [Docs]. The repo has a GUI test profile (`gui-test` group); **[Inferred]** tests reference current widget names, so plan to update them or keep stable `objectName`s. **Effort: M.**

#### D2. Hard-coded Chinese strings — **Low / note only** · [Code]
- No translation hooks (`tr()`) seen. Irrelevant if the product stays Chinese-only. If an English UI is ever wanted, wrapping strings now is cheaper than later, especially during a restructure.

---

## 5. Proposed design direction

### 5.1 Principles

1. **One screen, one primary task.** Paste → see → Download.
2. **Show before committing.** The user sees what will be downloaded (title, parts, quality, folder) before pressing Download.
3. **Progressive disclosure.** Defaults first; "More options" for the rest; "Details" for IDs, attempts and plans.
4. **User vocabulary.** Video, part, download, retry. Engine terms stay in Details.
5. **Actions live next to their object.** Row-level actions on the row; global actions in a toolbar.
6. **Always-visible state.** Login, save folder and idle/busy status never require opening a tab.

### 5.2 Target layout (single window, no top-level tabs)

```
┌ BiliX ───────────────────────────────── [ Account: Logged in ▾ ]  [ ⚙ Settings ] ┐
│                                                                                   │
│  Paste Bilibili links or BV IDs (one per line) — parsed automatically             │
│  ┌─────────────────────────────────────────────────────────────────────────────┐ │
│  │                                                                             │ │
│  └─────────────────────────────────────────────────────────────────────────────┘ │
│  ┌ Result card ────────────────────────────────────────────────────────────────┐ │
│  │ Video title            Uploader · 1:02:33 · 12 parts                        │ │
│  │ Parts: [Select all] [None]   ☑ P1  ☑ P2  ☐ P3 …            (scrolls)        │ │
│  │ Quality [Highest available ▾]   Available: 1080P, 720P, 480P                │ │
│  │ (hint) Log in to see more qualities                                          │ │
│  └─────────────────────────────────────────────────────────────────────────────┘ │
│  Save to [ ......................... ] [Browse]   More options ▸    [ Download ]   │
│                                                                                   │
│  Downloads   [ All 5 ]  [ Active 1 ]  [ Failed 1 ]  [ Done 3 ]    [Clear finished]│
│  ┌─────────────────────────────────────────────────────────────────────────────┐ │
│  │ ▸ Video A      ███████░░░  72%   3.2 MB/s · 1 min left                 [✕]   │ │
│  │ ▸ Video B      Failed: network error         [Retry ▾] [Details]             │ │
│  │ ▸ Video C      Done · 480 MB        [Open] [Folder] [⋯]                      │ │
│  └─────────────────────────────────────────────────────────────────────────────┘ │
│  Ready · Free space 120 GB                                                        │
└───────────────────────────────────────────────────────────────────────────────────┘
```

Notes on this layout:

- The **result card** is the old "信息与选集" tree plus the quality list, shown where the user is already looking. It appears after paste (debounced) and disappears or turns into a list entry after Download.
- The **download list** replaces "来源记录" and "会话任务" with a single tree (source → parts). Everything in the old detail box moves to **Details** (a side panel or dialog opened from a row).
- **Retry ▾** is a split button: default = original parameters; menu item "Retry with current settings…" keeps the existing confirmation.
- **More options ▸** reveals codec, audio, strict, overwrite, and the text part rule. Non-default values appear as badges next to it when folded.
- **Preview files and conflicts** is a secondary action, available from a menu next to Download, and results open in a dialog or inline panel, not a bottom text box.
- The window does not need a 760×590 minimum, because the page is a short fixed region plus a list that scrolls.

### 5.3 Flow comparison (single multi-part video, 3 of 12 parts, 720P)

| Step | Today | Proposed |
|---|---|---|
| 1 | Paste the link | Paste the link (auto-parse) |
| 2 | Click "查看信息" | — |
| 3 | Find the first inner tab at the bottom, uncheck 9 parts one by one (or open Advanced and type `1-3`) | Click *None*, tick 3 parts (or type a range) |
| 4 | Check the folder (set in two places) | Check the folder (one place) |
| 5 | Pick quality from a list that may offer unavailable choices | Pick quality from the available list |
| 6 | Click "开始下载" | Click Download |
| 7 | Watch the third inner tab, bar at the bottom | Watch the row |
| 8 | Select the row, scroll down, click "打开文件" (or double-click and get a folder) | Double-click the row, or click **Open** |

Roughly eight steps with two hidden mechanisms become five steps on one screen.

### 5.4 Mapping from current controls to the proposed ones

| Current | Proposed |
|---|---|
| "查看信息" (View info) | Automatic parse on paste; a small "Refresh" action on the card |
| Inner tab "信息与选集" | Result card (before download) |
| Inner tab "来源记录" | Removed; failed sources appear as rows with a "Re-read" action |
| Inner tab "会话任务" + filter + batch combos | Download list with segmented filter and counts; batch summaries in Details |
| Info / attempts / conflict text box | Details panel; plan results in a Preview dialog |
| "重试全部失败", "重试选中（原参数）", "重试选中（当前参数）", "重试全部取消" | Row **Retry ▾** + toolbar "Retry failed" (enabled only if applicable) |
| "打开文件", "复制路径", "打开输出目录" | Row actions and context menu |
| "清理成功记录" / "清理失败 / 取消" | One "Clear finished" menu: Clear completed / Clear failed |
| "复制选中来源 JSON" | Details → "Copy diagnostic info" |
| "高级选项" checkbox | "More options ▸" disclosure with badges |
| Option summary line | Badges for non-default values only |
| Tabs "账号", "设置", "诊断" | Account chip in header + one Settings dialog |

### 5.5 Wording suggestions

| Current | Suggested | Reason |
|---|---|---|
| "查看信息" (View info) | "解析链接" (Parse link), or automatic | Says what happens |
| "预览计划" (Preview plan) | "预览文件与冲突" (Preview files and conflicts) | "Plan" is jargon |
| "高级选项" (Advanced options) | "更多选项" (More options) | Less intimidating |
| "批量选集规则" (Batch part rule) | "只下载部分选集" (Download only some parts) | Task-oriented |
| "必须精确匹配画质 / 编码" | "找不到所选画质时不下载" (Don't download if the chosen quality isn't available) | States the consequence |
| "校验成功后覆盖同名文件" | "文件已存在时替换" (Replace if the file exists) | Verification is an implementation detail |
| "编码" (Codec) | "视频编码" + hint: AVC = most compatible; HEVC / AV1 = smaller, may not play everywhere | Helps the choice |
| "音轨" (Audio track) | "音频" (Audio) | Shorter |
| "会话任务" (Session tasks) | "下载列表" (Downloads) | User term |
| "来源记录" (Source records) | (removed) | Internal concept |
| "取消当前操作" / "取消整个批次" | "取消" (fixed label; scope in tooltip) | Stable button |
| "清理成功记录" | "清除已完成" (Clear completed) | Plain |

### 5.6 Settings consolidation

One **Settings** dialog, opened from a gear icon:

- **Account:** state (logged in / not), "QR login", "Log out", "Check status".
- **Downloads:** default folder, default quality (so users do not re-pick it each time). FFmpeg path under "Advanced", visible mainly on Linux.
- **About & diagnostics:** version, "Run diagnostics", "Open config folder", with environment-variable overrides shown only here.

### 5.7 Empty, loading and error states

- **Empty list:** a short message and one example ("Paste a Bilibili link above to start").
- **Parsing:** inline spinner on the card; per-source error with "Retry parse" instead of text in a narrow column.
- **Needs login / member-only:** a plain-language message and a "Log in" button at the point of failure.
- **Failure rows:** one-line safe message, **Retry**, **Details**. Keep your existing rule of never showing third-party exception text [Docs].

---

## 6. Phased plan

### Phase 1 — Quick wins (mostly localized edits in `app.py`; no model or worker changes)

| Item | Finding | Effort | Impact |
|---|---|---|---|
| Make **Start download** the default/emphasized button; fixed Cancel label | C6 | S | Medium |
| "More options ▸" disclosure; badges for non-default values only | C4 | S | Medium |
| Hide numeric quality codes; durations as `h:mm:ss` | C2, C5 | S | Medium |
| Select all / none / invert for part checkboxes | C5 | S | Medium |
| Only invalidate info for URLs that actually changed | B3 | S | Medium |
| Double-click opens the file; open/copy actions not busy-sensitive | B5 | S | Medium |
| Enable/disable retry and clear buttons by real state | B4 | S | Low–Medium |
| Plain-language option labels and helper text (section 5.5) | C3 | S | Medium |
| Account chip in status bar (offline state already available) | B8 | S | Medium |
| Hide IDs/attempt data under a "Technical details" toggle | C1 | S–M | Medium |
| Show override/source text in Settings only when an override is active | C7 | S | Low |
| Shortcuts (Ctrl+Enter), drag-and-drop of links and `.txt` | B9 | S | Low–Medium |
| Move Preview output to a dialog rather than the bottom text box | A4 | M | Medium |

### Phase 2 — Restructure the Download page (UI-only, larger)

| Item | Finding | Effort | Impact |
|---|---|---|---|
| Split `MainWindow` into panel widgets, stabilize `objectName`s, update GUI tests | D1 | M | Enabler |
| Auto-parse on paste (debounced) and the result card | B2 | M–L | **High** |
| Single source → parts list replacing both trees and the inner tab strip | A2 | M–L | **High** |
| Row-level actions and right-click menu; single **Retry ▾** | A3, B4 | M | High |
| Details panel replacing the multi-purpose text box | A4, C1 | M | Medium |
| One Settings dialog replacing three tabs; single folder control | A6, B7 | M | Medium |
| Quality list from available streams, with login hint | C2, B8 | M | Medium |

### Phase 3 — Needs backend work already on your roadmap

| Item | Finding | Roadmap | Effort | Impact |
|---|---|---|---|---|
| Add links while a batch is running; per-item cancel and remove | B1 | B-01 | L | **High** |
| Speed and time remaining per row | B6 | B-02 | M–L | High |
| Remember last-used folder / quality / window state | B7 | B-07 (GUI preferences) | M | Medium |

**Suggested order:** Phase 1 first (cheap, visible, no regressions in the task model), then Phase 2's `MainWindow` split and result card, then the list/Details restructure. Take Phase 3 items as the backend allows, and design the Phase 2 list so it can show queued/active/added-later items without redesign.

### Risks and constraints

- **Semantics must not be lost.** Your design guide fixes precise rules (retry from the failed attempt's snapshot, identity checks, "skip means unverified"). Simplifying wording is fine, but keep the confirmation for "current settings" retry and the "not verified" caveat on skipped files, perhaps in tooltips or Details.
- **Acceptance evidence.** GUI changes will invalidate parts of the 1.7.1 desktop validation (DPI, IME, small screen, keyboard). Budget a re-run for each phase.
- **Auto-parse costs network requests.** Debounce, parse lazily for long lists, respect cancellation, and make the account-change invalidation rules from A-02 apply to the card.

---

## 7. Things to verify (I could not do these)

1. **Screenshots** at 760×590, 940×760 and 1366×768, each at 100 %, 150 % and 200 % scaling: does the Download page scroll, and where do progress and open/retry controls fall? (A5)
2. **Read the unread tail of `app.py`** (`_on_event` for tasks, progress text, `_on_done`, `_error`, `closeEvent`, `main()`): confirm where preview output goes, what the progress bar and status bar show during and after a batch, whether errors are modal dialogs, and whether a stylesheet is applied. (A4, B6, C6)
3. **Check the button states** with an empty session: which retry/clear buttons are enabled, and what happens when clicked. (B4)
4. **Try a long multi-part video** (for example 50+ parts) and a pasted list of 20+ links: how usable is part selection and the tree? (B2, C5)
5. **Run a short moderated test** with three to five people unfamiliar with BiliX. Suggested tasks:
   - Download one video at 720P to the Desktop.
   - Download only parts 2–4 of a multi-part video.
   - Retry a failed download.
   - Find and play the downloaded file.
   - Work out why a higher quality is not offered.

   Record time to completion, wrong clicks, and which labels they misread.

---

## 8. Appendix: control inventory of the Download tab

| Region | Controls | Scope | Notes |
|---|---|---|---|
| Input | Multi-line URL box (max 100px); "导入 URL 文件"; "查看信息" | New work | Title and placeholder both say "one per line" |
| Options | "保存到" + "选择…"; Quality combo | New work | Quality shows numeric codes; list not tied to the video |
| Advanced (hidden) | Codec combo; Audio combo; Part-rule text; Strict checkbox; Overwrite checkbox | New work | Toggled by a checkbox |
| Summary | One-line label of all six settings | — | Always visible, defaults included |
| Primary actions | "开始下载"; "预览计划"; "重试全部失败"; "取消当前操作" | Mixed (new / history / running) | Retry sits beside Start |
| Retry row | "重试选中（原参数）"; "重试选中（当前参数）"; "重试全部取消" | History | Target depends on active inner tab |
| Inner tab 1 | "信息与选集" tree with part checkboxes | Per source | Disabled while busy |
| Inner tab 2 | "来源记录" tree | Per source request | Internal concept |
| Inner tab 3 | Filter combo; batch-summary combo; 4-column table ("视频 / 选集", "状态", "进度", "文件 / 说明") | Per task | Double-click opens the folder |
| Progress row | Global progress bar; "打开输出目录" | Running / selected | Open-folder button is disabled while busy |
| Record row | "打开文件"; "复制路径"; "清理成功记录"; "清理失败 / 取消" | Selected / history | Clear actions only when idle |
| Detail box | Read-only text (max 145px); "复制选中来源 JSON" | Whatever was clicked last | Shows IDs, attempts, plans, descriptions |

Sources for this review: `README.md`, `docs/gui-usage.md`, `docs/architecture.md`, `docs/cli-gui-ux-review.md`, and `src/djhx_bilix/gui/app.py` (first ~1000 lines) in `github.com/Koril33/bilix`.
