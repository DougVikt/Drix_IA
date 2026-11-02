def descrever_imagem(caminho_imagem, **kwargs):
    """Usa OCR/Pillow para descrever uma imagem."""
    try:
        from PIL import Image
        img = Image.open(caminho_imagem)
        return f"Imagem carregada: {caminho_imagem} (Formato: {img.format}, Tamanho: {img.size})"
    except Exception as e:
        return f"Erro ao processar imagem: {e}"

