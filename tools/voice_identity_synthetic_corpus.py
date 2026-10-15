"""Phase 32A.V synthetic-audio corpus from Reachy's own text-to-speech.

Runs the hub's real TTS code (`reachy_hub.tts`: the deployed Piper voice and the espeak-ng fallback with its voices and variants) over a fixed set of phrases, and writes
the clips and a manifest. It deploys nothing: run it in a throwaway container from the hub image, which already contains both engines and the pinned Piper voice, e.g.

    docker run --rm --network none -v "$PWD/tools:/tools:ro" -v "$OUT:/out" --entrypoint /app/.venv/bin/python \\
        reachy-homelab-reachy-hub:latest /tools/voice_identity_synthetic_corpus.py /out

TTS is deterministic, so two runs give identical bytes (the manifest records each clip's SHA-256 and the validation checks it). Generated voices are NOT independent human
speakers: espeak variants share one synthesiser and differ by formant/pitch settings, and there is a single Piper voice. Nothing here is evidence about real people.
"""

from __future__ import annotations

import hashlib
import json
import sys
import time
import wave
from pathlib import Path

from reachy_hub.tts import EspeakTTS, PiperTTS, spoken_text  # the hub's own TTS code

ENROLLMENT = [
    "The quick brown fox jumps over the lazy dog.",
    "Please remind me to call the dentist on Thursday morning.",
    "What is on my calendar for tomorrow afternoon?",
    "Add milk, eggs and a loaf of bread to the shopping list.",
    "Set an alarm for half past six and read me the weather.",
    "My voice is my own, and I am enrolling it on my own phone.",
    "Reachy, summarise the meeting we had on Monday.",
    "Nine green bottles stood on the shelf by the window.",
]
SHORT = ["Hello Reachy.", "What time is it?", "Stop the music.", "Turn on the lights.", "Good morning."]
MEDIUM = [
    "Can you tell me whether it is going to rain this afternoon?",
    "Create a task to review the quarterly budget before Friday.",
    "Read my notes from the planning session on Tuesday.",
    "How long will it take to get to the office by train?",
    "Remind me to send the signed contract to the accountant tomorrow.",
]
LONG = [
    "Last week the team agreed to move the release to the following Wednesday, so please update the calendar, tell the others, and make sure the documentation is ready by then.",
    "I would like a short summary of everything we decided in the meeting about the new storage system, including who owns each action and when each one is due.",
    "When you have a moment, search my documents for the warranty terms of the washing machine, and tell me how many months of coverage remain after the repair.",
]

# (label, engine, espeak voice). Piper is the deployed default and the only independent neural voice available; the rest are espeak-ng voices and variants.
VOICES = [
    ("piper-lessac", "piper", None),
    ("espeak-en-us", "espeak", "en-us"),
    ("espeak-en-gb-rp", "espeak", "en-gb-x-rp"),
    ("espeak-en-scotland", "espeak", "en-gb-scotland"),
    ("espeak-en-caribbean", "espeak", "en-029"),
    ("espeak-us+m3", "espeak", "en-us+m3"),
    ("espeak-us+m7", "espeak", "en-us+m7"),
    ("espeak-us+f2", "espeak", "en-us+f2"),
    ("espeak-us+f4", "espeak", "en-us+f4"),
    ("espeak-us+adam", "espeak", "en-us+adam"),
    ("espeak-us+alicia", "espeak", "en-us+Alicia"),
    ("espeak-rp+f3", "espeak", "en-gb-x-rp+f3"),
]


def phrases() -> list[dict]:
    rows = []
    for group, items in (("enroll", ENROLLMENT), ("short", SHORT), ("medium", MEDIUM), ("long", LONG)):
        for i, text in enumerate(items):
            rows.append({"id": f"{group}{i}", "group": group, "text": text})
    return rows


def main(out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    piper = PiperTTS(__import__("os").environ["PIPER_VOICE_MODEL"])
    engines = {"piper": piper}
    manifest = {"voices": [v[0] for v in VOICES], "phrases": phrases(), "clips": []}
    for label, engine, voice in VOICES:
        tts = engines["piper"] if engine == "piper" else EspeakTTS(voice=voice)
        for phrase in manifest["phrases"]:
            t = time.perf_counter()
            wav = tts.synthesize(spoken_text(phrase["text"]))
            took = time.perf_counter() - t
            name = f"{label}__{phrase['id']}.wav"
            (out / name).write_bytes(wav)
            with wave.open(str(out / name)) as w:
                seconds, rate = w.getnframes() / w.getframerate(), w.getframerate()
            manifest["clips"].append({"file": name, "voice": label, "engine": engine, "espeak_voice": voice, "phrase": phrase["id"], "group": phrase["group"],
                                      "text": phrase["text"], "seconds": round(seconds, 3), "rate": rate, "synth_s": round(took, 4),
                                      "sha256": hashlib.sha256(wav).hexdigest()})
    (out / "manifest.json").write_text(json.dumps(manifest, indent=1))
    print(f"{len(manifest['clips'])} clips from {len(VOICES)} voices x {len(manifest['phrases'])} phrases")


if __name__ == "__main__":
    main(Path(sys.argv[1]))
