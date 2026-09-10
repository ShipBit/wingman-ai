# Speech / TTS pricing (fetched 2026-09-10 via WebFetch)

## Deepgram (https://deepgram.com/pricing)
- STT Nova-3 monolingual streaming: "Current price $0.0048/min Regular price $0.0077/min"; multilingual streaming "$0.0058/min (regular $0.0092/min)"; pre-recorded mono $0.0043/min, multi $0.0052/min. "45+ languages".
- TTS Aura-2 "$0.030/1k characters" (= $30/1M); Aura-1 "$0.0150/1k" (= $15/1M). Free $200 credit on signup; growth plan up to 20% off with prepaid yearly credits.

## ElevenLabs API (https://elevenlabs.io/pricing/api)
- Per 1K chars: v3 $0.10; v3 Conversational $0.05; v2 Multilingual $0.10; Flash/Turbo $0.05 (= $50/1M chars for Flash).
- STT Scribe v2 $0.22/h, realtime $0.39/h. Pay-as-you-go exists ("No commitment"). Plans: Starter $6 (10k chars v3), Creator $22 (220k), Pro $99 (990k), Scale $299 (2.99M), Business $990 (9.9M).
- Languages: 70+ (v3), 29 (v2 Multilingual), 32 (Flash/Turbo).

## Inworld (https://inworld.ai/pricing)
- TTS-2: On-Demand $25/1M chars; Creator $20; Builder $17.50; Developer $15; Growth $12.50; Enterprise "as low as $5/1M".
- TTS-2 Flash: On-Demand $15/1M; Creator $10; Builder $9; Developer $8; Growth $7; Enterprise sub-$5.
- Free: "Up to 70 min TTS included" on On-Demand. "200+ languages". TTS-1 / TTS-1-Max no longer on the page (wingman-api still sends modelId "inworld-tts-1").

## Azure AI Speech (https://azure.microsoft.com/en-us/pricing/details/cognitive-services/speech-services/)
- Prices render as "$-" (JS); page labels it "public preview pricing". Free F0: STT 5 audio hours/month, TTS 0.5M chars/month neural. See Retail Prices API result below if fetched.

## Google Cloud TTS
- Pricing page truncated by fetcher; not captured.
