import yaml
from pathlib import Path

def gerar_imagem(prompt, **kwargs):
    """Gera imagem via Stable Diffusion (local) ou DALL-E (api)."""
    cfg = kwargs.get("config", {})
    hd_root = kwargs.get("hd_root", Path("."))
    workspace = hd_root / "workspace"

    if cfg.get("operation", {}).get("mode") == "local":
        try:
            from diffusers import StableDiffusionPipeline
            import torch
            modelos = hd_root / "ia_system" / "models"
            pipe = StableDiffusionPipeline.from_pretrained(
                str(modelos / "stable-diffusion-v1-5")
            )
            if cfg.get("local_resources", {}).get("use_gpu", True) and torch.cuda.is_available():
                pipe.to("cuda")
            image = pipe(prompt).images[0]
            output = workspace / "imagem_gerada.png"
            image.save(str(output))
            return f"Imagem gerada e salva em: {output}"
        except Exception as e:
            return f"Erro ao gerar imagem local: {e}. Tente modo API ou instale o modelo."
    else:
        return "Modo API para geracao de imagem - configure a chave da OpenAI ou Stability AI."

