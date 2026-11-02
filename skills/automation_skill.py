import pyautogui

def clicar_no_centro(**kwargs):
    cfg = kwargs.get("config", {})
    if cfg.get("security", {}).get("allow_host_write", False):
        pyautogui.click(pyautogui.size().width/2, pyautogui.size().height/2)
        return "Clique executado no centro da tela."
    return "ERRO: Automacao bloqueada pelo config.yaml (allow_host_write=false)."

def digitar_texto(texto, **kwargs):
    cfg = kwargs.get("config", {})
    if cfg.get("security", {}).get("allow_host_write", False):
        pyautogui.write(texto)
        return f"Texto digitado: {texto}"
    return "ERRO: Automacao bloqueada pelo config.yaml."
