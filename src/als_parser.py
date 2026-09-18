"""
als_parser.py
Parses an Ableton Live .als file (gzipped XML) into a structured Python dict.
Supports Ableton Live 10, 11, 12.
"""

import gzip
import math
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _float(val: str | None, default: float = 0.0) -> float:
    try:
        return float(val) if val is not None else default
    except (ValueError, TypeError):
        return default


def _int(val: str | None, default: int = 0) -> int:
    try:
        return int(val) if val is not None else default
    except (ValueError, TypeError):
        return default


def _bool(val: str | None, default: bool = False) -> bool:
    if val is None:
        return default
    return val.lower() in ("true", "1")


def _attr(el: ET.Element, *attrs: str, default: str = "") -> str:
    """Try multiple attribute names, return first found."""
    for a in attrs:
        v = el.get(a)
        if v is not None:
            return v
    return default


# ---------------------------------------------------------------------------
# Automation
# ---------------------------------------------------------------------------

def _parse_automation(auto_el: ET.Element | None) -> list[dict]:
    if auto_el is None:
        return []
    events = []
    for ev in auto_el.iter("AutomationEvent"):
        events.append({
            "time": _float(ev.get("Time")),
            "value": _float(ev.get("Value")),
            "curve": _float(ev.get("CurveControl1X"), 0.5),
        })
    return events


def _find_automation_for_param(track_el: ET.Element, param_id: str) -> list[dict]:
    """Find automation envelope for a parameter by its id attribute."""
    for env_el in track_el.iter("AutomationEnvelope"):
        id_el = env_el.find(".//EnvelopeTarget/PointeeId")
        if id_el is not None and id_el.get("Value") == param_id:
            return _parse_automation(env_el.find("Automation"))
    return []


# ---------------------------------------------------------------------------
# Volume / Pan / Mute / Solo
# ---------------------------------------------------------------------------

def _parse_mixer(mixer_el: ET.Element | None) -> dict:
    if mixer_el is None:
        return {"volume": 1.0, "pan": 0.0, "muted": False, "solo": False, "sends": []}

    vol_el = mixer_el.find("Volume/Manual")
    pan_el = mixer_el.find("Pan/Manual")
    mute_el = mixer_el.find("Track/IsMuted")  # may not exist here
    if mute_el is None:
        mute_el = mixer_el.find("IsMuted")

    sends = []
    for send_el in mixer_el.findall("Sends/TrackSendHolder"):
        active_el = send_el.find("Send/Active/Manual")
        amount_el = send_el.find("Send/Manual")
        sends.append({
            "active": _bool(_attr(active_el or ET.Element("x"), "Value"), True) if active_el is not None else True,
            "amount": _float(amount_el.get("Value") if amount_el is not None else None, 0.0),
        })

    return {
        "volume_db": _ableton_vol_to_db(_float(vol_el.get("Value") if vol_el is not None else None, 1.0)),
        "volume_linear": _float(vol_el.get("Value") if vol_el is not None else None, 1.0),
        "pan": _float(pan_el.get("Value") if pan_el is not None else None, 0.0),
        "muted": _bool(mute_el.get("Value") if mute_el is not None else None, False),
        "sends": sends,
    }


def _ableton_vol_to_db(linear: float) -> float:
    import math
    if linear <= 0:
        return -96.0
    return 20 * math.log10(linear)


# ---------------------------------------------------------------------------
# Plugin / Device parsing
# ---------------------------------------------------------------------------

ABLETON_NATIVE_DEVICES = {
    # Device XML tag  →  friendly name
    "Eq8": "EQ Eight",
    "Compressor2": "Compressor",
    "GlueCompressor": "Glue Compressor",
    "Gate": "Gate",
    "Limiter": "Limiter",
    "MultibandDynamics": "Multiband Dynamics",
    "AutoFilter": "Auto Filter",
    "AutoPan": "Auto Pan",
    "Chorus": "Chorus",
    "Chorus2": "Chorus-Ensemble",
    "Flanger": "Flanger",
    "Phaser": "Phaser",
    "Phaser2": "Phaser-Flanger",
    "Saturator": "Saturator",
    "Redux": "Redux",
    "Erosion": "Erosion",
    "Resonators": "Resonators",
    "Reverb": "Reverb",
    "Delay": "Delay",
    "FilterDelay": "Filter Delay",
    "GrainDelay": "Grain Delay",
    "PingPongDelay": "Ping Pong Delay",  # Ableton 10 legacy
    "Utility": "Utility",
    "Spectrum": "Spectrum",
    "TunerDevice": "Tuner",
    "VinylDistortion": "Vinyl Distortion",
    "Overdrive": "Overdrive",
    "Pedal": "Pedal",
    "DrumBuss": "Drum Buss",
    "Roar": "Roar",
    "StereoGain": "Stereo Gain",
    "MidiChord": "Chord",
    "MidiArpeggiator": "Arpeggiator",
    "MidiPitcher": "Pitch",
    "MidiTranspose": "Transpose",
    "MidiVelocity": "Velocity",
}

# Ableton EQ Eight mode map
# Values confirmed by decoding a test .als with each filter type set explicitly.
# Ableton uses 1-based indexing (not 0-based as previously assumed).
EQ8_MODE_MAP = {
    "1": "Low Cut",
    "2": "Low Shelf",
    "3": "Bell",
    "4": "Notch",
    "5": "High Shelf",
    "6": "High Cut",
}

EQ8_SLOPE_MAP = {
    "0": 12,   # 12 dB/oct
    "1": 24,   # 24 dB/oct
    "2": 48,   # 48 dB/oct (some versions)
}


def _parse_eq8(dev_el: ET.Element) -> dict:
    bands = []
    for i in range(8):  # EQ Eight has 8 bands
        band_el = dev_el.find(f"Bands.{i}")
        if band_el is None:
            continue

        # Ableton 12: params nested under ParameterA
        # Ableton 11: params are direct children of the band element
        # Use explicit is not None check — XML elements are falsy even when found
        _pa = band_el.find("ParameterA")
        param_el = _pa if _pa is not None else band_el

        enabled_el = param_el.find("IsOn/Manual")
        freq_el    = param_el.find("Freq/Manual")
        gain_el    = param_el.find("Gain/Manual")
        q_el       = param_el.find("Q/Manual")
        mode_el    = param_el.find("Mode/Manual")
        slope_el   = param_el.find("Slope/Manual")

        # Fallback to direct children for Ableton 11
        if freq_el is None:
            freq_el    = band_el.find("Freq/Manual")
            gain_el    = band_el.find("Gain/Manual")
            q_el       = band_el.find("Q/Manual")
            mode_el    = band_el.find("Mode/Manual")
            slope_el   = band_el.find("Slope/Manual")
            enabled_el = band_el.find("IsOn/Manual")

        bands.append({
            "index":    i,
            "enabled":  _bool(enabled_el.get("Value") if enabled_el is not None else None, True),
            "freq":     _float(freq_el.get("Value") if freq_el is not None else None, 1000.0),
            "gain_db":  _float(gain_el.get("Value") if gain_el is not None else None, 0.0),
            "q":        _float(q_el.get("Value") if q_el is not None else None, 0.7071067811865476),
            "mode":     EQ8_MODE_MAP.get(
                            mode_el.get("Value") if mode_el is not None else "3", "Bell"),
            "slope":    EQ8_SLOPE_MAP.get(
                            slope_el.get("Value") if slope_el is not None else "0", 12),
        })

    on_el   = dev_el.find("On/Manual")
    mode_el = dev_el.find("Mode/Manual")

    return {
        "type":    "EQ Eight",
        "enabled": _bool(on_el.get("Value") if on_el is not None else None, True),
        "bands":   bands,
        "mode":    mode_el.get("Value") if mode_el is not None else "0",
    }


def _parse_compressor(dev_el: ET.Element, friendly_name: str) -> dict:
    def _param(path: str, default: float = 0.0) -> float:
        el = dev_el.find(f"{path}/Manual")
        return _float(el.get("Value") if el is not None else None, default)

    on_el = dev_el.find("On/Manual")
    # Threshold is stored as linear amplitude (0.0003 to 1.995)
    # Gain is stored directly in dB
    # Knee is stored directly in dB
    thresh_linear = _param("Threshold", 0.1)  # default ~-20dB
    import math as _math
    thresh_db = 20.0 * _math.log10(max(thresh_linear, 1e-6))
    return {
        "type": friendly_name,
        "enabled": _bool(on_el.get("Value") if on_el is not None else None, True),
        "threshold_db": thresh_db,
        "ratio": _param("Ratio", 4.0),
        "attack_ms": _param("Attack", 10.0),
        "release_ms": _param("Release", 100.0),
        "makeup_gain_db": _param("Gain", 0.0),
        "knee_db": _param("Knee", 0.0),
        "dry_wet": _param("DryWet", 1.0),
    }


def _parse_glue_compressor(dev_el: ET.Element) -> dict:
    def _param(path: str, default: float = 0.0) -> float:
        el = dev_el.find(f"{path}/Manual")
        return _float(el.get("Value") if el is not None else None, default)

    on_el = dev_el.find("On/Manual")

    # Attack: stored as integer index 0–6 (SSL G-Bus clone standard values, all in ms)
    _GLUE_ATTACK_MS = {0: 0.01, 1: 0.1, 2: 0.3, 3: 1.0, 4: 3.0, 5: 10.0, 6: 30.0}
    attack_idx = int(_param("Attack", 3))
    attack_ms = _GLUE_ATTACK_MS.get(attack_idx, 1.0)

    # Release: stored as integer index 0–6, where 6 = Auto (values in seconds, converted to ms)
    _GLUE_RELEASE_MS = {0: 100.0, 1: 200.0, 2: 400.0, 3: 600.0, 4: 800.0, 5: 1200.0}
    release_idx = int(_param("Release", 2))
    release_auto = (release_idx >= 6)
    release_ms = 400.0 if release_auto else _GLUE_RELEASE_MS.get(release_idx, 400.0)

    # Ratio: stored as integer index 0–2
    _GLUE_RATIO = {0: 2.0, 1: 4.0, 2: 10.0}
    ratio_idx = int(_param("Ratio", 1))
    ratio = _GLUE_RATIO.get(ratio_idx, 4.0)

    return {
        "type": "Glue Compressor",
        "enabled": _bool(on_el.get("Value") if on_el is not None else None, True),
        "threshold_db": _param("Threshold", -20.0),  # direct dB
        "ratio": ratio,
        "attack_ms": attack_ms,
        "release_ms": release_ms,
        "release_auto": release_auto,
        "makeup_gain_db": _param("Makeup", 0.0),     # field is "Makeup" not "MakeupGain"
        "peak_clip_in": _bool(dev_el.findtext("PeakClipIn/Manual"), False),
        "range_db": _param("Range", 70.0),
        "dry_wet": _param("DryWet", 1.0),
    }


def _parse_saturator(dev_el: ET.Element) -> dict:
    def _param(path: str, default: float = 0.0) -> float:
        el = dev_el.find(f"{path}/Manual")
        return _float(el.get("Value") if el is not None else None, default)

    on_el = dev_el.find("On/Manual")
    shape_el = dev_el.find("WaveShaper/Manual")
    return {
        "type": "Saturator",
        "enabled": _bool(on_el.get("Value") if on_el is not None else None, True),
        "drive_db": _param("Drive", 0.0),
        "output_gain_db": _param("Output", 0.0),
        "dry_wet": _param("DryWet", 1.0),
        "shape": shape_el.get("Value") if shape_el is not None else "0",
    }


def _parse_utility(dev_el: ET.Element) -> dict:
    def _param(path: str, default: float = 0.0) -> float:
        el = dev_el.find(f"{path}/Manual")
        return _float(el.get("Value") if el is not None else None, default)

    def _bparam(path: str, default: bool = False) -> bool:
        el = dev_el.find(f"{path}/Manual")
        return _bool(el.get("Value") if el is not None else None, default)

    def _at(path: str) -> str | None:
        at = dev_el.find(f"{path}/AutomationTarget")
        return at.get("Id") if at is not None else None

    on_el = dev_el.find("On/Manual")

    # Ableton 12 stores Utility as StereoGain
    gain_lin = _param("Gain", 1.0)
    gain_db = 20 * math.log10(max(gain_lin, 1e-6))

    # Ableton ChannelMode: 0=Left, 1=Stereo(default), 2=Right, 3=Swap
    channel_mode = int(_param("ChannelMode", 1))

    return {
        "type": "Utility",
        "enabled": _bool(on_el.get("Value") if on_el is not None else None, True),
        "gain_lin": gain_lin,
        "gain_db": gain_db,
        "pan": _param("Balance", 0.0),              # -1..1
        "width": _param("StereoWidth", 1.0),         # 0..2 (0=mono,1=normal,2=wide)
        "channel_mode": channel_mode,
        "phase_l": _bparam("PhaseInvertL", False),
        "phase_r": _bparam("PhaseInvertR", False),
        "mono": _bparam("Mono", False),
        "bass_mono": _bparam("BassMono", False),
        "bass_mono_freq": _param("BassMonoFrequency", 120.0),
        "mute": _bparam("Mute", False),
        "dc_filter": _bparam("DcFilter", False),
        # AutomationTarget Ids (floats: Gain/Balance/StereoWidth/ChannelMode/BassMonoFrequency;
        # bools: PhaseInvertL/R, Mono, BassMono, Mute, DcFilter)
        "auto_targets": {
            "gain":           _at("Gain"),
            "balance":        _at("Balance"),
            "width":          _at("StereoWidth"),
            "channel_mode":   _at("ChannelMode"),
            "phase_l":        _at("PhaseInvertL"),
            "phase_r":        _at("PhaseInvertR"),
            "mono":           _at("Mono"),
            "bass_mono":      _at("BassMono"),
            "bass_mono_freq": _at("BassMonoFrequency"),
            "mute":           _at("Mute"),
            "dc_filter":      _at("DcFilter"),
        },
    }


def _parse_reverb(dev_el: ET.Element) -> dict:
    def _param(path: str, default: float = 0.0) -> float:
        el = dev_el.find(f"{path}/Manual")
        return _float(el.get("Value") if el is not None else None, default)

    on_el = dev_el.find("On/Manual")
    return {
        "type": "Reverb",
        "enabled": _bool(on_el.get("Value") if on_el is not None else None, True),
        "decay_time_s": _param("DecayTime", 1.5),
        "predelay_ms": _param("PreDelay", 10.0),
        "room_size": _param("RoomSize", 0.5),
        "dry_wet": _param("DryWet", 0.3),
        "diffusion": _param("InDiffuseSize", 0.5),
        "hf_damping": _param("ChorusModFreq", 0.0),  # approximation
        "bass_boost": _param("ReflectionsLevel", 0.0),
    }


def _parse_delay(dev_el: ET.Element) -> dict:
    def _fval(path: str, default: float = 0.0) -> float:
        el = dev_el.find(f"{path}/Manual")
        return _float(el.get("Value") if el is not None else None, default)
    def _bval(path: str, default: bool = True) -> bool:
        el = dev_el.find(f"{path}/Manual")
        return _bool(el.get("Value") if el is not None else None, default)
    def _at(path: str) -> str | None:
        at = dev_el.find(f"{path}/AutomationTarget")
        return at.get("Id") if at is not None else None

    on_el = dev_el.find("On/Manual")

    # Ableton Delay XML field names (confirmed from .als inspection)
    l_synced = _bval("DelayLine_SyncL")
    r_synced = _bval("DelayLine_SyncR")

    linked = _bval("DelayLine_Link", False)

    # Synced time: stored as 0-based index into {1,2,3,4,5,6,8,16} sixteenth notes
    l_sixteenths = int(_fval("DelayLine_SyncedSixteenthL", 2))
    # When link is on Ableton only updates the left value; right stores a stale value
    r_sixteenths = l_sixteenths if linked else int(_fval("DelayLine_SyncedSixteenthR", 2))

    # Non-synced time in seconds
    l_time_ms = _fval("DelayLine_TimeL", 0.25) * 1000.0
    r_time_ms = l_time_ms if linked else _fval("DelayLine_TimeR", 0.25) * 1000.0

    return {
        "type":         "Delay",
        "enabled":      _bool(on_el.get("Value") if on_el is not None else None, True),
        "l_synced":     l_synced,
        "r_synced":     r_synced,
        "l_time_ms":    l_time_ms,
        "r_time_ms":    r_time_ms,
        "l_sixteenths": l_sixteenths,
        "r_sixteenths": r_sixteenths,
        "feedback":     _fval("Feedback", 0.5),    # 0..0.95 linear
        "filter_on":    _bval("Filter_On", False),
        "filter_freq":  _fval("Filter_Frequency", 1000.0),  # bandpass center Hz
        "filter_bw":    _fval("Filter_Bandwidth", 8.0),     # bandwidth in octaves
        "dry_wet":      _fval("DryWet", 0.5),      # 0..1 linear
        "auto_targets": {
            "feedback":    _at("Feedback"),
            "filter_on":   _at("Filter_On"),
            "filter_freq": _at("Filter_Frequency"),
            "filter_bw":   _at("Filter_Bandwidth"),
            "dry_wet":     _at("DryWet"),
            "l_synced":    _at("DelayLine_SyncL"),
            "r_synced":    _at("DelayLine_SyncR"),
            "l_sixteenths":_at("DelayLine_SyncedSixteenthL"),
            "r_sixteenths":_at("DelayLine_SyncedSixteenthR"),
            "l_time_ms":   _at("DelayLine_TimeL"),
            "r_time_ms":   _at("DelayLine_TimeR"),
        },
    }


def _parse_chorus(dev_el: ET.Element) -> dict:
    def _param(path: str, default: float = 0.0) -> float:
        el = dev_el.find(f"{path}/Manual")
        return _float(el.get("Value") if el is not None else None, default)

    on_el = dev_el.find("On/Manual")
    return {
        "type": "Chorus",
        "enabled": _bool(on_el.get("Value") if on_el is not None else None, True),
        "rate_hz": _param("Rate", 1.0),
        "depth": _param("Amount", 0.5),
        "delay_ms": _param("DelayTime", 5.0),
        "feedback": _param("Feedback", 0.0),
        "dry_wet": _param("DryWet", 0.5),
    }


def _parse_gate(dev_el: ET.Element) -> dict:
    def _param(path: str, default: float = 0.0) -> float:
        el = dev_el.find(f"{path}/Manual")
        return _float(el.get("Value") if el is not None else None, default)

    on_el = dev_el.find("On/Manual")

    # Threshold: stored as linear amplitude (same as Compressor)
    thresh_lin = _param("Threshold", 0.01)
    threshold_db = 20 * math.log10(max(thresh_lin, 1e-6))

    # Return: dB offset above threshold (0–24dB). Gate closes at threshold - return.
    return_offset_db = _param("Return", 0.0)

    # Floor (field name is "Gain"): output attenuation when gate closed. Range -75–0dB.
    floor_db = _param("Gain", -75.0)

    # LookAhead: enum 0=0ms, 1=1.5ms, 2=10ms — stored as integer, use int() not _bool
    _LOOKAHEAD_MS = {0: 0.0, 1: 1.5, 2: 10.0}
    lookahead_el = dev_el.find("LookAhead/Manual")
    lookahead_idx = int(_float(lookahead_el.get("Value") if lookahead_el is not None else None, 0))
    lookahead_ms = _LOOKAHEAD_MS.get(lookahead_idx, 0.0)

    # FlipMode: stored as integer 0/1, not "true"/"false"
    flipmode_el = dev_el.find("FlipMode/Manual")
    flip = int(_float(flipmode_el.get("Value") if flipmode_el is not None else None, 0)) != 0

    return {
        "type": "Gate",
        "enabled": _bool(on_el.get("Value") if on_el is not None else None, True),
        "threshold_db": threshold_db,
        "return_offset_db": return_offset_db,   # gate closes at threshold - return_offset_db
        "floor_db": floor_db,
        "attack_ms": _param("Attack", 1.0),
        "hold_ms": _param("Hold", 1.0),
        "release_ms": _param("Release", 50.0),
        "lookahead_ms": lookahead_ms,
        "flip": flip,
    }


def _parse_limiter(dev_el: ET.Element) -> dict:
    def _param(path: str, default: float = 0.0) -> float:
        el = dev_el.find(f"{path}/Manual")
        return _float(el.get("Value") if el is not None else None, default)

    on_el = dev_el.find("On/Manual")
    return {
        "type": "Limiter",
        "enabled": _bool(on_el.get("Value") if on_el is not None else None, True),
        "ceiling_db": _param("Ceiling", 0.0),
        "lookahead_ms": _param("Lookahead", 1.5),
        "release_ms": _param("Release", 100.0),
        "stereo_link": _bool(dev_el.findtext("StereoLink/Manual"), True),
    }


def _parse_auto_filter(dev_el: ET.Element) -> dict:
    def _param(path: str, default: float = 0.0) -> float:
        el = dev_el.find(f"{path}/Manual")
        return _float(el.get("Value") if el is not None else None, default)

    on_el = dev_el.find("On/Manual")
    type_el = dev_el.find("FilterType/Manual")
    slope_el = dev_el.find("Slope/Manual")
    return {
        "type": "Auto Filter",
        "enabled": _bool(on_el.get("Value") if on_el is not None else None, True),
        "cutoff_hz": _param("Cutoff", 500.0),
        "resonance": _param("Resonance", 0.5),
        "filter_type": type_el.get("Value") if type_el is not None else "0",
        "slope": slope_el.get("Value") if slope_el is not None else "0",
        "lfo_rate": _param("LfoRate", 1.0),
        "lfo_amount": _param("LfoAmount", 0.5),
        "dry_wet": _param("DryWet", 1.0),
    }


def _parse_generic_device(dev_el: ET.Element, tag: str, friendly_name: str) -> dict:
    """Fallback: capture all Manual param values for any device."""
    on_el = dev_el.find("On/Manual")
    params = {}
    for el in dev_el.iter():
        if el.tag == "Manual" and el.get("Value") is not None:
            # Build a path relative to the device element
            params[el.tag] = el.get("Value")  # simplified; full path tracking below

    # Better: collect all leaf Manual values with their parent path
    params = {}
    def _walk(node: ET.Element, path: str):
        for child in node:
            child_path = f"{path}/{child.tag}" if path else child.tag
            if child.tag == "Manual" and child.get("Value") is not None:
                params[path] = child.get("Value")
            _walk(child, child_path)
    _walk(dev_el, "")

    return {
        "type": friendly_name,
        "ableton_tag": tag,
        "enabled": _bool(on_el.get("Value") if on_el is not None else None, True),
        "params": params,
        "note": "Generic parse — parameters captured but not mapped to Reaper equivalent.",
    }


def _parse_plugin_device(dev_el: ET.Element) -> dict:
    """VST/AU third-party plugin.
    
    Ableton 12 stores Vst3PluginInfo with an Id attribute (e.g. <Vst3PluginInfo Id='0'>)
    which causes find() path matching to fail in ElementTree. Use iter() instead.
    Plugin names may also be URL-encoded (e.g. 'Silk%20Vocal%20Mono').
    """
    import urllib.parse

    # Detect plugin type and find the info element via iter() to avoid Id-attr path bug
    vst3_info = next(dev_el.iter("Vst3PluginInfo"), None)
    vst2_info = next(dev_el.iter("VstPluginInfo"), None)
    au_info   = next(dev_el.iter("AuPluginInfo"), None)

    if vst3_info is not None:
        plugin_type = "VST3"
        name_el  = vst3_info.find("Name")
        manu_el  = vst3_info.find("Manufacturer")
    elif au_info is not None:
        plugin_type = "AU"
        name_el  = au_info.find("Name")
        manu_el  = au_info.find("Manufacturer")
    elif vst2_info is not None:
        plugin_type = "VST2"
        name_el  = vst2_info.find("PlugName")
        manu_el  = vst2_info.find("Manufacturer")
    else:
        plugin_type = "VST"
        name_el  = None
        manu_el  = None

    # Name: try Value attr first, then text content, then BrowserContentPath fallback
    raw_name = None
    if name_el is not None:
        raw_name = name_el.get("Value") or (name_el.text.strip() if name_el.text else None)
    if not raw_name:
        bcp = dev_el.find(".//BrowserContentPath")
        if bcp is not None:
            raw_name = bcp.get("Value", "").split(":")[-1]
    name = urllib.parse.unquote(raw_name or "Unknown Plugin")

    raw_manu = None
    if manu_el is not None:
        raw_manu = manu_el.get("Value") or (manu_el.text.strip() if manu_el.text else None)
    manufacturer = urllib.parse.unquote(raw_manu or "Unknown")

    on_el = dev_el.find("On/Manual")

    # For VST3 Melda plugins: extract ProcessorState blob for passthrough
    processor_state_hex = None
    if vst3_info is not None:
        ps_el = next(dev_el.iter("ProcessorState"), None)
        if ps_el is not None and ps_el.text:
            processor_state_hex = ''.join(ps_el.text.split())

    # Extract ParameterList: maps AutomationTarget Id → (param_idx, param_name)
    # Used to attach FloatEvent automation to the right parameter index.
    param_targets = {}
    param_list = dev_el.find("ParameterList")
    if param_list is not None:
        for p in param_list.findall("PluginFloatParameter"):
            idx = p.get("Id")
            if idx is None:
                continue
            pname_el = p.find("ParameterName")
            pname = pname_el.get("Value", "") if pname_el is not None else ""
            at_el = p.find("ParameterValue/AutomationTarget")
            if at_el is not None:
                at_id = at_el.get("Id")
                if at_id:
                    param_targets[at_id] = (int(idx), pname)

    return {
        "type": "THIRD_PARTY",
        "plugin_type": plugin_type,
        "name": name,
        "manufacturer": manufacturer,
        "enabled": _bool(on_el.get("Value") if on_el is not None else None, True),
        "processor_state_hex": processor_state_hex,  # None if not available
        "param_targets": param_targets,  # {auto_target_id: (param_idx, param_name)}
        "note": "Third-party plugin — cannot be auto-migrated. Manual setup required.",
    }


def _build_automation_index(track_el: ET.Element) -> dict:
    """Index all AutomationEnvelope elements (within this track) by their PointeeId.
    Returns {'bool': {pid: [(t, bool_v)...]}, 'float': {pid: [(t, float_v)...]}}.
    BoolEvent = bypass/on-off automation; FloatEvent = continuous parameter automation."""
    bool_index  = {}
    float_index = {}
    auto_el = track_el.find("AutomationEnvelopes/Envelopes")
    if auto_el is None:
        return {"bool": bool_index, "float": float_index}
    for env in auto_el.findall("AutomationEnvelope"):
        pointee = env.find("EnvelopeTarget/PointeeId")
        if pointee is None:
            continue
        pid = pointee.get("Value")
        events_el = env.find("Automation/Events")
        if events_el is None:
            continue
        bool_events = []
        for be in events_el.findall("BoolEvent"):
            t = _float(be.get("Time"), 0.0)
            v = _bool(be.get("Value"), True)
            bool_events.append((t, v))
        if bool_events:
            bool_index[pid] = bool_events
        float_events = []
        for fe in events_el.findall("FloatEvent"):
            t = _float(fe.get("Time"), 0.0)
            v = _float(fe.get("Value"), 0.0)
            float_events.append((t, v))
        if float_events:
            float_index[pid] = float_events
    return {"bool": bool_index, "float": float_index}


def _get_bypass_automation(dev_el: ET.Element, automation_index: dict) -> list | None:
    """Check if this device's On parameter has bypass automation. Returns a list of
    (beat_time, enabled) tuples sorted by time, or None if no automation present.
    Filters out the sentinel start-of-song time (-63072000) and de-dupes paired
    step-transition points (Ableton stores two events at the same beat for instant
    transitions; we keep only the one that starts the new state)."""
    on_el = dev_el.find("On")
    if on_el is None:
        return None
    target = on_el.find("AutomationTarget")
    if target is None:
        return None
    pid = target.get("Id")
    bool_index = automation_index.get("bool", {}) if isinstance(automation_index, dict) else automation_index
    if pid is None or pid not in bool_index:
        return None

    raw_events = bool_index[pid]
    # Clamp sentinel "beginning of time" to beat 0
    cleaned = [(max(t, 0.0), v) for t, v in raw_events]
    # Sort by time; for duplicate times keep the LAST value (the one that starts the new state)
    cleaned.sort(key=lambda e: e[0])
    deduped = []
    for t, v in cleaned:
        if deduped and deduped[-1][0] == t:
            deduped[-1] = (t, v)  # overwrite with the later entry at same time
        else:
            deduped.append((t, v))
    return deduped


def _parse_device(dev_el: ET.Element, automation_index: dict | None = None) -> dict | None:
    parsed = _parse_device_inner(dev_el)
    if parsed is not None and automation_index:
        bypass_auto = _get_bypass_automation(dev_el, automation_index)
        if bypass_auto:
            parsed["bypass_automation"] = bypass_auto  # list of (beat_time, enabled)
        # VST plugin parameter automation (FloatEvent envelopes)
        float_index = automation_index.get("float", {}) if isinstance(automation_index, dict) else {}
        bool_index_auto = automation_index.get("bool", {}) if isinstance(automation_index, dict) else {}
        param_targets = parsed.get("param_targets", {})
        if param_targets and float_index:
            param_automations = {}
            for at_id, (param_idx, param_name) in param_targets.items():
                raw = float_index.get(at_id)
                if not raw:
                    continue
                # Sort by time only — value must NOT be used as tiebreaker.
                # Ableton encodes instant steps as two events at the same Time:
                # the first is the "from" value, the second is the "to" value.
                # Sorting by (time, value) would reverse pairs like (t,1),(t,0),
                # making a step-down disappear in Reaper (it would see 0→1 not 1→0).
                cleaned = sorted(((max(t, 0.0), v) for t, v in raw), key=lambda e: e[0])
                if cleaned:
                    param_automations[param_idx] = {"name": param_name, "events": cleaned}
            if param_automations:
                parsed["param_automations"] = param_automations
        # Ableton native Delay automation (raw values, not normalized)
        if parsed.get("type") == "Delay":
            auto_targets = parsed.get("auto_targets", {})
            raw_auto = {}
            for param_name, at_id in auto_targets.items():
                if at_id is None:
                    continue
                events = float_index.get(at_id) or bool_index_auto.get(at_id)
                if events:
                    cleaned = sorted(((max(t, 0.0), v) for t, v in events), key=lambda e: e[0])
                    if cleaned:
                        raw_auto[param_name] = cleaned
            if raw_auto:
                parsed["delay_auto"] = raw_auto
        # Ableton native Utility automation (raw values, not normalized)
        if parsed.get("type") == "Utility":
            auto_targets = parsed.get("auto_targets", {})
            raw_auto = {}
            for param_name, at_id in auto_targets.items():
                if at_id is None:
                    continue
                events = float_index.get(at_id) or bool_index_auto.get(at_id)
                if events:
                    cleaned = sorted(((max(t, 0.0), v) for t, v in events), key=lambda e: e[0])
                    if cleaned:
                        raw_auto[param_name] = cleaned
            if raw_auto:
                parsed["utility_auto"] = raw_auto
    return parsed


def _parse_device_inner(dev_el: ET.Element) -> dict | None:
    tag = dev_el.tag

    # Third-party VST/AU
    if tag in ("PluginDevice", "AuPluginDevice", "Vst3PluginDevice", "VstPluginDevice"):
        return _parse_plugin_device(dev_el)

    # Native Ableton devices
    if tag == "Eq8":
        return _parse_eq8(dev_el)
    if tag == "Compressor2":
        return _parse_compressor(dev_el, "Compressor")
    if tag == "GlueCompressor":
        return _parse_glue_compressor(dev_el)
    if tag == "Gate":
        return _parse_gate(dev_el)
    if tag == "Limiter":
        return _parse_limiter(dev_el)
    if tag == "Saturator":
        return _parse_saturator(dev_el)
    if tag in ("Utility", "StereoGain"):  # StereoGain is the Ableton 12 tag for Utility
        return _parse_utility(dev_el)
    if tag == "Reverb":
        return _parse_reverb(dev_el)
    if tag in ("Delay", "SimplerDevice"):  # SimplerDevice skip
        if tag == "Delay":
            return _parse_delay(dev_el)
    if tag in ("Chorus", "Chorus2"):
        return _parse_chorus(dev_el)
    if tag == "AutoFilter":
        return _parse_auto_filter(dev_el)

    # Known native, generic parse
    if tag in ABLETON_NATIVE_DEVICES:
        return _parse_generic_device(dev_el, tag, ABLETON_NATIVE_DEVICES[tag])

    # Instruments and unknown — skip silently unless it's recognizable
    return None


def _parse_fx_rack(rack_el: ET.Element, automation_index: dict | None = None) -> list[dict]:
    """
    Flatten an AudioEffectGroupDevice (FX Rack) into a list of devices.
    The rack's own On/off state is applied to each child as a bypass override.
    Path: Branches/AudioEffectBranch/DeviceChain/AudioToAudioDeviceChain/Devices
    """
    on_el = rack_el.find("On/Manual")
    rack_enabled = _bool(on_el.get("Value") if on_el is not None else None, True)

    devices_el = rack_el.find(
        "Branches/AudioEffectBranch/DeviceChain/AudioToAudioDeviceChain/Devices"
    )
    if devices_el is None:
        return []

    result = []
    for child in devices_el:
        if child.tag == "AudioEffectGroupDevice":
            # Nested rack — recurse
            inner = _parse_fx_rack(child, automation_index)
            # If outer rack is bypassed, force all inner devices bypassed too
            # Rack bypass state intentionally NOT propagated here.
            # In Ableton, racks are often bypassed purely for clean stem export,
            # not because the effect is unwanted. All devices land enabled in Reaper.
            result.extend(inner)
        else:
            parsed = _parse_device(child, automation_index)
            if parsed is not None:
                result.append(parsed)
    return result


def _parse_device_chain(chain_el: ET.Element | None, automation_index: dict | None = None) -> list[dict]:
    if chain_el is None:
        return []
    devices = []
    devices_el = chain_el.find("DeviceChain/Devices") or chain_el.find("Devices")
    if devices_el is None:
        return []
    for child in devices_el:
        if child.tag == "AudioEffectGroupDevice":
            rack_devices = _parse_fx_rack(child, automation_index)
            for d in rack_devices:
                d["enabled"] = True
            devices.extend(rack_devices)
        else:
            parsed = _parse_device(child, automation_index)
            if parsed is not None:
                parsed["enabled"] = True
                devices.append(parsed)
    return devices


# ---------------------------------------------------------------------------
# Track parsing
# ---------------------------------------------------------------------------

def _parse_track(track_el: ET.Element, track_type: str) -> dict:
    name_el = track_el.find("Name/EffectiveName")
    # Use direct child iteration to avoid matching nested Color elements
    # (e.g. Color inside Name sub-elements) which may have no Value attribute
    color_el = None
    for _child in track_el:
        if _child.tag in ("Color", "ColorIndex") and _child.get("Value") is not None:
            color_el = _child
            break
    mute_el = track_el.find("MuteState/Manual") or track_el.find("TrackMuteState/Manual")
    solo_el = track_el.find("Solo")
    group_id_el = track_el.find("TrackGroupId")

    mixer_el = track_el.find("DeviceChain/Mixer")
    # For return tracks the structure may differ
    if mixer_el is None:
        mixer_el = track_el.find("Mixer")

    device_chain_el = track_el.find("DeviceChain")
    automation_index = _build_automation_index(track_el)
    devices = _parse_device_chain(device_chain_el, automation_index)

    # Volume automation — match by Volume's own AutomationTarget Id, same pattern
    # used for device bypass (On/AutomationTarget). Using the FIRST envelope found
    # on the track (old behavior) could grab automation for any parameter, not
    # necessarily Volume.
    vol_automation = []
    vol_target = mixer_el.find("Volume/AutomationTarget") if mixer_el is not None else None
    if vol_target is not None:
        vol_pid = vol_target.get("Id")
        auto_el = track_el.find("AutomationEnvelopes/Envelopes")
        if auto_el is not None and vol_pid is not None:
            for env in auto_el.findall("AutomationEnvelope"):
                target_el = env.find("EnvelopeTarget/PointeeId")
                if target_el is not None and target_el.get("Value") == vol_pid:
                    events = env.find("Automation/Events")
                    if events is not None:
                        for ev in events.findall("FloatEvent"):
                            vol_automation.append({
                                "time": _float(ev.get("Time"), 0.0),
                                "value": _float(ev.get("Value"), 1.0),  # linear gain
                                "curve": _float(ev.get("CurveControl1X"), 0.0),
                            })
                    break

    mixer = _parse_mixer(mixer_el)

    # Check mute at track level too
    if mute_el is not None:
        mixer["muted"] = _bool(mute_el.get("Value"), False)

    return {
        "id": track_el.get("Id", ""),
        "type": track_type,
        "name": name_el.get("Value") if name_el is not None else "Unnamed Track",
        "color_index": _int(color_el.get("Value") if color_el is not None else None, 0),
        "group_id": _int(group_id_el.get("Value") if group_id_el is not None else None, -1),
        "mixer": mixer,
        "devices": devices,
        "automation": vol_automation,
    }


# ---------------------------------------------------------------------------
# Main parser
# ---------------------------------------------------------------------------

def parse_als(als_path: str | Path) -> dict:
    als_path = Path(als_path)
    if not als_path.exists():
        raise FileNotFoundError(f"File not found: {als_path}")

    with gzip.open(als_path, "rb") as f:
        tree = ET.parse(f)
    root = tree.getroot()

    # Ableton version
    version = root.get("Creator", "Unknown")

    # BPM / tempo
    tempo_el = root.find(".//Tempo/Manual")
    tempo = _float(tempo_el.get("Value") if tempo_el is not None else None, 120.0)

    # Time signature
    num_el = root.find(".//TimeSignature/TimeSignatures/RemoteableTimeSignature/Numerator")
    den_el = root.find(".//TimeSignature/TimeSignatures/RemoteableTimeSignature/Denominator")
    time_sig_num = _int(num_el.get("Value") if num_el is not None else None, 4)
    time_sig_den = _int(den_el.get("Value") if den_el is not None else None, 4)

    tracks = []

    # Iterate ALL track types in document order — preserves Ableton's group/child structure.
    # Separate loops per tag type would break ordering (all AudioTracks first, etc.)
    _TRACK_TYPE_MAP = {
        "AudioTrack":  "audio",
        "MidiTrack":   "midi",
        "GroupTrack":  "group",
        "ReturnTrack": "return",
    }
    for el in root.iter():
        if el.tag in _TRACK_TYPE_MAP:
            track = _parse_track(el, _TRACK_TYPE_MAP[el.tag])
            track['export_index'] = len(tracks) + 1  # 1-based, matches Ableton stem export numbering
            tracks.append(track)

    # Master track
    master_el = root.find(".//MasterTrack")
    master = None
    if master_el is not None:
        master = _parse_track(master_el, "master")

    return {
        "source_file": str(als_path.name),
        "ableton_version": version,
        "tempo": tempo,
        "time_signature": f"{time_sig_num}/{time_sig_den}",
        "tracks": tracks,
        "master": master,
    }


if __name__ == "__main__":
    import sys
    import json

    if len(sys.argv) < 2:
        print("Usage: python als_parser.py <file.als> [output.json]")
        sys.exit(1)

    result = parse_als(sys.argv[1])
    output_path = sys.argv[2] if len(sys.argv) > 2 else sys.argv[1].replace(".als", "_parsed.json")
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)
    print(f"Parsed → {output_path}")
    print(f"  Tracks: {len(result['tracks'])}")
    print(f"  Tempo:  {result['tempo']} BPM")
