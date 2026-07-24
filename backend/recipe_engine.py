from __future__ import annotations

from copy import deepcopy

from schemas import Emotion, MaterialRecipe, Mode


_BASE: dict[Emotion, dict] = {
    Emotion.JOY: {
        "voiceFx": {"playbackRate": 1.05, "lowpassHz": 6000, "distortion": 0.02, "reverb": 0.30, "gain": 0.95},
        "soundscape": {"stemId": "bright_pluck_01", "pulseRate": 0.76, "stemGain": 0.34},
        "visual": {"sharpness": 0.42, "density": 0.55, "breathing": 0.55, "motion": "rising"},
    },
    Emotion.ANGER: {
        "voiceFx": {"playbackRate": 0.96, "lowpassHz": 3000, "distortion": 0.30, "reverb": 0.18, "gain": 1.00},
        "soundscape": {"stemId": "deep_pulse_01", "pulseRate": 0.82, "stemGain": 0.38},
        "visual": {"sharpness": 0.85, "density": 0.78, "breathing": 0.28, "motion": "compressed"},
    },
    Emotion.SADNESS: {
        "voiceFx": {"playbackRate": 0.88, "lowpassHz": 2600, "distortion": 0.02, "reverb": 0.72, "gain": 0.82},
        "soundscape": {"stemId": "soft_pad_01", "pulseRate": 0.24, "stemGain": 0.30},
        "visual": {"sharpness": 0.18, "density": 0.45, "breathing": 0.42, "motion": "falling"},
    },
    Emotion.ANXIETY: {
        "voiceFx": {"playbackRate": 1.08, "lowpassHz": 4200, "distortion": 0.12, "reverb": 0.35, "gain": 0.90},
        "soundscape": {"stemId": "ticking_air_01", "pulseRate": 0.90, "stemGain": 0.28},
        "visual": {"sharpness": 0.68, "density": 0.66, "breathing": 0.30, "motion": "trembling"},
    },
    Emotion.NEUTRAL_MIXED: {
        "voiceFx": {"playbackRate": 1.00, "lowpassHz": 4200, "distortion": 0.03, "reverb": 0.40, "gain": 0.90},
        "soundscape": {"stemId": "neutral_air_01", "pulseRate": 0.45, "stemGain": 0.26},
        "visual": {"sharpness": 0.35, "density": 0.50, "breathing": 0.48, "motion": "floating"},
    },
}


def build_recipe(emotion: Emotion, mode: Mode) -> dict:
    recipe = deepcopy(_BASE[emotion])
    recipe["emotion"] = emotion.value
    recipe["mode"] = mode.value
    recipe["soundscape"]["emotionStemId"] = f"emotion_{emotion.value}"

    if mode == Mode.EXPRESS:
        recipe["voiceFx"]["distortion"] = min(recipe["voiceFx"]["distortion"] + 0.08, 0.45)
        recipe["voiceFx"]["gain"] = min(recipe["voiceFx"]["gain"] + 0.08, 1.15)
        recipe["soundscape"]["pulseRate"] = min(recipe["soundscape"]["pulseRate"] + 0.12, 1.0)
        recipe["visual"]["sharpness"] = min(recipe["visual"]["sharpness"] + 0.12, 1.0)
        recipe["visual"]["density"] = min(recipe["visual"]["density"] + 0.10, 1.0)
    else:
        recipe["voiceFx"].update({
            "playbackRate": min(recipe["voiceFx"]["playbackRate"], 0.94),
            "lowpassHz": min(recipe["voiceFx"]["lowpassHz"], 1800),
            "distortion": min(recipe["voiceFx"]["distortion"], 0.05),
            "reverb": max(recipe["voiceFx"]["reverb"], 0.65),
            "gain": min(recipe["voiceFx"]["gain"], 0.92),
        })
        recipe["soundscape"]["stemId"] = "warm_drone_02"
        recipe["soundscape"]["pulseRate"] = min(recipe["soundscape"]["pulseRate"], 0.35)
        recipe["visual"].update({
            "sharpness": min(recipe["visual"]["sharpness"], 0.22),
            "breathing": max(recipe["visual"]["breathing"], 0.65),
            "motion": "settling",
        })

    # Keep the original ``soundscape`` key and expose the taskbook's
    # equivalent ``audioBed`` name additively for older and newer clients.
    recipe["audioBed"] = deepcopy(recipe["soundscape"])
    return MaterialRecipe.model_validate(recipe).model_dump(mode="json")
