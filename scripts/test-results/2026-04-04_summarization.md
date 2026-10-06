# Test Results: Summarization Prompts (2026-04-04)

## Test Matrix: 3 Prompts x 4 Presets x 5 Iterations = 60 Responses
Model: Qwen3.5-2B (local, via Wingman AI Core)

---

## PROMPT 1: condense-conversation (Fact Extraction from Chat)

### Preset: Precise (temp=0.1, top_p=1.0)

**Response 1** (190 tokens, 3.2s):
> * User asks about best ship for solo bounty hunting
> * Assistant recommends Aegis Vanguard Warden as top choice for solo work
> * Assistant notes Drake Cutlass Black is affordable alternative with decent combat and cargo space
> * User shares experience of dying to Hammerheads while flying Cutlass Black
> * Assistant advises using hit-and-run tactics against Hammerheads
> * Suggests focusing on hit-and-run attacks with fast approach and shield-face unload
> * Recommends boosting away before turrets track the pilot
> * Advises targeting engines to reduce Hammerhead mobility
> * Mentions upgrading to Size 3 gimballed weapons for better sustained DPS
> * User plans group bounty night on Saturday, considering saving Hammerheads for that event
> * Assistant confirms group bounty night is a smart plan
> * Suggests coordinating shield-face attacks with wing of 3-4 fighters
> * Recommends having someone fly ERT-capable ship to pull contracts

Word count: ~119

**Response 2** (189 tokens, 2.7s): Nearly identical to R1. Difference: "possibly saving" vs "considering saving". Word count: ~118

**Response 3** (198 tokens, 2.8s): More detailed -- includes "heavy forward firepower, strong shields, and good range" for the Vanguard. Word count: ~122

**Response 4** (181 tokens, 5.0s): Slightly more compressed, fewer bullets (11 vs 13). Word count: ~113

**Response 5** (197 tokens, 6.4s): Very close to R1/R2 with minor phrasing variations. Word count: ~120

**Ratings:**
- Coherence: 5/5 -- All responses are clear, well-structured bullet lists
- Task Completion: 4/5 -- All facts captured; some responses split "hit-and-run" into redundant sub-bullets
- Quality: 4/5 -- Consistent and reliable, minor redundancy issue

### Preset: Balanced (temp=0.3, top_p=1.0)

**Response 1** (173 tokens, 7.8s): 11 bullets, concise. Minor error: "Recommend boosting to engines" (should be "aiming for engines"). Word count: ~112

**Response 2** (185 tokens, 7.3s): Uses paragraph-style bullets instead of atomic facts. Last bullet invents detail ("did not provide specific details on the ERT ship type" -- meta-commentary that violates prompt rules). Word count: ~120

**Response 3** (196 tokens, 6.4s): Good structure with categorized suggestions. Word count: ~118

**Response 4** (225 tokens, 11.0s): Most verbose. Uses asterisk-dot format. Well-organized. Word count: ~140

**Response 5** (178 tokens, 9.3s): Clean, concise. Word count: ~112

**Ratings:**
- Coherence: 4.5/5 -- Mostly clear; R2 has a rule violation
- Task Completion: 4/5 -- R2 adds meta-commentary (violates rules); R1 has a minor factual distortion
- Quality: 3.5/5 -- Less consistent than Precise; one clear rule violation

### Preset: Creative (temp=0.8, top_p=0.9)

**Response 1** (139 tokens, 13.2s): Very compressed (only 4 bullets). Merges multiple facts per bullet. Word count: ~85

**Response 2** (126 tokens, 12.8s): Changes bullet format entirely -- drops "User/Assistant" framing, uses topic headers. Word count: ~82

**Response 3** (147 tokens, 12.9s): Uses dashes instead of asterisks. Reasonable coverage. Word count: ~95

**Response 4** (219 tokens, 18.2s): Good detail but uses bold markdown formatting not requested. "User plans to fly Hammerheads" is factually wrong (user plans to FIGHT them in a group). Word count: ~135

**Response 5** (221 tokens, 18.6s): Adds markdown headers. Misses hit-and-run detail bullets. Word count: ~130

**Ratings:**
- Coherence: 3.5/5 -- R4 has a factual error; R5 adds unwanted structure
- Task Completion: 3/5 -- R1/R2 are too compressed, missing details. R4 introduces a hallucination
- Quality: 3/5 -- High variance in format and accuracy

### Preset: Adventurous (temp=1.2, top_p=0.85)

**Response 1** (207 tokens, 14.4s): Uses bold headers and markdown. Adds invented details ("armor and shield capabilities" for Hammerheads -- not in source). Word count: ~120

**Response 2** (230 tokens, 17.8s): Adds meta-commentary bullets ("Assistant Role Function: Assistant provides tactical guidance..."). Invents fabricated inference. Word count: ~145

**Response 3** (268 tokens, 17.4s): Uses paragraph-style prose instead of concise bullets. Word count: ~160

**Response 4** (197 tokens, 6.2s): Good quality, concise, accurate. Best of this preset group. Word count: ~124

**Response 5** (248 tokens, 13.0s): Uses bold markdown headers. Adds fabricated framing. "Organizing a group event on Saturday for solo pilots" -- inaccurate. Word count: ~140

**Ratings:**
- Coherence: 3/5 -- Multiple hallucinations and invented details
- Task Completion: 2.5/5 -- Rule violations, hallucinations, inconsistent format
- Quality: 2.5/5 -- High variance; only R4 is genuinely good

### Preset Comparison:
| Preset | Coherence | Task Completion | Quality | Avg Tokens | Avg Time |
|--------|-----------|-----------------|---------|------------|----------|
| Precise | 5.0 | 4.0 | 4.0 | 191 | 4.0s |
| Balanced | 4.5 | 4.0 | 3.5 | 191 | 8.4s |
| Creative | 3.5 | 3.0 | 3.0 | 170 | 15.1s |
| Adventurous | 3.0 | 2.5 | 2.5 | 230 | 13.8s |

**Best preset: Precise (temp=0.1)** -- Fact extraction is deterministic; low temperature = most consistent, zero hallucinations.

---

## PROMPT 2: support-default (Text Summarization)

### Preset: Precise (temp=0.1, top_p=1.0)

**Response 1** (110 tokens, 7.9s): Nearly verbatim copy of input. Word count: ~84
**Response 2** (92 tokens, 4.0s): Good compression, preserves all key facts. Word count: ~66
**Response 3** (89 tokens, 5.1s): Most concise. Slight info loss. Word count: ~62
**Response 4** (109 tokens, 8.0s): Near-verbatim again. Word count: ~82
**Response 5** (106 tokens, 4.5s): Drops "plant" from "power plant". Word count: ~78

**Ratings:** Coherence: 5/5 | Task Completion: 3.5/5 | Quality: 3.5/5

### Preset: Balanced (temp=0.3, top_p=1.0)

**Response 1** (102 tokens, 7.3s): Good compression. Word count: ~75
**Response 2** (118 tokens, 6.3s): Nearly verbatim -- not a summary. Word count: ~90
**Response 3** (101 tokens, 8.2s): Good balance. Word count: ~72
**Response 4** (105 tokens, 8.6s): Well-structured. Word count: ~78
**Response 5** (103 tokens, 6.3s): Good. Word count: ~77

**Ratings:** Coherence: 5/5 | Task Completion: 3.5/5 | Quality: 4/5

### Preset: Creative (temp=0.8, top_p=0.9)

**Response 1** (59 tokens, 4.1s): Very concise but drops details. Word count: ~43
**Response 2** (81 tokens, 6.5s): Good balance but slightly awkward. Word count: ~58
**Response 3** (119 tokens, 9.2s): Essentially verbatim. Word count: ~90
**Response 4** (83 tokens, 5.4s): Good summary. Word count: ~60
**Response 5** (69 tokens, 3.9s): Good compression. Minor distortion. Word count: ~49

**Ratings:** Coherence: 4.5/5 | Task Completion: 3.5/5 | Quality: 3.5/5

### Preset: Adventurous (temp=1.2, top_p=0.85)

**Response 1** (74 tokens, 5.8s): Good. Word count: ~56
**Response 2** (104 tokens, 5.0s): Good. Word count: ~77
**Response 3** (59 tokens, 4.2s): Redundant phrasing. Word count: ~42
**Response 4** (88 tokens, 3.8s): Good. Minor misrepresentation. Word count: ~63
**Response 5** (88 tokens, 3.6s): Solid. Word count: ~64

**Ratings:** Coherence: 4/5 | Task Completion: 4/5 | Quality: 3.5/5

**Best preset: Balanced (temp=0.3)** -- Best consistency with reasonable compression.

---

## PROMPT 3: support-tool-response (Structured Data Summarization)

### Preset: Precise (temp=0.1, top_p=1.0)

**Response 1** (347 tokens, 14.8s): BROKEN JSON output. Invents calculations. Word count: ~100
**Response 2** (264 tokens, 8.2s): Clean markdown but invents "$96 x $3,250,000 = $312,000,000". Word count: ~100
**Response 3** (189 tokens, 5.8s): Excellent. Clean, accurate, no invented data. Word count: ~80
**Response 4** (229 tokens, 4.9s): Good table format. Minor currency error. Word count: ~95
**Response 5** (223 tokens, 3.9s): Similar to R4. Word count: ~93

**Ratings:** Coherence: 3/5 | Task Completion: 3/5 | Quality: 3/5

### Preset: Balanced (temp=0.3, top_p=1.0)

**Response 1** (213 tokens, 3.7s): Good. Fabricated "Aureus Price" term. Word count: ~90
**Response 2** (218 tokens, 3.3s): Good formatting. Word count: ~95
**Response 3** (312 tokens, 5.4s): CATASTROPHIC -- fabricated meta-JSON. Word count: ~60 real
**Response 4** (197 tokens, 3.6s): Good bullets. Meta-commentary violation. Word count: ~90
**Response 5** (205 tokens, 3.7s): Clean bullets. Wrong "per unit" label. Word count: ~90

**Ratings:** Coherence: 3/5 | Task Completion: 3/5 | Quality: 3/5

### Preset: Creative (temp=0.8, top_p=0.9)

**Response 1** (225 tokens, 3.8s): Good but invents weapon counts. Word count: ~95
**Response 2** (262 tokens, 4.4s): Confusing personnel description. Word count: ~100
**Response 3** (3369 tokens, 58.6s): **CATASTROPHIC** -- infinite JSON repetition loop. Word count: ~2500+ hallucination
**Response 4** (191 tokens, 3.0s): Clean and accurate. Best of set. Word count: ~85
**Response 5** (558 tokens, 9.4s): Fabricated meta-JSON. Word count: ~200+

**Ratings:** Coherence: 2/5 | Task Completion: 2/5 | Quality: 2/5

### Preset: Adventurous (temp=1.2, top_p=0.85)

**Response 1** (189 tokens, 3.2s): Good. Word count: ~85
**Response 2** (445 tokens, 7.4s): Fabricated notes and summaries. Word count: ~180
**Response 3** (215 tokens, 3.8s): Wrong computed numbers. Word count: ~100
**Response 4** (365 tokens, 6.7s): Broken formatting. Word count: ~150
**Response 5** (203 tokens, 3.5s): Clean and accurate. Word count: ~90

**Ratings:** Coherence: 2.5/5 | Task Completion: 2.5/5 | Quality: 2.5/5

**Best preset: Precise or Balanced (temp 0.1-0.3)** -- Even those hallucinate computed values. CRITICAL BUG: degenerate repetition loop at temp >= 0.8.
