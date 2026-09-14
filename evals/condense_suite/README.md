# Condensation eval suite

Answers one question before a model goes into a subscription plan: **can it
summarise a Wingman conversation without losing facts, without copying tool
plumbing, and short enough to be worth the call?**

```bash
export AI_GATEWAY_API_KEY=...

# every shipped model against every prompt variant
python evals/condense_suite/run.py

# a candidate we are thinking about adding
python evals/condense_suite/run.py --models moonshotai/kimi-k3

# the bundled 2B (close the desktop app first, it holds the model ports)
python evals/condense_suite/run.py --prompts terse_rules --local

# while rewording a prompt
python evals/condense_suite/run.py --prompts minimal --cases tool_heavy_mcp --show
```

Results are written to `results/` as JSON so two runs stay comparable.

## What it measures

| part | meaning | weight |
| --- | --- | --- |
| `recall` | share of the fixture's fact groups that survived | 0.5 |
| `size` | summary length against a per-fixture budget | 0.2 |
| `cleanliness` | no tool plumbing, no "the assistant could not do X" | 0.2 |
| `form` | bullets, no preamble, no headline, no closing remark | 0.1 |

`ratio` (summary tokens / conversation tokens) is reported but not scored — it
is the cost story, and the budget already covers it per fixture.

Recall carries half the weight on purpose: a shorter summary that forgets the
pilot's name is not an improvement, it is the same failure with extra steps.

Scoring is deterministic — keyword groups and substring markers, no model judge.
A judge would cost money per run, drift between runs, and make two runs
incomparable.

## The conversation shapes

| fixture | what it stresses |
| --- | --- |
| `command_heavy` | VoiceAttack style: many tool calls, almost nothing to keep |
| `roleplay` | long in-character turns, dense with personal facts |
| `tool_heavy_mcp` | MCP activation chatter, websearch results, a big trade table |
| `long_session` | three hours of mixed play including turns with no content |
| `terse_typos` | lowercase, abbreviated, fast typing |
| `german_user` | German conversation — a lot of our users |

## Extending it

- **New model**: pass it to `--models`. If it needs a reasoning switch or a
  pinned provider, add an entry to `REASONING_OFF` / `PROVIDER_PINS` in `run.py`.
- **New conversation shape**: one dict in `conversations.py` with `messages`,
  `required` keyword groups, optional `forbidden` markers and a token budget.
- **New prompt**: one entry in `prompt_variants.py`. `shipped` always reads
  `prompts/condense-conversation.md`, so the baseline follows production.
