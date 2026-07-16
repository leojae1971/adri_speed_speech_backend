"""
Generador de línea de tiempo de "visemas" (estados de boca) aproximado
por duración de palabra — NO por análisis real del audio.

Por qué esta simplificación: hacer análisis de amplitud real requiere
decodificar MP3/PCM en el servidor (ffmpeg, pydub u otra dependencia
pesada que además complica el despliegue en un free tier de hosting).
Para un avatar estilizado (no fotorrealista), sincronizar la boca a la
duración estimada de cada palabra es suficiente y es lo que hacen la
mayoría de asistentes conversacionales 2D.

Ruta de upgrade futura: si necesitas lip-sync fonético real, usa
Rhubarb Lip Sync (binario open-source, MIT, corre en CPU en
milisegundos). NUNCA uses SadTalker/Wav2Lip para conversación en
tiempo real — son generadores de video por lote, tardan varios
segundos por frase incluso en GPU.
"""
from dataclasses import dataclass, asdict

# Ritmo de habla asumido. Ajusta esta constante cuando midas el
# ritmo real de tus proveedores TTS (Azure/Google no siempre hablan
# al mismo ritmo con el mismo texto).
CHARS_PER_SECOND = 15


@dataclass
class VisemeFrame:
    start_ms: int
    end_ms: int
    mouth: str  # "closed" | "half" | "open"


def estimate_visemes(text: str) -> list[dict]:
    """
    Devuelve una lista de frames [{start_ms, end_ms, mouth}, ...] que
    el cliente Flutter usa para animar la boca del avatar en sincronía
    con la posición de reproducción del audio.
    """
    words = text.split()
    if not words:
        return []

    frames: list[VisemeFrame] = []
    t_ms = 0
    for word in words:
        duration_ms = max(80, int(len(word) / CHARS_PER_SECOND * 1000))
        n_syl = max(1, len(word) // 3)  # aproximación cruda de sílabas
        seg = duration_ms // n_syl
        for i in range(n_syl):
            mouth = "open" if i % 2 == 0 else "half"
            frames.append(VisemeFrame(t_ms, t_ms + seg, mouth))
            t_ms += seg
        frames.append(VisemeFrame(t_ms, t_ms + 60, "closed"))  # pausa entre palabras
        t_ms += 60

    return [asdict(f) for f in frames]
