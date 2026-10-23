# Test Results: Structured Output Prompts (2026-04-04)

## Test Matrix: 3 Prompts x 4 Presets x 5 Iterations = 60 Responses
Model: Qwen3.5-2B (local, via Wingman AI Core)

---

## PROMPT 1: extract-memories

### Preset: Precise (temp=0.1, top_p=1.0) -- Avg 5.2s

All 5 responses produce valid JSON with summary + facts array. Consistent structure.

**Common issues across ALL responses:**
- Confuse "12 million aUEC" (currency) with "12 million SCU" or "12 million laranite"
- R1 includes trade route profit (violates "Do NOT include game mechanics")
- R1 says "User plans to join" when user already JOINED
- Marcus (named friend) frequently omitted from facts
- JSON is pretty-printed, not "compact single line" as instructed

**Ratings:** Coherence: 4/5 | Task Completion: 3/5 | Quality: 3/5

### Preset: Balanced (temp=0.3, top_p=1.0) -- Avg 7.3s

More variation but MORE rule violations than Precise.
- R2, R3, R5 include trade prices (game mechanics, explicitly forbidden)
- R4 includes per-run profit calculations
- R5 misspells "laranite" as "Loranite"

**Ratings:** Coherence: 4/5 | Task Completion: 2.5/5 | Quality: 2.5/5

### Preset: Creative (temp=0.8, top_p=0.9) -- Avg 14.1s

- R3 is the ONLY response across ALL presets that correctly says "12 million aUEC"
- R4 summarizes what the assistant did (rule violation)
- R5 has contradictory tense: "intends to join...last week"
- ~3x slower than Precise

**Ratings:** Coherence: 3.5/5 | Task Completion: 2/5 | Quality: 2/5

### Preset: Adventurous (temp=1.2, top_p=0.85) -- Avg 7.2s

- R1 hallucinates "purchase Idris units" (Idris is a ship, not tradeable)
- R1 says "purchased the C2 Hercules" (user already owned it)
- R5 only has 2 facts (target is 5)
- Fact quality degrades: "Idris is an investment target worth saving for" (too vague)

**Ratings:** Coherence: 3/5 | Task Completion: 2/5 | Quality: 2/5

**Best preset: Precise (0.1/1.0)** -- Structured extraction needs low temperature.

---

## PROMPT 2: radio-chatter

### ALL PRESETS: 90% JSON Failure Rate

**JSON validity across all 20 responses: 2/20 (10%)**

| Preset | Valid JSON | Notes |
|--------|-----------|-------|
| Precise (0.1) | 0/5 | All have structural issues |
| Balanced (0.3) | 0/5 | Double braces, missing commas |
| Creative (0.8) | 1/5 | R3 is valid and good |
| Adventurous (1.2) | 1/5 | R5 is valid and good |

**Root cause: The `{{` double-brace syntax in the prompt example is literally copied by the model.** This is almost certainly a Python f-string escape that wasn't unescaped. The model also loses track of object structure after the first 2-3 entries, dropping the `"user"` field.

**Content quality (when ignoring JSON issues):**
- Radio chatter content is thematically appropriate across all presets
- 3 distinct participants maintained in ~60% of responses
- 5-message count followed in ~70% of responses
- Creative and Adventurous produce more varied/interesting dialog

**Verdict: This is a code bug, not a prompt or preset issue.** Fix `{{`/`}}` to `{`/`}` first, then retest.

---

## PROMPT 3: tts-test-praise

### Preset: Precise (temp=0.1, top_p=1.0) -- Avg 1.2s

| # | Tokens | Response (truncated) |
|---|--------|---------------------|
| 1 | 64 | "Wingman AI just walked into my kitchen and started singing 'I'm the Man'..." |
| 2 | 59 | "Wingman AI just walked into my kitchen and started singing 'I'm the Man'..." |
| 3 | 51 | "Wingman AI just walked into my kitchen and started singing 'I'm the Man'..." |
| 4 | 62 | "Wingman AI just walked into my kitchen and convinced my cat..." |
| 5 | 52 | "Wingman AI just walked into my kitchen and started singing 'I'm the Man'..." |

**4/5 start with "Wingman AI just walked into my kitchen"** -- near-zero diversity.
- Coherence: 3/5 | Humor: 1.5/5 | TTS Suitability: 1/5 (all 50-64 tokens, way too long)

### Preset: Balanced (temp=0.3, top_p=1.0) -- Avg 2.5s

All 48-71 tokens. Themes: toasters, cats, kitchens. Run-on sentences. Not funny.
- Coherence: 3/5 | Humor: 2/5 | TTS Suitability: 1/5

### Preset: Creative (temp=0.8, top_p=0.9) -- Avg 1.7s

More varied. Some clever phrases ("flavor profile of my own regrets"). Still mostly too long (41-78 tokens).
R2 and R5 are closest to usable length.
- Coherence: 3.5/5 | Humor: 2.5/5 | TTS Suitability: 2/5

### Preset: Adventurous (temp=1.2, top_p=0.85) -- Avg 1.5s

Best length range (30-62 tokens). Most stylistic variety. R3 violates "No quotes" rule.
R5 is a question ("Does my Wingman AI have eyes the size of two pomegranates...?") -- actually works well for TTS.
- Coherence: 3/5 | Humor: 2.5/5 | TTS Suitability: 3/5

### Preset Comparison:
| Preset | Avg Tokens | Variety | Humor | TTS Length |
|--------|-----------|---------|-------|-----------|
| Precise | 58 | Very Low | 1.5/5 | Too long |
| Balanced | 59 | Low | 2/5 | Too long |
| Creative | 53 | Medium | 2.5/5 | Borderline |
| Adventurous | 48 | High | 2.5/5 | Best range |

**Best preset: Adventurous (1.2/0.85)** for this creative short-form task.

**Critical issues:**
- "One short funny sentence" is not specific enough -- model produces 30-78 tokens
- Model fixates on kitchens, toasters, and cats
- Run-on sentences are the norm
- Random-absurd != funny
- Needs hard word limit (8-20 words) and concrete style examples
