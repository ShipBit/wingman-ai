# Condensation: prompt and model findings

Measured 2026-09-14 with `evals/condense_suite/run.py` as
`results/bakeoff.json`, `results/local.json` and `results/models-example_led.json`.
Those files are not in git — `evals/.gitignore` excludes `results/`, as it does
for the other harnesses — so the numbers below are the record. Rerun to refresh
them.

## The shipped prompt did not summarise

Measured in a real ATC session before this work: 44 messages became a 956-token
summary and saved **53 tokens**. The prompt at the time said

> You extract **ALL** facts from conversations as bullet-point lists.
> Every topic discussed gets **at least one** bullet.
> Each bullet = one atomic fact. Do **NOT** merge multiple facts into a single bullet.
> Include: … questions AND their answers, **tool results** …

That is the specification for a transcript. It cannot shrink anything, and
because "tool results" is spelled out, the plumbing came along:

> * The 'wingman_starhead' capability was activated.
> * The available tools after activating 'wingman_starhead' are
>   mcp_wingman_starhead_sc_get_ships, mcp_wingman_starhead_sc_get_locations, …

In the suite it reproduces exactly: ratio **0.867** (a summary as long as its
source) and the only prompt with a cleanliness score below 1.

## Prompt bake-off

Five prompts × three cloud models × six conversation shapes, plus all five
against the bundled 2B. Averages across all runs:

| prompt | score | recall | ratio | clean | tokens | worst case |
| --- | --- | --- | --- | --- | --- | --- |
| **example_led** | **0.990** | 0.979 | **0.311** | 1.000 | 69 | 0.83 qwen3.5-2b / long_session |
| minimal | 0.983 | 0.966 | 0.319 | 1.000 | 72 | 0.83 flash-lite / long_session |
| budgeted | 0.980 | 0.967 | 0.406 | 1.000 | 92 | 0.83 flash-lite / long_session |
| terse_rules | 0.978 | 0.955 | 0.394 | 1.000 | 90 | 0.81 qwen3.5-2b / roleplay |
| shipped | 0.922 | 0.986 | 0.867 | 0.947 | 232 | 0.71 flash-lite / tool_heavy_mcp |

The shipped prompt has the **best recall** — it keeps everything, because it
copies everything. That is the trap: recall alone does not say whether a summary
is worth making.

### The split the numbers exposed

`terse_rules` — rule lists with a "keep / drop" structure — wins on cloud models
and is the **worst** of the four candidates on the 2B:

| prompt | cloud (3 models) | local 2B |
| --- | --- | --- |
| terse_rules | 1.000 | 0.910 |
| example_led | 1.000 | 0.958 |
| minimal | 0.991 | 0.959 |

A 2B follows examples better than it follows rules. `example_led` is the only
prompt that is first-place on cloud and within 0.001 of first on the 2B, which
is why it is now what ships.

## Per conversation shape, shipped prompt

| shape | score | ratio | summary tokens |
| --- | --- | --- | --- |
| command_heavy | 1.000 | 0.23 | 60 |
| roleplay | 1.000 | 0.36 | 89 |
| tool_heavy_mcp | 1.000 | 0.17 | 88 |
| long_session | 0.958 | 0.13 | 42 |
| terse_typos | 1.000 | 0.51 | 72 |
| german_user | 0.979 | 0.46 | 62 |

Two shapes compress least, for opposite reasons. `terse_typos` is already dense —
there is little filler to remove. `german_user` is short to begin with. Neither
is a problem: the ratio matters on the long sessions, and those sit at 0.13.

The one repeated miss on the 2B is `long_session` losing "Lorville" — a place
named once in passing, twenty messages before the end.

## Model rating

All eight gateway models plus the bundled 2B, with the shipping prompt, six
cases each. Cost is per single condensation (the run total divided by six).

| model | score | recall | ratio | tokens | seconds | $ / condensation |
| --- | --- | --- | --- | --- | --- | --- |
| google/gemini-2.5-flash-lite | 1.000 | 1.000 | 0.263 | 60 | **0.65** | 0.000077 |
| alibaba/qwen3.7-flash | 1.000 | 1.000 | 0.278 | 59 | 1.61 | **0.000023** |
| zai/glm-5.3-flash | 1.000 | 1.000 | 0.286 | 68 | 1.55 | 0.000108 |
| deepseek/deepseek-v4.1-flash | 1.000 | 1.000 | 0.294 | 67 | 1.32 | 0.000213 |
| openai/gpt-4.1-mini | 1.000 | 1.000 | 0.339 | 77 | 1.91 | 0.000313 |
| google/gemini-3.1-flash-lite | 1.000 | 1.000 | 0.274 | 59 | 4.37 | 0.001138 |
| google/gemini-3-flash | 0.979 | 0.958 | 0.274 | 57 | 7.45 | 0.002168 |
| google/gemini-2.5-flash | 0.972 | 0.945 | 0.298 | 66 | 0.96 | 0.000322 |
| local/qwen3.5-2b | 0.956 | 0.924 | 0.342 | 83 | 1.63 | 0 |

**There is no clear winner, and that is the useful result.** Six models score a
perfect 1.000. Condensing a 3–5k-token conversation into bullet points is not a
hard task; every current flash-class model can do it once the prompt stops
asking for a transcript. So the choice is free to be made on latency and price.

Three things worth naming:

- **The expensive models are not better at this.** `gemini-3-flash` costs 28×
  `gemini-2.5-flash-lite`, takes 11× as long, and scores *lower* (0.979) — it
  dropped "ArcCorp" from `tool_heavy_mcp`. `gemini-3.1-flash-lite` matches
  flash-lite's score at 15× the price and 6.7× the latency. Nothing about a
  bigger model helps here.
- **`gemini-2.5-flash-lite` stays the support-lane default.** It is the fastest
  perfect scorer at 0.65s, and condensation blocks the user's turn, so seconds
  are what the pilot actually feels. `qwen3.7-flash` is 3.3× cheaper but 2.5×
  slower; at $0.000077 per condensation the saving is not worth a second of
  silence mid-flight.
- **`deepseek-v4.1-flash` scores 1.000** — it summarises as well as anything on
  the list. It joins the catalogue as a chat model, not as a support model and
  not as a default, per the decision already taken.

### The local 2B survives

At 0.956 it stays in. It is not perfect: across 54 runs it lost "Lorville" once
and "evening" once, and it leaked an MCP tool name into one `tool_heavy_mcp`
summary. That is the same "Lorville" that `gemini-2.5-flash` also lost — a
place named once, far from the end.

For a model running on the pilot's own machine at zero cost, losing one
passing mention per six long sessions is an acceptable trade. No need to drop
it and no need for a separate prompt for it — which was the open question.

## Running this again

Before a new model goes into a plan:

    export AI_GATEWAY_API_KEY=...
    python evals/condense_suite/run.py --models vendor/new-model --prompts example_led

Six calls, a few cents, about a minute. Read the `score` column and the
`weakest results` block. A model below roughly 0.95, or one that leaks tool
names into `tool_heavy_mcp`, is not ready for the support lane.

Adding a conversation shape is one dict in `conversations.py`; adding a prompt
to try is one entry in `prompt_variants.py`. Scoring is deterministic keyword
and substring matching — no judge model — so two runs a month apart are
comparable and a rerun costs the same few cents.
