def transcrever_audio(caminho_audio, **kwargs):
    """Transcreve áudio usando Whisper."""
    try:
        import whisper
        model = whisper.load_model("base")
        result = model.transcribe(caminho_audio)
        return f"Transcrição: {result['text']}"
    except Exception as e:
        return f"Erro ao transcrever áudio: {e}"

def falar(texto, **kwargs):
    """Converte texto em voz."""
    try:
        import pyttsx3
        engine = pyttsx3.init()
        engine.say(texto)
        engine.runAndWait()
        return "Fala reproduzida."
    except Exception as e:
        return f"Erro ao reproduzir fala: {e}"

