# Parakeet STT — Follow-up TODO

## Documentation
- [ ] Create Parakeet provider docs (setup, usage, model variants, execution providers)
- [ ] Update dev docs if they reference STT providers (add Parakeet alongside FasterWhisper)

## Credits
- [ ] Add CC-BY-4.0 attribution for NVIDIA Parakeet TDT models to README
- [ ] Credit `onnx-asr` and `onnxruntime` dependencies

## Language setting per Wingman
- [ ] Investigate whether the `language` field in `ParakeetSttConfig` is actually needed — it works fine without setting it
- [ ] Consider removing it if `onnx-asr` handles language detection automatically (v3 is multilingual, v2 is English-only)

## FasterWhisper on-demand loading
- [ ] Currently FasterWhisper loads its model eagerly at startup — explore making it on-demand like Parakeet/PocketTTS to reduce memory usage and bundle size
- [ ] Would need an `enable` toggle in FasterWhisper settings (like Parakeet has)

## Remote access
- [ ] Test remote/offload mode (host/port fields exist in UI and settings but provider currently only does local inference)
- [ ] Implement HTTP client in `providers/parakeet.py` to call a remote Parakeet server at configured host:port
