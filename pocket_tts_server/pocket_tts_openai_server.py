import os
import argparse
import sys
import logging
import io
import time
import json
import glob
from pathlib import Path
from flask import Flask, request, jsonify, send_file, render_template, Response, stream_with_context
import torch
import torchaudio
import atexit
import shutil

try:
    from pocket_tts import TTSModel
except ImportError:
    print("Error: pocket-tts not found. Please install it using 'pip install pocket-tts'.")
    sys.exit(1)

from .utils import validate_format, convert_audio, write_wav_header

# Configure Logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("PocketTTS-Server")

app = Flask(__name__)

# Global Variables
model = None
voice_cache = {} # Cache for voice states
VOICES_DIR = None

# --- PyInstaller Support ---
if getattr(sys, 'frozen', False):
    # If the application is run as a bundle, the PyInstaller bootloader
    # extends the sys module by a flag frozen=True.
    if hasattr(sys, '_MEIPASS'):
        # One-file mode
        base_path = sys._MEIPASS
    else:
        # One-dir mode
        base_path = os.path.dirname(os.path.abspath(sys.executable))
        
    template_folder = os.path.join(base_path, 'templates')
    static_folder = os.path.join(base_path, 'static')
    app = Flask(__name__, template_folder=template_folder, static_folder=static_folder)
    
    # Default Voices Dir when frozen (bundled)
    # We will assume 'voices' is bundled into the root of the executable
    BUNDLE_VOICES_DIR = os.path.join(base_path, 'voices')
    BUNDLE_MODEL_PATH = os.path.join(base_path, 'model', 'b6369a24.yaml')
else:
    app = Flask(__name__)
    base_path = os.path.dirname(os.path.abspath(__file__))
    BUNDLE_VOICES_DIR = None
    BUNDLE_MODEL_PATH = None

# --- Helpers ---
def get_voice_state(voice_id_or_path):
    """
    Resolve voice ID to a model state with caching.
    """
    global voice_cache
    
    # 1. Normalize/Resolve the ID to its final path/form first
    resolved_key = voice_id_or_path
    if VOICES_DIR:
        possible_path = os.path.join(VOICES_DIR, voice_id_or_path)
        if os.path.exists(possible_path):
            resolved_key = os.path.abspath(possible_path) # Use absolute path for consistency
    elif os.path.exists(voice_id_or_path):
        resolved_key = os.path.abspath(voice_id_or_path)

    # 2. Check cache using the resolved key
    if resolved_key in voice_cache:
        logger.info(f"Using cached voice state for {resolved_key}")
        return voice_cache[resolved_key]
    
    # 3. If not cached, load it
    try:
        if os.path.exists(resolved_key):
            logger.info(f"Loading new voice state from file: {resolved_key}")
        else:
            logger.info(f"Loading new voice state from ID/URL: {resolved_key}")
            
        state = model.get_state_for_audio_prompt(resolved_key)
        
        # 4. Store in cache using the same resolved key
        voice_cache[resolved_key] = state
        return state
        
    except Exception as e:
        logger.error(f"Failed to load voice {resolved_key}: {e}")
        raise ValueError(f"Voice '{voice_id_or_path}' could not be loaded.")

# --- Routes ---

@app.route('/')
def home():
    """Serve the simple web interface."""
    return render_template('index.html')

@app.route('/v1/voices', methods=['GET'])
def list_voices():
    """List available voices: Built-ins + Scanned Directory."""
    
    # 1. Built-in defaults
    # User requested specific voices: alba, marius, javert, jean, fantine, cosette, eponine, azelma
    # We map them to potential IDs. Since we don't have exact URLs for all, we assume they are either
    # resolved by pocket-tts or the user has these files/IDs.
    
    builtin_map = {
       "alba": "alba",
       "marius": "marius", 
       "javert": "javert",
       "jean": "jean",
       "fantine": "fantine",
       "cosette": "cosette",
       "eponine": "eponine",
       "azelma": "azelma"
    }

    voices = []
    for name_id in ["alba", "marius", "javert", "jean", "fantine", "cosette", "eponine", "azelma"]:
        # If we have a known mapping (like for alba), use it as ID? 
        # Or just use the name as ID and let get_voice_state handle it?
        # Specifying ID as the lookup key.
        voices.append({
            "id": builtin_map.get(name_id, name_id),
            "name": name_id.capitalize()
        })
    
    # 2. Scan Directory if configured
    if VOICES_DIR and os.path.isdir(VOICES_DIR):
        # Define supported extensions
        extensions = ("*.wav", "*.mp3", "*.flac")
        
        # Gather all matching files
        audio_files = []
        for ext in extensions:
            audio_files.extend(glob.glob(os.path.join(VOICES_DIR, ext)))

        for f in audio_files:
            name = os.path.basename(f)
            # ID is the full path so the server can access it, or just filename if we handle resolution
            # Using filename for UI consistency as per original logic
            voices.append({
                "id": name, 
                "name": f"Local: {name}"
            })

    return jsonify({
        "object": "list",
        "data": [{"id": v["id"], "name": v["name"], "object": "voice"} for v in voices]
    })

@app.route('/upload_voice', methods=['POST'])
def upload_voice():
    """Upload a custom voice file temporarily."""
    if 'file' not in request.files:
        return jsonify({"error": "No file part"}), 400
    
    file = request.files['file']
    if file.filename == '':
        return jsonify({"error": "No selected file"}), 400
        
    if file:
        # Create uploads dir if not exists
        upload_dir = os.path.join(base_path, 'uploads')
        os.makedirs(upload_dir, exist_ok=True)
        
        # Save file with a safe unique name
        filename = f"custom_voice_{int(time.time())}_{file.filename}"
        filepath = os.path.join(upload_dir, filename)
        file.save(filepath)
        
        logger.info(f"Uploaded custom voice to: {filepath}")
        return jsonify({"path": filepath})


@app.route('/v1/audio/speech', methods=['POST'])
def generate_speech():
    """OpenAI-compatible speech generation endpoint."""
    data = request.json
    
    if not data:
        return jsonify({"error": "Missing JSON body"}), 400
        
    text = data.get('input')
    voice = data.get('voice', 'hf://kyutai/tts-voices/alba-mackenna/casual.wav')
    
    # Check stream flag
    stream_request = data.get('stream', False)
    
    if stream_request:
        response_format = data.get('response_format', 'pcm')
    else:
        response_format = data.get('response_format', 'mp3')

    if not text:
        return jsonify({"error": "Missing 'input' text"}), 400

    target_format = validate_format(response_format)
    
    try:
        # Load Voice (with cache)
        voice_state = get_voice_state(voice)
        
        # Determine Generation Mode
        if stream_request or app.config.get('CLI_STREAM_DEFAULT'):
            return stream_audio(voice_state, text, target_format)
        else:
            return generate_file(voice_state, text, target_format)
            
    except Exception as e:
        logger.exception("Generation failed")
        return jsonify({"error": str(e)}), 500

def generate_file(voice_state, text, fmt):
    """Generate full audio and return as file."""
    t0 = time.time()
    audio_tensor = model.generate_audio(voice_state, text)
    generation_time = time.time() - t0
    logger.info(f"Generated {len(text)} chars in {generation_time:.2f}s")
    
    # Convert
    audio_buffer = convert_audio(audio_tensor, model.sample_rate, fmt)
    
    mimetype = f"audio/{fmt}"
    if fmt == 'wav': mimetype = 'audio/wav'
    elif fmt == 'mp3': mimetype = 'audio/mpeg'
    
    return send_file(
        audio_buffer,
        mimetype=mimetype,
        as_attachment=True,
        download_name=f"speech.{fmt}"
    )

def stream_audio(voice_state, text, fmt):
    """Stream audio chunks as WAV or raw PCM."""
    
    def generate():
        # pocket-tts native streaming
        stream = model.generate_audio_stream(voice_state, text)
        
        for chunk_tensor in stream:
            if chunk_tensor.is_cuda: 
                chunk_tensor = chunk_tensor.cpu()
            if chunk_tensor.dim() == 1: 
                chunk_tensor = chunk_tensor.unsqueeze(0)
            
            # Convert to 16-bit PCM
            c = (chunk_tensor * 32767).clamp(-32768, 32767).to(torch.int16)
            yield c.numpy().tobytes()

    def stream_with_header():
        # ONLY yield header if format is WAV
        if fmt == 'wav':
            yield write_wav_header(model.sample_rate, num_channels=1, bits_per_sample=16, num_frames=0)
             
        yield from generate()

    # Match the MIME types
    if fmt == 'pcm':
        mimetype = "audio/L16"
    elif fmt == 'wav':
        mimetype = "audio/wav"
    else:
        mimetype = f"audio/{fmt}"
    
    return Response(stream_with_context(stream_with_header()), mimetype=mimetype)


# --- startup ---
def cleanup_uploads():
    """Delete all files in the uploads directory."""
    upload_dir = os.path.join(base_path, 'uploads')
    if os.path.exists(upload_dir):
        logger.info(f"Cleaning up uploads directory: {upload_dir}")
        try:
            # Iterate and remove files
            for filename in os.listdir(upload_dir):
                file_path = os.path.join(upload_dir, filename)
                try:
                    if os.path.isfile(file_path) or os.path.islink(file_path):
                        os.unlink(file_path)
                    elif os.path.isdir(file_path):
                        shutil.rmtree(file_path)
                except Exception as e:
                    logger.warning(f"Failed to delete {file_path}. Reason: {e}")
        except Exception as e:
            logger.error(f"Error checking uploads directory: {e}")

def start_server(model_path=None, host="0.0.0.0", port=5002, stream=True, voices_dir=None):
    """Programmatic entry point to start the server."""
    global model, VOICES_DIR
    
    app.config['CLI_STREAM_DEFAULT'] = stream
    VOICES_DIR = voices_dir
    
    cleanup_uploads()
    atexit.register(cleanup_uploads)

    logger.info("Loading Pocket TTS Model...")
    
    # Use model_path as variant if provided, otherwise default
    if model_path:
        logger.info(f"Using custom model variant/path: {model_path}")
        model = TTSModel.load_model(variant=model_path)
    elif getattr(sys, 'frozen', False):
        # Check if model is bundled in 'model' dir
        if os.path.isfile(BUNDLE_MODEL_PATH):
            logger.info(f"Using bundled model from: {BUNDLE_MODEL_PATH}")
            try:
                model = TTSModel.load_model(variant=BUNDLE_MODEL_PATH)
            except Exception as e:
                logging.error(f"Error trying to load models bundled with .exe: {e}. Returning to default model load.")
                model = TTSModel.load_model()
        else:
            model = TTSModel.load_model()
    else:
        model = TTSModel.load_model()
        
    logger.info(f"Model loaded. Device: {model.device}, Sample Rate: {model.sample_rate}")
    
    if VOICES_DIR:
        logger.info(f"Scanning voices from: {VOICES_DIR}")
        
    logger.info(f"Starting server on {host}:{port}")
    # We set use_reloader=False because it doesn't play well with multiprocessing
    app.run(host=host, port=port, debug=False, threaded=True, use_reloader=False)

def main():
    # 1. Cleanup on start
    cleanup_uploads()
    # 2. Register cleanup on exit
    atexit.register(cleanup_uploads)

    parser = argparse.ArgumentParser(description="Pocket TTS OpenAI Compatible Server")
    parser.add_argument("--model_path", type=str, default=None, help="Path to model file or variant name")
    parser.add_argument("--host", type=str, default="0.0.0.0", help="Host to run server")
    parser.add_argument("--port", type=int, default=5002, help="Port to run server")
    parser.add_argument("--stream", action="store_true", help="Enable streaming by default")
    parser.add_argument("--voices_dir", type=str, default=None, help="Directory containing local voice .wav, .mp3 or .flac files")
    
    args = parser.parse_args()
    
    # Config
    app.config['CLI_STREAM_DEFAULT'] = args.stream
    global VOICES_DIR
    if args.voices_dir:
        VOICES_DIR = args.voices_dir
    elif getattr(sys, 'frozen', False) and BUNDLE_VOICES_DIR and os.path.isdir(BUNDLE_VOICES_DIR):
        VOICES_DIR = BUNDLE_VOICES_DIR
    else:
        VOICES_DIR = None
    
    global model
    logger.info("Loading Pocket TTS Model...")
    
    # Use model_path as variant if provided, otherwise default
    if args.model_path:
        logger.info(f"Using custom model variant/path: {args.model_path}")
        model = TTSModel.load_model(variant=args.model_path)
    elif getattr(sys, 'frozen', False):
        # Check if model is bundled in 'model' dir
        if os.path.isfile(BUNDLE_MODEL_PATH):
            logger.info(f"Using bundled model from: {BUNDLE_MODEL_PATH}")
            try:
                model = TTSModel.load_model(variant=BUNDLE_MODEL_PATH)
            except Exception as e:
                logging.error(f"Error trying to load models bundled with .exe: {e}. Returning to default model load.")
                model = TTSModel.load_model()
        else:
            model = TTSModel.load_model()
    else:
        model = TTSModel.load_model()
        
    logger.info(f"Model loaded. Device: {model.device}, Sample Rate: {model.sample_rate}")
    
    if VOICES_DIR:
        logger.info(f"Scanning voices from: {VOICES_DIR}")
        
    logger.info(f"Starting server on {args.host}:{args.port}")
    app.run(host=args.host, port=args.port, debug=False, threaded=True)

if __name__ == "__main__":
    main()
