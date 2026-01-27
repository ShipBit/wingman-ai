import io
import torch
import torchaudio
import logging

logger = logging.getLogger(__name__)

def convert_audio(audio_tensor: torch.Tensor, sample_rate: int, target_format: str = 'wav') -> io.BytesIO:
    """
    Convert a raw audio tensor to a byte buffer in the specified format.
    
    Args:
        audio_tensor (torch.Tensor): The audio waveform (1D or 2D).
        sample_rate (int): The sample rate of the audio.
        target_format (str): The target audio format (mp3, wav, opus, aac, flac).
        
    Returns:
        io.BytesIO: Buffer containing the encoded audio data.
    """
    buffer = io.BytesIO()
    
    # Ensure tensor is CPU
    if audio_tensor.is_cuda:
        audio_tensor = audio_tensor.cpu()
        
    # Ensure 2D (channels, time)
    if audio_tensor.dim() == 1:
        audio_tensor = audio_tensor.unsqueeze(0)
        
    # Validation/Normalization if needed
    # torchaudio.save expects data in range [-1, 1] usually, confirm if normalization needed?
    # PocketTTS output range is typically fine, but clipping is good practice.
    # audio_tensor = torch.clamp(audio_tensor, -1.0, 1.0)

    try:
        torchaudio.save(buffer, audio_tensor, sample_rate, format=target_format)
        buffer.seek(0)
        return buffer
    except Exception as e:
        logger.error(f"Error converting audio to {target_format}: {e}")
        # Fallback to wav if conversion fails? Or re-raise?
        # For now, let's try to handle common issues or re-raise
        raise e

def validate_format(fmt: str) -> str:
    """Normalize and validate the requested audio format."""
    fmt = fmt.lower()
    valid_formats = {'mp3', 'wav', 'opus', 'aac', 'flac', 'pcm'}
    
    if fmt == 'mpeg': # OpenAI sometimes sends 'mpeg' aka mp3
        return 'mp3'
        
    if fmt not in valid_formats:
        return 'wav' # Default fallback
    return fmt

def write_wav_header(sample_rate: int, num_channels: int = 1, bits_per_sample: int = 16, num_frames: int = 0) -> bytes:
    """
    Generate a WAV header. If num_frames is 0, set to 0xFFFFFFFF (unknown/large).
    """
    import struct
    
    byte_rate = sample_rate * num_channels * bits_per_sample // 8
    block_align = num_channels * bits_per_sample // 8
    
    # Data size: if unknown, max uint32 approximately
    data_size = num_frames * block_align
    if num_frames == 0:
        data_size = 0xFFFFFFFF - 36 # Max possible size remaining
        
    chunk_size = 36 + data_size
    
    header = io.BytesIO()
    header.write(b'RIFF')
    header.write(struct.pack('<I', chunk_size))
    header.write(b'WAVE')
    header.write(b'fmt ')
    header.write(struct.pack('<I', 16)) # Subchunk1Size (16 for PCM)
    header.write(struct.pack('<H', 1))  # AudioFormat (1 for PCM)
    header.write(struct.pack('<H', num_channels))
    header.write(struct.pack('<I', sample_rate))
    header.write(struct.pack('<I', byte_rate))
    header.write(struct.pack('<H', block_align))
    header.write(struct.pack('<H', bits_per_sample))
    header.write(b'data')
    header.write(struct.pack('<I', data_size))
    
    return header.getvalue()
