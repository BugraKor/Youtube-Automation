# Roadmap: Self-Optimizing Viral Psychology Media Company

Goal: fastest possible monetization (1,000 subs + 10M Shorts views in 90 days),
maximum retention, maximum subscriber conversion, full automation scalability.
The existing architecture (Gemini content → images/stock video → TTS → FFmpeg
render → YouTube upload, 2x daily via GitHub Actions) is kept intact; each
phase layers on top of it.

Legend: ✅ implemented · 🔜 next up · 🗺️ planned

---

## Phase 1 — Viral Topic Engine ✅

- New default niche `viral-psychology` (config `CONTENT_THEME`): attraction,
  dark psychology, brain science, emotions, relationships, cognitive biases,
  habits, social behavior, self-improvement — for a 16-35 English-speaking
  Shorts audience.
- 18 psychology-specific viral formats + 9 subject categories × 5 seeds,
  rotated with the existing category cooldown.
- Every topic candidate is scored by the LLM: Virality, Retention, Emotional
  Impact, Monetization (0-100). Candidates below the gates
  (`MIN_VIRALITY_SCORE=85`, `MIN_EMOTIONAL_IMPACT=80`, retention ≥75,
  monetization ≥70) are rejected and regenerated (up to `TOPIC_ATTEMPTS=3`;
  best candidate kept as fallback so a run never fails).

## Phase 2 — Hook Engine ✅

- `generate_hooks()` produces 5 competing hooks per topic, each with a
  predicted CTR-style quality score (strict rubric; only irresistible hooks
  score 90+).
- The highest-scoring hook is injected into the script as Scene 1's narration.
- Gate: `MIN_HOOK_SCORE=90` (logged against every selection).

## Phase 3 — High-Retention Script Engine ✅

- 20-35 second scripts with the retention timeline baked into the prompt:
  0-2s extreme curiosity → 2-8s emotional connection ("this is literally
  you") → 8-18s explanation → 18-25s twist → ending question/shock.
- Short sentences, fast pacing, emotional language, loop-back ending,
  comment-bait detail (all preserved from the previous strategy work).
- `predict_retention()` scores each script per time segment (0-3s, 3-10s,
  10-20s, 20-35s); scripts averaging below `MIN_RETENTION_PREDICTION=75%`
  are regenerated (`SCRIPT_ATTEMPTS=2`, best kept).

## Phase 4 — Visual Engine ✅ (partial)

- Psychology theme switches image prompts to ultra-realistic cinematic
  photography with **emotional human subjects**, movie-quality dramatic
  lighting, moody atmosphere, 9:16.
- Default scene count raised to 5 (`SCENES_PER_VIDEO`); every scene must
  differ dramatically in scale/palette/angle (stimulus density rule).
- 🗺️ Remaining: per-scene visual scoring (emotional impact / curiosity /
  clickability) with regeneration of weak frames; 10-scene mode for 30-35s
  videos.

## Phase 5 — Thumbnail Engine 🗺️

- Shorts are feed-driven, so thumbnails matter mainly for channel-page and
  search surfaces (and are critical for Phase 9 long-form).
- Plan: generate 3 thumbnail concepts per video (text overlay + emotional
  face close-up), LLM-evaluate curiosity/fear/attraction/CTR, render the
  winner with Pillow, set via `youtube.thumbnails().set()` (needs no new
  scopes beyond upload).

## Phase 6 — Competitor Engine 🗺️

- Analyze top psychology Shorts channels (Psych2Go, Charisma on Command,
  HealthyGamerGG, BRAINY DOSE …): titles, hooks, upload frequency, duration.
- Plan: nightly job pulls each channel's latest uploads via YouTube Data API
  (public, `YOUTUBE_API_KEY` — already wired), feeds top performers' titles
  into the topic prompt as style exemplars, and stores learned patterns in
  `output/competitor_patterns.json`.

## Phase 7 — Trend Engine 🗺️

- Sources: YouTube trending (Data API `mostPopular`), Google Trends
  (pytrends), Reddit r/psychology + r/askpsychology (public JSON API),
  TikTok Creative Center.
- Plan: a `trends` CLI command scores emerging topics with the Phase 1 gate
  and inserts qualifying ones at the front of the generation queue.

## Phase 8 — Self-Improvement Loop ✅ (foundation)

- Every generated topic is recorded with its category/format in
  `output/performance.json`; uploads attach the video id.
- `python -m ai_shorts_factory optimize` (now also a CI step after each
  publish) refreshes public views/likes/comments via `YOUTUBE_API_KEY` and
  prints winning patterns, e.g. `attraction: avg 4,200 views (+60% vs
  channel avg)`.
- Learned category weights (0.5x-3x) bias future topic selection toward
  winners automatically — the channel doubles down on what works with zero
  manual input.
- State persists across CI runs via a rolling GitHub Actions cache.
- 🗺️ Remaining: retention-curve level learning via YouTube Analytics API
  (needs `yt-analytics.readonly` OAuth scope — one-time re-auth).

## Phase 9 — Long-Form Expansion ✅ (detection) / 🗺️ (generation)

- `optimize` reports every Short crossing 1,000 / 5,000 / 10,000 views with
  the recommended long-form target (5 / 8 / 10 minutes).
- 🗺️ Remaining: `expand <video_id>` command that generates a chaptered
  long-form script from the winning topic, renders with the existing
  pipeline at 16:9, and uploads as a regular video (higher RPM than Shorts —
  the fastest monetization lever once topics are proven).

## Phase 10 — Multi-Platform Distribution 🗺️

- The rendered `final.mp4` is already platform-agnostic (9:16, burned-in
  captions, no YouTube-specific elements).
- Plan: post-render step exports per-platform metadata
  (`tiktok.json`, `reels.json`) with platform-native hashtags; publish via
  Meta Graph API (Reels) and TikTok Content Posting API once those
  credentials are provisioned.

---

## Quality gates (enforced, configurable via env)

| Gate                      | Env var                    | Default |
|---------------------------|----------------------------|---------|
| Virality score            | `MIN_VIRALITY_SCORE`       | 85      |
| Hook quality              | `MIN_HOOK_SCORE`           | 90      |
| Retention prediction      | `MIN_RETENTION_PREDICTION` | 75      |
| Emotional impact          | `MIN_EMOTIONAL_IMPACT`     | 80      |
| CTR / monetization        | `MIN_CTR_PREDICTION`       | 70      |
| Master switch             | `QUALITY_GATES`            | true    |

## Priority order

1. **Fastest growth** — Phases 1-3 gates live now; Phase 7 trends next.
2. **Highest retention** — Phase 3 retention gate + Phase 4 visual scoring.
3. **Subscriber conversion** — loop endings + pinned debate comments (live);
   Phase 6 competitor patterns.
4. **Fastest monetization** — Phase 9 long-form expansion of proven winners
   (highest RPM), Phase 5 thumbnails for long-form CTR.
5. **Automation scalability** — Phase 10 multi-platform, all state in
   `output/*.json` so additional channels are a config change away.

## Setup needed from the channel owner

- `YOUTUBE_API_KEY` secret (plain Data API v3 key, public stats only) to
  activate the self-improvement loop. Everything else runs with existing
  secrets; without the key the loop skips gracefully.
