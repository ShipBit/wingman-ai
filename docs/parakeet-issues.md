# Parakeet STT Issues (2026-04-07)

## Issue 1: macOS CoreML crash

**Symptom**: Switching execution provider to CoreML gives `ONNXRuntimeError: model_path must not be empty` from `onnxruntime/core/optimizer/initializer.cc:45`.

**Root cause**: The `NemoConformerAED` model class explicitly excludes CoreML in `onnx_asr/models/nemo.py:183`:
```python
def _get_excluded_providers() -> list[str]:
    return [*TensorRtOptions.get_provider_names(), "CoreMLExecutionProvider"]
```
But `NemoConformerTdt` (the model Parakeet uses — `nemo-parakeet-tdt-0.6b-v2/v3`) inherits from `NemoConformerRnnt` which has **no CoreML exclusion**. So CoreML is passed to the ONNX session, but the TDT model uses external data files (`onnx?data` pattern in `loader.py:134`) that CoreML can't handle.

**Fix options**:
1. Exclude CoreML from TDT models (like AED does) — simplest, but removes the option
2. Catch the error in `parakeet.py:__load_model_inner()` and fall back to CPU with a toast message
3. Hide the CoreML option in the Client UI when the model variant doesn't support it (requires Core→Client communication of supported providers)

## Issue 2: Windows CUDA doesn't reinitialize properly

**Symptom**: Switching execution provider to CUDA downloads the model but STT doesn't work until full app restart.

**Root cause (suspected)**: `del self.model` in `parakeet.py:101` drops the Python reference to the old ONNX session, but CUDA GPU memory isn't released immediately (Python GC is non-deterministic). When the new CUDA session tries to allocate GPU memory, the old one may still be holding it.

**Fix options**:
1. Force `gc.collect()` after unloading the model before loading the new one
2. Add explicit ONNX session cleanup (call `self.model` internals to release sessions)
3. Add a brief delay between unload and reload for CUDA specifically

## Broader architecture issues

- `__load_model_inner()` has a generic `except Exception` that toasts an error but leaves `self.model = None`. No retry, no CPU fallback.
- No way for the user to recover without restarting the app if reload fails.
- The `_loading` flag prevents transcription during reload, but there's no timeout or progress feedback.
- The Preprocessor (`onnx_asr`) explicitly excludes CUDA — it always runs on CPU regardless of the selected provider. This is by design but may confuse users expecting full CUDA acceleration.

## Key files

### Core (wingman-ai)
- `providers/parakeet.py` — Parakeet provider, model loading, settings update
- `services/settings_service.py:144-148` — calls `parakeet.update_settings_async()`
- `api/interface.py:183-192` — `ParakeetSettings` dataclass

### onnx_asr library (3rd party, in venv)
- `onnx_asr/loader.py:187-357` — `load_model()`, downloads files, creates ONNX sessions
- `onnx_asr/models/nemo.py:70-85` — `NemoConformerRnnt.__init__()` creates encoder/decoder sessions
- `onnx_asr/models/nemo.py:181-183` — `NemoConformerAED._get_excluded_providers()` excludes CoreML
- `onnx_asr/preprocessors/preprocessor.py` — Preprocessor, excludes CUDA
- `onnx_asr/onnx.py:81-101` — `update_onnx_providers()` filters provider list

### Client (wingman-client)
- The execution provider dropdown is in the STT settings UI — may need to filter options per model/platform

## Provider/model compatibility matrix

| Provider | NemoConformerTdt (Parakeet) | NemoConformerAED | Preprocessor |
|----------|---------------------------|------------------|-------------|
| CPU | Yes | Yes | Yes |
| DirectML | Yes | Yes | Yes |
| CUDA | Yes | Yes | **Excluded** |
| CoreML | **Crashes** (should exclude) | **Excluded** | ? |
| TensorRT | Excluded | Excluded | Excluded |
