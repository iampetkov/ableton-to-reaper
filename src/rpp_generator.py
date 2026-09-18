"""
rpp_generator.py  —  Ableton → Reaper project generator

VST state chunks are derived from ground-truth Reaper 7.38/macOS-arm64 project files.
Each plugin has: fixed_header (never changes) + param_block (patched per instance).
"""

import math, json, struct, base64, zlib, wave
from pathlib import Path
from vst_db import VSTDatabase


def _get_wav_duration(wav_path: Path) -> float:
    """Read a WAV file's exact duration in seconds using its header (no decoding needed).
    Returns 0.0 if the file is missing or unreadable — caller should warn in that case."""
    try:
        with wave.open(str(wav_path), 'rb') as wf:
            frames = wf.getnframes()
            rate = wf.getframerate()
            return frames / float(rate) if rate else 0.0
    except Exception:
        return 0.0


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _patch(default_b64: str, patches: dict) -> str:
    """Clone default param block, overwrite float32 values at given param indices."""
    data = bytearray(base64.b64decode(default_b64))
    for idx, val in patches.items():
        struct.pack_into('<f', data, idx * 4, float(val))
    return base64.b64encode(bytes(data)).decode('ascii')

def _clamp(v, lo, hi):
    return max(lo, min(hi, v))

def _db_to_lin(db):
    return 10 ** (db / 20.0)

def _reaper_color(color_index: int) -> int:
    # Ableton Live 12 color palette (indices 0-69).
    # Sampled directly from Ableton's color picker screenshot — pixel-accurate.
    # Confirmed: idx 0=salmon, idx 1=orange, idx 6=spring green, 
    #            idx 8=light blue, idx 17=yellow, idx 20=teal/cyan
    ABLETON_PALETTE = [
        0xFB95A3, 0xFAA727, 0xCB9C2A, 0xF6F382, 0xBCFB00, 0x37FE2F, 0x35FFA4, 0x63FFED, 0x88C5FF, 0x5180E8, 0x8EA8FF, 0xDE64EA, 0xE653A4, 0xFFFEFF,  # 0-13
        0xFD3538, 0xF96A04, 0x99734C, 0xFFEF38, 0x8BFC64, 0x46BD09, 0x24C1B0, 0x36E8FF, 0x24A6F1, 0x1E7EBB, 0x8969E4, 0xBA74CA, 0xF53CD7, 0xCFCFCF,  # 14-27
        0xDA6A5F, 0xF7A575, 0xD2AE74, 0xEFFFAF, 0xD2E39C, 0xB9D171, 0x98C688, 0xCEFFE2, 0xCFF0F7, 0xBCBFE2, 0xCCBAE2, 0xB098E6, 0xE5DCE1, 0xADA9AA,  # 28-41
        0xC5938A, 0xBB8058, 0x98826B, 0xC0B96B, 0xA5BF00, 0x7DB246, 0x87C2BC, 0x9DB2C5, 0x89A4C2, 0x7F97C7, 0xA497B5, 0xBE9DBC, 0xC16E9C, 0x7C7A7D,  # 42-55
        0xA13A31, 0xAD502E, 0x7D5645, 0xE0C300, 0x82941C, 0x4BA029, 0x1B9D93, 0x206584, 0x123394, 0x2A55A4, 0x6951B3, 0xB550BA, 0xCC2573, 0x3D3F3C,  # 56-69
    ]
    rgb = ABLETON_PALETTE[color_index % len(ABLETON_PALETTE)]
    r = (rgb >> 16) & 0xFF
    g = (rgb >> 8) & 0xFF
    b = rgb & 0xFF
    return (r << 16) | (g << 8) | b | 0x01000000


# ─────────────────────────────────────────────────────────────────────────────
# Ground-truth VST state constants  (Reaper 7.38 / macOS-arm64)
# ─────────────────────────────────────────────────────────────────────────────

# ── ReaEQ ────────────────────────────────────────────────────────────────────
# Tag: VST: ReaEQ (Cockos)  reaeq.vst.dylib  1919247729<56535472656571726561657100000000>
# ReaEQ VST state encoding.
# All constants verified by byte-for-byte comparison with Reaper 7.38-saved RPP files.
#
# Structure (bytes):
#   0-47:   fixed prefix (magic, version, metadata)
#   48-51:  data length field = N*33 + 40
#   52-70:  fixed suffix of header (ends just before band data)
#   71+:    band structs (33 bytes each)
#   last 29: trailer
#
# The full header template (bytes 0-70) is taken directly from a Reaper-saved file.
# Only bytes 48-51 (length), 64-67 (num_bands), and 68-70 (slot_hint) are patched per file.
#
# Band struct layout (33 bytes, offset within struct):
#   [0]      always 0x00
#   [1-4]    enabled (int32: 1=on, 0=off)
#   [5-12]   freq (double, Hz)
#   [13-20]  gain (double, linear multiplier; 0dB = 1.0)
#   [21-28]  bandwidth (double, octaves)
#   [29-32]  flags: b29=0x01, b30=type_flag, b31=0x00, b32=0x00
#
# type_flag values (b30), confirmed from controlled Reaper test:
#   Bell=0x00, LowShelf=0x01, HighShelf=0x04, HighPass=0x03, LowPass=0x06, Notch=0x01

# Full header template bytes 0-70 (copied from Reaper-saved 6-band reference file)
_REAEQ_HEADER_TEMPLATE = bytes.fromhex(
    '71656572ee5eedfe020000000100000000000000020000000000000002000000'
    '010000000000000002000000000000000000000001000000000010002100000006000000080000'
)
# Trailer: last 29 bytes (same across all Reaper-saved ReaEQ files)
_REAEQ_TRAILER = bytes.fromhex('0001000000000000000000f03f00000000400200006b01000002000000')
_REAEQ_TAG = 'VST "VST: ReaEQ (Cockos)" reaeq.vst.dylib 0 "" 1919247729<56535472656571726561657100000000> ""'

# ReaEQ type encoding — confirmed by controlled byte-diff experiments.
#
# The type for each band is encoded in TWO places:
#   - byte[68] of the state = type code of band 1
#   - b30 of band N         = type code of band N+1
#
# Both positions use the same type code values:
#   LowShelf=0x00, HighShelf=0x01, LowPass=0x03, HighPass=0x04, Notch=0x06, Bell=0x08
#
# b30 of the last band is ignored by Reaper.
_REAEQ_TYPE_CODES = {
    'Bell':       0x08,
    'Low Shelf':  0x00,
    'High Shelf': 0x01,
    'High Cut':   0x03,  # LowPass in ReaEQ
    'Low Cut':    0x04,  # HighPass in ReaEQ
    'Notch':      0x06,
    'Tilt Shelf': 0x00,  # approximate as Low Shelf
}



def _ableton_q_to_reaper_bw(ableton_q: float, is_shelf: bool = False) -> float:
    """Convert Ableton Q to ReaEQ bandwidth in octaves.

    Shelves use a power-law Q scaling (Q_eff = 3.0 × Q^0.37) derived from spectral
    analysis and ear testing. ReaEQ's shelf BW is internally clamped at ~0.90 oct;
    high-Q shelves (Q > ~1.5) cannot be perfectly replicated but this formula gives
    the closest achievable match across the Q range.
    """
    import math
    q = max(ableton_q, 0.01)
    if is_shelf:
        q = 3.0 * (q ** 0.37)
    return (2.0 / math.log(2.0)) * math.asinh(1.0 / (2.0 * q))

# ReaEQ's bandwidth field range is 0.01–4.00 oct for all filter types.
# The Bell formula maps Ableton's default Q=0.7071 → 1.9 oct ≈ 2.0 (ReaEQ default).
# Very low Ableton Q values (e.g. Q=0.1 → 6.67 oct) exceed ReaEQ's 4.00 max and are clamped.
_REAEQ_BW_MAX = 4.0
_REAEQ_BW_MIN = 0.01

_REAEQ_SHELF_MODES = {'High Shelf', 'Low Shelf', 'Tilt Shelf'}

def _make_reaeq_state(bands: list) -> tuple:
    """Build a ReaEQ VST binary state chunk.

    Returns (base64_str, clamped_warnings) where clamped_warnings is a list of
    human-readable strings for bands whose bandwidth was clamped to ReaEQ's range.

    Type encoding (confirmed by byte-diff experiments):
      - byte[68]       = type code of band 1
      - b30 of band N  = type code of band N+1  (b30 of last band is ignored)
    """
    n = len(bands)
    type_codes = [_REAEQ_TYPE_CODES.get(b.get('mode', 'Bell'), 0x08) for b in bands]
    clamped_warnings = []

    band_data = bytearray()
    for i, b in enumerate(bands):
        freq       = float(b.get('freq', 1000.0))
        gain_lin   = _db_to_lin(b.get('gain_db', 0.0))
        mode       = b.get('mode', 'Bell')
        ableton_q  = float(b.get('q', 0.7071067811865476))
        bw         = _ableton_q_to_reaper_bw(ableton_q, is_shelf=(mode in _REAEQ_SHELF_MODES))
        if bw > _REAEQ_BW_MAX:
            clamped_warnings.append(
                f'Band {i+1} ({mode}, {freq:.0f}Hz): Q={ableton_q:.2f} → {bw:.2f} oct '
                f'clamped to {_REAEQ_BW_MAX} oct (ReaEQ maximum)'
            )
            bw = _REAEQ_BW_MAX
        reaper_q = max(_REAEQ_BW_MIN, bw)
        is_enabled = 1 if b.get('enabled', True) else 0
        # b30 = type code of the NEXT band (ignored for last band)
        next_type  = type_codes[i + 1] if i + 1 < n else 0x00
        band_data += struct.pack('<B',    0x00)                          # [0]    always 0
        band_data += struct.pack('<I',    is_enabled)                    # [1-4]  enabled
        band_data += struct.pack('<d',    freq)                          # [5-12] freq Hz
        band_data += struct.pack('<d',    gain_lin)                      # [13-20] gain linear
        band_data += struct.pack('<d',    reaper_q)                      # [21-28] bandwidth oct
        band_data += struct.pack('<BBBB', 0x01, next_type, 0x00, 0x00)  # [29-32] flags

    # Build header: template (71 bytes) with 3 patched fields
    data = bytearray(_REAEQ_HEADER_TEMPLATE)
    struct.pack_into('<I',   data, 48, n * 33 + 40)          # data length
    struct.pack_into('<I',   data, 64, n)                     # num_bands
    struct.pack_into('<BBB', data, 68, type_codes[0], 0, 0)  # byte[68] = type of band 1
    data += band_data
    data += _REAEQ_TRAILER
    return base64.b64encode(bytes(data)).decode('ascii'), clamped_warnings

def _wrap_vst(tag: str, state_b64: str, enabled: bool, chunk_trailer: str = 'AAAQAAAA', wet: float = 1.0) -> str:
    """Wrap a VST state into an RPP FX block, splitting state into 76-char lines.
    Order matches Reaper 7.38: BYPASS → <VST block> → WET (if not 100%) → PRESETNAME → FLOATPOS → FXID → WAK

    wet: 0.0–1.0. Omitted when 1.0 (Reaper default). Written as 'WET <value> 0' otherwise.
    """
    lines = [f'      BYPASS {0 if enabled else 1} 0 0']
    lines.append(f'      <{tag}')
    for i in range(0, len(state_b64), 76):
        lines.append(f'        {state_b64[i:i+76]}')
    if chunk_trailer:
        lines.append(f'        {chunk_trailer}')
    lines.append('      >')
    if wet < 0.9999:
        lines.append(f'      WET {wet:.6f} 0')
    lines.append('      PRESETNAME 0')
    lines.append('      FLOATPOS 0 0 0 0')
    lines.append('      FXID {00000000-0000-0000-0000-000000000000}')
    lines.append('      WAK 0 0')
    return '\n'.join(lines)


def _wrap_vst_waves(tag: str, c1_b64: str, state_b64: str, preset_b64: str, enabled: bool) -> str:
    """Waves WaveShell multi-chunk RPP block: C1, state, and preset name are separate b64 lines."""
    lines = [f'      BYPASS {0 if enabled else 1} 0 0',
             f'      <{tag}',
             f'        {c1_b64}']
    for i in range(0, len(state_b64), 76):
        lines.append(f'        {state_b64[i:i+76]}')
    lines.append(f'        {preset_b64}')
    lines += ['      >', '      PRESETNAME 0',
              '      FLOATPOS 0 0 0 0',
              '      FXID {00000000-0000-0000-0000-000000000000}',
              '      WAK 0 0']
    return '\n'.join(lines)


def _make_bypass_parmenv(events: list, fx_name: str = 'FX') -> str:
    """Build a PARMENV 16:bypass block from (time_seconds, enabled) tuples.
    Reaper's bypass envelope value: 0 = active (not bypassed), 1 = bypassed.
    Each Ableton step transition becomes two Reaper points at the same time
    (end of old state, start of new state) to create an instant step, matching
    how Reaper itself writes step automation (confirmed from reference RPP).
    LANEHEIGHT 121 (not 0) keeps the lane visibly expanded in the track panel —
    a height of 0 collapses it, which defeats the purpose of showing automation
    to a collaborator who needs to see it at a glance."""
    lines = [f'      <PARMENV 16:bypass 0 1 0.5 "Bypass / {fx_name}"',
             '        ACT 1 -1', '        VIS 1 1 1', '        LANEHEIGHT 121 0',
             '        ARM 1', '        DEFSHAPE 1 -1 -1']
    prev_val = None
    for t, enabled in events:
        val = 0 if enabled else 1   # 0=active, 1=bypassed
        if prev_val is not None and prev_val != val:
            lines.append(f'        PT {t:.6f} {prev_val} 1')
        lines.append(f'        PT {t:.6f} {val} 1')
        prev_val = val
    lines.append('      >')
    return '\n'.join(lines)

def _encode_reaeq(eq: dict) -> tuple:
    bands = eq.get('bands', [])
    state, clamped_warnings = _make_reaeq_state(bands)
    # Compute disabled-band bitmask for the AAAQAAAA chunk.
    # byte[2] of the 6-byte chunk = bitmask where bit N = band N+1 disabled.
    disabled_mask = 0
    for b in bands:
        if not b.get('enabled', True):
            disabled_mask |= (1 << b['index'])
    chunk_bytes = bytes([0x00, 0x00, disabled_mask, 0x00, 0x00, 0x00])
    chunk_trailer = base64.b64encode(chunk_bytes).decode('ascii')
    return _wrap_vst(_REAEQ_TAG, state, eq.get('enabled', True), chunk_trailer=chunk_trailer), clamped_warnings


# ── ReaComp ───────────────────────────────────────────────────────────────────
# Params in C2 chunk (float32, index = offset/4):
#   [2] threshold  norm = db / -200         range -200..0 dB  (e.g. -20dB → 0.10)
#   [3] ratio      norm = 1/(ratio*8+1)     (e.g. 4:1 → 1/33 = 0.0303)
#   [4] attack     norm = ms / 500          range 0..500ms    (e.g. 10ms → 0.020)
#   [5] release    norm = ms / 5000         range 0..5000ms   (e.g. 100ms → 0.020)
#   [8] makeup     linear multiplier        0dB = 1.0
#  [15] knee       norm = db / 60           range 0..60dB
# All confirmed by decoding a known RPP (threshold=-20, ratio=4, attack=10, release=100)
_REACOMP_C1 = 'bWNlcu9e7f4EAAAAAQAAAAAAAAACAAAAAAAAAAQAAAAAAAAACAAAAAAAAAACAAAAAQAAAAAAAAACAAAAAAAAAFwAAAAAAAAAAAAQAA=='
_REACOMP_C2 = '776t3g3wrd4AAIA/ED74PKabxDsK16M8AAAAAAAAAAAAAIA/AAAAAAAAAAAAAAAAnNEHMwAAgD8AAAAAzcxMPQAAAAAAAAAAAAAAAAAAgD4AAAAAAAAAAAAAAAA='
_REACOMP_TAG = 'VST "VST: ReaComp (Cockos)" reacomp.vst.dylib 0 "" 1919247213<5653547265636D726561636F6D700000> ""'

def _encode_reacomp(comp: dict) -> str:
    ratio = max(comp.get('ratio', 4.0), 1.0)
    c2 = _patch(_REACOMP_C2, {
        2:  _clamp(comp.get('threshold_db', -20.0) / -200.0, 0, 1),
        3:  _clamp(1.0 / (ratio * 8.0 + 1.0), 0, 1),
        4:  _clamp(comp.get('attack_ms', 10.0) / 500.0, 0, 1),
        5:  _clamp(comp.get('release_ms', 100.0) / 5000.0, 0, 1),
        8:  _db_to_lin(comp.get('makeup_gain_db', 0.0)),
        # [15] = RMS size (default 0.05 = 5ms) — leave at default, not patched
    })
    return _wrap_vst(_REACOMP_TAG, base64.b64encode(
        base64.b64decode(_REACOMP_C1) + base64.b64decode(c2)
    ).decode(), comp.get('enabled', True))


# ── ReaGate ───────────────────────────────────────────────────────────────────
# Params in chunk2:
#   [2] threshold   norm = (db + 60) / 60
#   [3] attack      norm = ms / 166.7
#   [4] release     norm = ms / 5000
#  [11] return(hysteresis) same scale as threshold
_REAGATE_C1 = 'dGdlcu9e7f4EAAAAAQAAAAAAAAACAAAAAAAAAAQAAAAAAAAACAAAAAAAAAACAAAAAQAAAAAAAAACAAAAAAAAAFwAAAAAAAAAAAAQAA=='
_REAGATE_C2 = '776t3g3wrd6c0QczppvEOwrXozwAAAAAAAAAAAAAgD8AAAAAAAAAAAAAAACc0QczAACAP5zRBzMAAIA/AAAAAAAAAAAAAAAALBYLPwAAAAAAAAAAAAAAAAAAAAA='
_REAGATE_TAG = 'VST "VST: ReaGate (Cockos)" reagate.vst.dylib 0 "" 1919248244<56535472656774726561676174650000> ""'

def _encode_reagate(gate: dict) -> str:
    # Confirmed normalizations from reference RPPs (float32, index = byte_offset/4 in C2):
    # [2]  threshold:  linear amplitude = 10^(db/20)
    # [3]  attack:     ms / 500   (max 500ms → 1.0)
    # [4]  release:    ms / 5000  (max 5000ms → 1.0)
    # [5]  hold:       power curve (ms/10001.32)^0.34948
    # [6]  pre-open:   power curve (ms/91.29)^3.825 — maps to ReaGate Pre-Open (max ~250ms)
    # [14] hysteresis: linear amplitude of close threshold = 10^(close_db/20)
    #                  Ableton close = threshold_db - return_offset_db
    # [20] invert:     2.0 = on, 0.0 = off
    # Floor (Ableton "Gain"): no direct equivalent in ReaGate — not mapped
    # LookAhead enum → Pre-Open ms (mapped via [6])

    import math

    thresh_db  = gate.get('threshold_db', -40.0)
    thresh_lin = 10 ** (thresh_db / 20.0)

    attack_ms    = gate.get('attack_ms', 1.0)
    release_ms   = gate.get('release_ms', 50.0)
    hold_ms      = gate.get('hold_ms', 1.0)
    return_offset = gate.get('return_offset_db', 0.0)

    hold_norm = _clamp(hold_ms / 1000.0, 0, 1.5)  # linear ms/1000, confirmed from RPP

    # Pre-open [index 5]: exact values confirmed from reference RPPs
    _LOOKAHEAD_NORM = {0.0: 0.0, 1.5: 0.006, 10.0: 0.04}
    pre_norm = _LOOKAHEAD_NORM.get(gate.get('lookahead_ms', 0.0), 0.0)

    # Hysteresis [index 14]: relative attenuation below threshold
    # return_offset=0dB → 1.0 (no gap), return_offset=10dB → 0.316
    hyst_norm = 10 ** (-return_offset / 20.0)

    invert = 2.0 if gate.get('flip', False) else 0.0

    c2 = _patch(_REAGATE_C2, {
        2:  _clamp(thresh_lin, 0, 4.0),
        3:  _clamp(attack_ms  / 500,  0, 1),
        4:  _clamp(release_ms / 5000, 0, 1),
        5:  pre_norm,
        6:  hold_norm,
        14: _clamp(hyst_norm, 0, 4.0),
        20: invert,
    })
    warnings = []
    if gate.get('floor_db', -75.0) > -74.0:
        warnings.append('Floor not mappable in ReaGate')
    return _wrap_vst(_REAGATE_TAG, base64.b64encode(
        base64.b64decode(_REAGATE_C1) + base64.b64decode(c2)
    ).decode(), gate.get('enabled', True))


# ── ReaDelay ──────────────────────────────────────────────────────────────────
# Params in C2 chunk (float32, index = offset/4) — confirmed from known RPP:
#   [6]  tap enabled (1.0)
#   [7]  ??? (1.0 default)
#   [9]  tap enabled again (1.0)
#   [10] L HP filter  norm = hz / 20000   (200Hz → 0.01)
#   [11] feedback     0..1 linear (0.0078 = floor/-inf dB)
#   [13] L LP filter  norm = hz / 20000   (8000Hz → 0.40)
#   [14] HP filter    norm = hz / 20000   (same as [10])
#   [15] stereo width (1.0 = full)
#   [16] volume       (1.0 = unity)
#   [17] volume again (1.0)
#   [18] wet          linear amplitude    (0.5 = -6dB)
#   L time: [6] in C2 maps to Length(time) = ms/500 (250ms → 0.5)
# Note: ReaDelay C2 also encodes musical length — we use time mode only.
_READELAY_C1 = 'bGRlcu5e7f4CAAAAAQAAAAAAAAACAAAAAAAAAAIAAAABAAAAAAAAAAIAAAAAAAAATAAAAAEAAAAAABAA'
_READELAY_C2 = 'AAAAAAAAAAABAAAALAAAAAIAAAAAAAAAQwIAPwAAgD8AAAAAAACAPwAAAAAAAAA8nNEHMwAAgD8AAAAAAACAPwAAgD8AAIA/AAAAPw=='
_READELAY_TAG = 'VST "VST: ReaDelay (Cockos)" readelay.vst.dylib 0 "" 1919247468<5653547265646C72656164656C617900> ""'

def _encode_readelay(delay: dict, bpm: float = 120.0) -> str:
    # For synced delays, convert sixteenth note count to ms using project BPM.
    # ReaDelay only has a time-in-ms mode; we convert beat divisions to ms.
    ms_per_sixteenth = (60000.0 / bpm) / 4.0
    if delay.get('l_synced', False):
        l_ms = delay.get('l_sixteenths', 2) * ms_per_sixteenth
    else:
        l_ms = delay.get('l_time_ms', 250.0)
    if delay.get('r_synced', False):
        r_ms = delay.get('r_sixteenths', 2) * ms_per_sixteenth
    else:
        r_ms = delay.get('r_time_ms', delay.get('l_time_ms', 250.0))
    # Feedback: Ableton stores 0..0.95 linear; ReaDelay stores same range, floor = 0.0078
    feedback_raw = delay.get('feedback', 0.5)
    feedback_norm = max(float(feedback_raw), 0.0078)
    # HP/LP from Ableton's delay filter (bandpass center+BW → HP/LP approximation)
    # Ableton Filter_Frequency is bandpass center; we use it as LP cutoff.
    # For HP we use 0 (disabled) unless filter_on and we can derive it from BW.
    import math as _math
    filter_on = delay.get('filter_on', False)
    if filter_on:
        # Ableton stores bandpass center freq + bandwidth in octaves
        # Convert to HP and LP cutoffs for ReaDelay
        center = delay.get('filter_freq', 1000.0)  # bandpass center Hz
        bw_oct = delay.get('filter_bw', 8.0)
        hp_hz = _clamp(center / (2 ** (bw_oct / 2)), 0, 20000)
        lp_hz = _clamp(center * (2 ** (bw_oct / 2)), 0, 20000)
        # [10] uses scale /8000, [13] and [14] use scale /20000
        hp_norm_8k  = _clamp(hp_hz / 8000.0, 0, 1)
        hp_norm_20k = _clamp(hp_hz / 20000.0, 0, 1)
        lp_norm_20k = _clamp(lp_hz / 20000.0, 0, 1)
    else:
        hp_norm_8k  = 0.0
        hp_norm_20k = 0.0
        lp_norm_20k = 1.0
    wet = _clamp(delay.get('dry_wet', 0.5), 0, 1)
    c2 = _patch(_READELAY_C2, {
        6:  _clamp(l_ms / 500.0, 0, 1),
        8:  0.0,   # pan = center (always hardcoded; never inherit from track pan)
        10: hp_norm_8k,
        11: feedback_norm,
        13: lp_norm_20k,
        14: hp_norm_20k,
        18: wet,
    })
    return _wrap_vst(_READELAY_TAG, base64.b64encode(
        base64.b64decode(_READELAY_C1) + base64.b64decode(c2)
    ).decode(), delay.get('enabled', True))



# ── MDelay (MeldaProduction) ──────────────────────────────────────────────────
# State format: 68-byte VST3 header + zlib-compressed binary blob
# Binary blob format: null-terminated strings with type-prefixed values:
#   'd' prefix = little-endian double
#   's' prefix = null-terminated string
#   '1' prefix = single byte bool
# Key parameters:
#   FilterMode:    string "Feedback filter" or "Input filter"
#   MinFrequency:  log10(hp_hz)   — HP cutoff
#   MaxFrequency:  log10(lp_hz)   — LP cutoff
#   feedback:      sqrt(linear)   — Tap 1 feedback amplitude
#   gain:          sqrt(linear)   — Tap 1 output gain
#   delay:         seconds        — Tap 1 delay time
#   tap1:          bool           — Tap 2 enabled
#   feedback1/gain1/delay1        — Tap 2 params (same format)
# All confirmed from decoding MDelay.RPP with known settings.
_MDELAY_HEADER = bytes.fromhex('3910bf38ee5eedfe020000000100000000000000020000000000000002000000010000000000000002000000000000001004000001000000000010000002000001000000')
_MDELAY_TAG = 'VST "VST3: MDelay (MeldaProduction)" MDelay.vst3 0 "" 952045625{4D656C646170726F6778373667783736} ""'
_MDELAY_REF_HEX = '3910bf38ee5eedfe02000000010000000000000002000000000000000200000001000000000000000200000000000000100400000100000000001000000200000100000078da6591cd4a033110c7a7de3c89f802855e85b256912258b7db2e140c162abad774336e6363529314aca0072f822fe2c197f005c4ab4f20e2c527109db42a55e736bff9f8cf07b06696b1162a3e71e8bdd48583b8025129aea45279b4cc080497228a3ecf87e5a329a41426756af1748c3a9f8068bcad1c5f0d167688f3b3397effb0b57d5d5f227ef4d501c4cdddcbebc5ed7323ae145cea795f843140bc7f047b24e0f9289acef25d1dfd2d8ffed5132941b0a7467c80d649a3611d169721669d56a76b4d61f94932e0bac0b6e67d851041fc0b27dc6361ac3ca74529d616d21bdb23175cbdb6b9ba11d5204e8cf6d6284502b32e22a432a4e3b884381f39143df2d08405ba6a5c48bd6f8cea73fb130f11bad76ebad754261f4e25a27236ebb206d9a1147ec020eb99b1cd314c89b3fbd39b48ae5aad5e7e02bb96a0e400000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000200000000000078da6591cd4a033110c7a7de3c89f802855e85b256912258b7db2e140c162abad774336e6363529314aca0072f822fe2c197f005c4ab4f20e2c527109db42a55e736bff9f8cf07b06696b1162a3e71e8bdd48583b8025129aea45279b4cc080497228a3ecf87e5a329a41426756af1748c3a9f8068bcad1c5f0d167688f3b3397effb0b57d5d5f227ef4d501c4cdddcbebc5ed7323ae145cea795f843140bc7f047b24e0f9289acef25d1dfd2d8ffed5132941b0a7467c80d649a3611d169721669d56a76b4d61f94932e0bac0b6e67d851041fc0b27dc6361ac3ca74529d616d21bdb23175cbdb6b9ba11d5204e8cf6d6284502b32e22a432a4e3b884381f39143df2d08405ba6a5c48bd6f8cea73fb130f11bad76ebad754261f4e25a27236ebb206d9a1147ec020eb99b1cd314c89b3fbd39b48ae5aad5e7e02bb96a0e400000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000'


def _build_mdelay_blob(filter_mode, min_hz, max_hz,
                        tap1_fb, tap1_gain, tap1_delay_s,
                        tap2_enabled, tap2_fb, tap2_gain, tap2_delay_s):
    import math as _m, struct as _s
    def _str(t): return t.encode('ascii') + b'\x00'
    def _pdbl(n, v): return b'A#' + _str(n) + b'd' + _s.pack('<d', v)
    def _pstr(n, v): return b'A#' + _str(n) + b's' + _str(v)
    def _pbool(n, v): return b'A#' + _str(n) + b'1' + bytes([int(bool(v))])
    def _sqrt(x): return _m.sqrt(max(float(x), 0.0))

    return (
        b'\x00' + _str('MBXXMDelaysettings') +
        b'A#\x001\x01' +
        _pstr('FilterMode', filter_mode) +
        _pdbl('MinFrequency', _m.log10(max(min_hz, 1.0))) +
        _pdbl('MaxFrequency', _m.log10(max(max_hz, 1.0))) +
        _pdbl('feedback', _sqrt(tap1_fb)) +
        _pdbl('gain', _sqrt(tap1_gain)) +
        _pdbl('delay', tap1_delay_s) +
        _pbool('tap1', tap2_enabled) +
        _pdbl('feedback1', _sqrt(tap2_fb)) +
        _pdbl('gain1', _sqrt(tap2_gain)) +
        _pdbl('delay1', tap2_delay_s)
    )


def _encode_mdelay(delay: dict, bpm: float = 120.0) -> str:
    """Encode Ableton Delay → MDelay by patching known offsets in the reference state blob.

    Approach: decompress the reference 448-byte blob, patch double values at their
    confirmed byte offsets, recompress, and rebuild the 1100-byte state.
    This is more reliable than rebuilding from scratch since MDelay requires the
    AVersion and other metadata fields to accept the state.

    Blob offsets (confirmed from reference RPP decode):
      [38]  FilterMode string value ('Feedback filter' or 'Input filter')
      [71]  MinFrequency = log10(hp_hz)
      [95]  MaxFrequency = log10(lp_hz)
      [115] feedback     = sqrt(tap1_linear)
      [131] gain         = sqrt(wet_linear)
      [148] delay        = tap1_delay_seconds
      [171] tap2_enabled = bool byte (0x01 or 0x00)
      [178] feedback1    = sqrt(tap2_linear)
      [195] gain1        = sqrt(wet_linear)
      [213] delay1       = tap2_delay_seconds
    """
    import zlib as _z, math as _m

    ms_per_sixteenth = (60000.0 / bpm) / 4.0
    l_ms = (delay.get('l_sixteenths', 2) * ms_per_sixteenth
            if delay.get('l_synced') else delay.get('l_time_ms', 250.0))
    r_ms = (delay.get('r_sixteenths', 2) * ms_per_sixteenth
            if delay.get('r_synced') else delay.get('r_time_ms', l_ms))

    fb      = max(float(delay.get('feedback', 0.5)), 0.0)
    wet     = _clamp(delay.get('dry_wet', 0.5), 0, 1)
    l_s     = l_ms / 1000.0
    r_s     = r_ms / 1000.0
    two_tap = abs(l_ms - r_ms) > 1.0

    filter_on = delay.get('filter_on', False)
    if filter_on:
        center = delay.get('filter_freq', 1000.0)
        bw_oct = delay.get('filter_bw', 8.0)
        hp_hz  = _clamp(center / (2 ** (bw_oct / 2)), 1, 20000)
        lp_hz  = _clamp(center * (2 ** (bw_oct / 2)), 1, 20000)
        fm_str = b'Feedback filter\x00'
    else:
        hp_hz, lp_hz = 1.0, 20000.0
        fm_str = b'Input filter\x00'

    # Decompress reference blob and patch values at known offsets
    ref_raw = bytes.fromhex(_MDELAY_REF_HEX)
    blob = bytearray(_z.decompress(ref_raw[68:387]))

    import struct as _s

    def _find_param(name):
        # Find 'A#<name>\x00' then return offset of the type byte after it
        key = b'A#' + name.encode() + b'\x00'
        idx = blob.find(key)
        if idx < 0: raise ValueError(f'MDelay param not found: {name}')
        return idx + len(key)  # points to type byte (d/s/1)

    def _patch_dbl(name, val):
        off = _find_param(name)
        assert blob[off] == 0x64, f'Expected double type for {name}'
        blob[off+1:off+9] = _s.pack('<d', val)

    def _patch_bool(name, val):
        off = _find_param(name)
        assert blob[off] == 0x31, f'Expected bool type for {name}'
        blob[off+1] = 1 if val else 0

    def _patch_str_param(name, new_str):
        off = _find_param(name)
        assert blob[off] == 0x73, f'Expected string type for {name}'
        end = blob.index(0, off+1)
        new_bytes = new_str if isinstance(new_str, bytes) else (new_str.encode() + b'\x00')
        blob[off+1:end+1] = new_bytes

    import struct as _st
    def _read_dbl(name):
        off = _find_param(name)
        return _st.unpack_from('<d', blob, off+1)[0] if off >= 0 else None
    def _pic(name, val, tol=1e-9):  # patch if changed
        cur = _read_dbl(name)
        if cur is None or abs(cur - val) >= tol: _patch_dbl(name, val)

    # Only patch FilterMode if it changed (string patching resizes blob)
    _fm_off = _find_param('FilterMode')
    _fm_end = blob.index(0, _fm_off+1)
    _fm_cur = blob[_fm_off+1:_fm_end]
    if _fm_cur != fm_str.rstrip(b'\x00'):
        _patch_str_param('FilterMode', fm_str)
    _pic('MinFrequency', _m.log10(hp_hz))
    _pic('MaxFrequency', _m.log10(lp_hz))
    _pic('feedback',     _m.sqrt(fb))
    _pic('gain',         _m.sqrt(wet))
    _pic('delay',        l_s)
    _patch_bool('tap1',  two_tap)
    _pic('feedback1',    _m.sqrt(fb))
    _pic('gain1',        _m.sqrt(wet))
    _pic('delay1',       r_s)

    # Recompress and rebuild 1100-byte state
    # Reuse original compressed bytes if unchanged (Melda is sensitive to byte identity)
    ref_blob1 = ref_raw[68:387]
    if bytes(blob) == _z.decompress(ref_blob1):
        compressed = ref_blob1
    else:
        compressed = _z.compress(bytes(blob), level=9)
    SEP  = b'\x02\x00\x00\x00\x00\x00'
    PAD1 = 581 - 68 - len(compressed)
    PAD2 = 1100 - 588 - len(compressed)
    assert PAD1 >= 0 and PAD2 >= 0, f'MDelay blob too large: {len(compressed)}'
    state_bytes = (
        ref_raw[:68]
        + compressed + b'\x00' * PAD1 + SEP
        + b'\x00'
        + compressed + b'\x00' * PAD2
    )
    assert len(state_bytes) == 1100, f'MDelay state size wrong: {len(state_bytes)}'
    return _wrap_vst(_MDELAY_TAG, base64.b64encode(state_bytes).decode(),
                     delay.get('enabled', True), chunk_trailer='')



# ── MCompressor (MeldaProduction) ─────────────────────────────────────────────
# State: 1123 bytes total. Two zlib blobs at offsets 84 and 603.
# Blob params: threshold=10^(dB/40), ratio=direct, release=seconds, attack=seconds
_MCOMP_REF_HEX = '41d2d734ee5eedfe0400000001000000000000000200000000000000040000000000000008000000000000000200000001000000000000000200000000000000100400000100000000001000000200000100000078da5d903d4e03311085870e0aa4a05c00292d525808450a449c25119158082442db4eb0d9b5f07a56b623050a44410982166e42cf11a838051740e0dd24223095fddea7373f10b5e3380a29cb8db0968c15ce499d586035089658cd0825d00ae02fcf45bdeeb19a4b3d9a92e2c02bbd835175f7dd8b069d24e05056a5c5ce84b192343460650d58d4dbeff50d2506b330459d888ec691121000fb2387e84442465e0b53781d2e1d9981ff826d6e6e6f349a3bc042d2ce9052bec1348597316a9c483d24522334a1b731b785f3cd229c1c768fdb8ace2fcba4609d1d9e0e72259d136576301bfbf6a9f5cfd99a39cb772d96a2ba4850eaa219660534e662ba7500b15f214ffd9ec4fda84764325410f7496a07acab30b16d081eeb7365b270b9ab85f79cbc5f24a727fd2cc993d5b761f5ebe3977ca8d76f7e00c66090d80000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000200000000000078da5d903d4e03311085870e0aa4a05c00292d525808450a449c25119158082442db4eb0d9b5f07a56b623050a44410982166e42cf11a838051740e0dd24223095fddea7373f10b5e3380a29cb8db0968c15ce499d586035089658cd0825d00ae02fcf45bdeeb19a4b3d9a92e2c02bbd835175f7dd8b069d24e05056a5c5ce84b192343460650d58d4dbeff50d2506b330459d888ec691121000fb2387e84442465e0b53781d2e1d9981ff826d6e6e6f349a3bc042d2ce9052bec1348597316a9c483d24522334a1b731b785f3cd229c1c768fdb8ace2fcba4609d1d9e0e72259d136576301bfbf6a9f5cfd99a39cb772d96a2ba4850eaa219660534e662ba7500b15f214ffd9ec4fda84764325410f7496a07acab30b16d081eeb7365b270b9ab85f79cbc5f24a727fd2cc993d5b761f5ebe3977ca8d76f7e00c66090d8000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000300010000000'
_MCOMP_TAG = 'VST "VST3: MCompressor (MeldaProduction)" MCompressor.vst3 0 "" 886559297{4D656C646170726F4D4165314D416531} ""'


def _encode_mcompressor(comp: dict) -> str:
    """Encode Ableton Compressor → MCompressor by patching reference blob.
    Uses original MCompressor.RPP state (threshold=-20, ratio=4, attack=10ms, release=100ms)
    as reference. Patches all values by name-search, inserts non-default params.
    """
    import zlib as _z, math as _m, struct as _s

    threshold_db = comp.get('threshold_db', -20.0)
    ratio        = max(comp.get('ratio', 4.0), 1.0)
    attack_ms    = comp.get('attack_ms', 10.0)
    release_ms   = comp.get('release_ms', 100.0)
    makeup_db    = comp.get('makeup_gain_db', 0.0)
    knee_db      = comp.get('knee_db', 0.0)

    ref_raw = bytes.fromhex(_MCOMP_REF_HEX)

    # Find blob1 end
    for _bs in range(50, 520):
        try:
            if len(_z.decompress(ref_raw[84:84+_bs])) > 400:
                _blob1_end = 84 + _bs; break
        except: pass

    blob = bytearray(_z.decompress(ref_raw[84:_blob1_end]))

    def _find(name):
        key = b'A#' + name.encode() + b'\x00'
        idx = blob.find(key)
        return (idx, idx + len(key)) if idx >= 0 else (-1, -1)

    def _patch_dbl(name, val):
        _, off = _find(name)
        assert off >= 0 and blob[off] == 0x64
        blob[off+1:off+9] = _s.pack('<d', val)

    def _insert_dbl(name, val):
        ins = blob.find(b'AVersion')
        if ins >= 0:
            blob[ins:ins] = b'A#' + name.encode() + b'\x00d' + _s.pack('<d', val)

    def _insert_str(name, val):
        ins = blob.find(b'AVersion')
        if ins >= 0:
            blob[ins:ins] = b'A#' + name.encode() + b'\x00s' + val.encode() + b'\x00'

    def _remove(name):
        idx, off = _find(name)
        if idx >= 0 and blob[off] == 0x64:
            del blob[idx:off+9]  # key + 'd' + 8-byte double

    def _remove_str(name):
        idx, off = _find(name)
        if idx >= 0 and blob[off] == 0x73:
            end = blob.index(0, off+1)
            del blob[idx:end+1]

    # Patch core params (always present in reference)
    _patch_dbl('threshold', 10 ** (threshold_db / 40.0))
    _patch_dbl('ratio',     ratio)
    _patch_dbl('release',   release_ms / 1000.0)

    # Attack: only in blob if non-default (ref has attack=10ms)
    if abs(attack_ms - 10.0) > 0.5:
        idx, off = _find('attack')
        if idx >= 0: _patch_dbl('attack', attack_ms / 1000.0)
        else:        _insert_dbl('attack', attack_ms / 1000.0)

    # Output gain: insert if non-zero, remove if zero
    if abs(makeup_db) > 0.01:
        idx, off = _find('outputgain')
        if idx >= 0: _patch_dbl('outputgain', makeup_db)
        else:        _insert_dbl('outputgain', makeup_db)
    else:
        _remove('outputgain')  # ensure not present (default=0dB)

    # Knee: insert if non-zero
    if knee_db > 0.1:
        idx, _ = _find('kneemode')
        if idx >= 0: pass  # already Soft in blob
        else: _insert_str('kneemode', 'Soft')
        kneesize = min(knee_db / 18.0, 1.0)  # Ableton max=18dB → MComp 100%
        idx2, off2 = _find('kneesize')
        if idx2 >= 0: _patch_dbl('kneesize', kneesize)
        else: _insert_dbl('kneesize', kneesize)
    else:
        _remove_str('kneemode')
        _remove('kneesize')

    # Rebuild state
    ref_blob1 = ref_raw[84:_blob1_end]
    compressed = ref_blob1 if bytes(blob) == _z.decompress(ref_blob1) else _z.compress(bytes(blob), level=9)
    SEP = b'\x02\x00\x00\x00\x00\x00'
    PAD1 = 597 - 84 - len(compressed)
    PAD2 = 1116 - 604 - len(compressed)
    assert PAD1 >= 0 and PAD2 >= 0, f'MComp blob too large: {len(compressed)}'
    state_bytes = (
        ref_raw[:84]
        + compressed + b'\x00' * PAD1 + SEP
        + b'\x00'
        + compressed + b'\x00' * PAD2
        + ref_raw[-7:]
    )
    assert len(state_bytes) == 1123, f'MComp state wrong: {len(state_bytes)}'
    wet = _clamp(comp.get('dry_wet', 1.0), 0, 1)
    return _wrap_vst(_MCOMP_TAG, base64.b64encode(state_bytes).decode(),
                     comp.get('enabled', True), chunk_trailer='', wet=wet)


# ── MUtility ──────────────────────────────────────────────────────────────────
# PARKED — see HANDOFF.md "Known limitations".
# Ableton's Utility (StereoGain) → Melda MUtility mapping is NOT implemented.
# Investigation found that MUtility's VST3 state blob has an undiagnosed buffer
# constraint: zlib-compressed param blobs above ~321 bytes (the size of the
# original reference RPP's blob) cause Reaper to crash inside Melda's
# LoadMBXCompressed function, regardless of total state size or padding scheme.
# Compressed size varies near-randomly with parameter VALUES (not which params
# are set), so no value-rounding or precision strategy reliably avoids it.
# Tested extensively: forced 1123-byte total (matching MCompressor's pattern),
# dynamic total, various tail-padding schemes — all either crash or silently
# fall back to default values once the compressed blob exceeds ~321 bytes.
# Until this buffer limit is understood, Ableton's Utility device is left
# unmapped (falls through to the "unsupported device" report entry).


# Params in chunk2:
#   [6]  wet/dry  norm = 0..1
# Most reverb character params are fixed (room IR etc.) — we just set wet level
_REAVERB_C1 = 'YnZlcu5e7f4CAAAAAQAAAAAAAAACAAAAAAAAAAIAAAABAAAAAAAAAAIAAAAAAAAAKAAAAAEAAAAAABAA'
_REAVERB_C2 = 'AAAQwcybgD4AAIA/AAAAAAAAgD8AAIA/AAAAPwAAgD8AAIA/AAAAQA=='
_REAVERB_TAG = 'VST "VST: ReaVerb (Cockos)" reaverb.vst.dylib 0 "" 1919252066<56535472657662726561766572620000> ""'

def _encode_reaverb(rev: dict) -> str:
    c2 = _patch(_REAVERB_C2, {
        6: _clamp(rev.get('dry_wet', 0.3), 0, 1),
    })
    return _wrap_vst(_REAVERB_TAG, base64.b64encode(
        base64.b64decode(_REAVERB_C1) + base64.b64decode(c2)
    ).decode(), rev.get('enabled', True))


# ── ReaLimit ──────────────────────────────────────────────────────────────────
# Params in chunk2:
#   [0] ceiling  norm = ceiling_db / 0... actually default is 0.0 at 0dBFS
#   Stored as actual dB value (not normalized) based on default=0.0
_REALIMIT_C1 = 'dG1scu5e7f4CAAAAAQAAAAAAAAACAAAAAAAAAAIAAAABAAAAAAAAAAIAAAAAAAAAMAAAAAEAAAAAABAA'
_REALIMIT_C2 = 'AwAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAgAAAAAAAAAAAAAAAAAAAD+fduMQw8Y/'
_REALIMIT_TAG = 'VST "VST: ReaLimit (Cockos)" realimit.vst.dylib 0 "" 1919708532<565354726C6D747265616C696D697400> ""'

def _encode_realimit(lim: dict) -> str:
    c2 = _patch(_REALIMIT_C2, {
        0: lim.get('ceiling_db', 0.0),   # stored as actual dB
    })
    return _wrap_vst(_REALIMIT_TAG, base64.b64encode(
        base64.b64decode(_REALIMIT_C1) + base64.b64decode(c2)
    ).decode(), lim.get('enabled', True))


# ── JS plugins (already work, use PARM syntax) ────────────────────────────────

def _js(name: str, enabled: bool, parms: list) -> str:
    parm_str = ' '.join(f'{p:.6f}' if isinstance(p, float) else str(p) for p in parms)
    # Pad to 64 params with dashes
    pad = ' -' * max(0, 64 - len(parms))
    return '\n'.join([
        f'      <JS {name} ""',
        f'      FLOATPOS 0 0 0 0',
        f'      FXID {{00000000-0000-0000-0000-000000000000}}',
        f'      PARM {parm_str}{pad}',
        '      >',
        f'      BYPASS {0 if enabled else 1} 0 0',
    ])

def _encode_js_saturator(sat: dict) -> str:
    drive = _clamp((sat.get('drive_db', 0.0) + 24) / 48, 0, 1)
    output = _clamp((sat.get('output_gain_db', 0.0) + 24) / 48, 0, 1)
    return _js('Liteon/Saturation', sat.get('enabled', True),
               [drive, output, float(sat.get('dry_wet', 1.0))])

def _encode_js_utility(util: dict) -> str:
    gain_norm = _clamp((util.get('gain_db', 0.0) + 36) / 72, 0, 1)
    pan_norm  = (util.get('pan', 0.0) + 1.0) / 2.0
    en = util.get('enabled', True) and not util.get('mute', False)
    return _js('utility/volume_pan', en, [gain_norm, pan_norm])

# MUtility insertion: NO state chunk written at all. Reaper instantiates the
# plugin fresh with its own factory defaults — this is the safest possible
# insertion since Melda never has to parse a state blob on load, sidestepping
# the buffer-size crash entirely (see HANDOFF.md "Known limitations").
# Values must be set by hand; the migration report tells you what to set.
_MUTILITY_TAG = 'VST "VST3: MUtility (MeldaProduction)" MUtility.vst3 0 "" 1423054497{4D656C646170726F4D7574694D757469} ""'

_MUTILITY_C1 = 'a116d254ee5eedfe0400000001000000000000000200000000000000040000000000000008000000000000000200000001000000000000000200000000000000100400000100000000001000'

def _encode_mutility_blank(util: dict) -> str:
    state_b64 = base64.b64encode(bytes.fromhex(_MUTILITY_C1)).decode()
    return _wrap_vst(_MUTILITY_TAG, state_b64, util.get('enabled', True), chunk_trailer='')


_ABS_UTILITY_C1   = 'a8425a7aee5eedfe020000000100000000000000020000000000000002000000010000000000000002000000000000005a02000001000000ffff10004a02000001000000'
_ABS_UTILITY_TAG  = 'VST "VST3: Absolute Utility (Internal)" "Absolute Utility.vst3" 0 "" 2052735656{ABCDEF019182FAEB4162735541625554} ""'
# JUCEPrivateData suffix appended by JUCE after the XML in getStateInformation output.
# Represents default (bypass off) state; identical across all instances.
_ABS_UTILITY_JUCE_SUFFIX = bytes.fromhex(
    '0000000000000000004a554345507269766174654461746100010142797061737300010103001d'
    '000000000000004a5543455072697661746544617461')
# Ableton ChannelMode → Absolute Utility channels (Ableton 1=Stereo vs Abs 0=Stereo)
_ABL_CH_TO_ABS = {0: 1, 1: 0, 2: 2, 3: 3}


def _abs_utility_norm(param: str, raw: float) -> float:
    """Convert a raw Ableton Utility value to Absolute Utility normalized [0,1]."""
    import math as _math
    if param == 'gain':
        db = _math.log10(max(raw, 1e-10)) * 20.0
        return _clamp((db + 70.0) / 105.0, 0.0, 1.0)
    if param == 'balance':
        return _clamp((raw * 50.0 + 50.0) / 100.0, 0.0, 1.0)
    if param == 'width':
        return _clamp(raw / 4.0, 0.0, 1.0)          # Ableton 0..2 → Abs 0..400%, norm=v/4
    if param == 'channel_mode':
        return _ABL_CH_TO_ABS.get(round(raw), 0) / 3.0
    if param == 'bass_mono_freq':
        return _clamp((raw - 50.0) / 450.0, 0.0, 1.0)
    return 1.0 if raw >= 0.5 else 0.0               # bool params


def _build_abs_utility_juce_blob(util: dict) -> bytes:
    """Build a JUCE copyXmlToBinary blob for Absolute Utility from Ableton Utility params."""
    import math as _math
    gain_lin  = util.get('gain_lin', 1.0)
    gain_db   = _math.log10(max(gain_lin, 1e-10)) * 20.0
    gain_db   = _clamp(gain_db, -70.0, 35.0)
    balance   = util.get('pan', 0.0) * 50.0                       # -1..1 → -50..50%
    width     = util.get('width', 1.0) * 100.0                    # 0..2  → 0..200%
    channels  = float(_ABL_CH_TO_ABS.get(util.get('channel_mode', 1), 0))
    phase_l   = 1.0 if util.get('phase_l', False) else 0.0
    phase_r   = 1.0 if util.get('phase_r', False) else 0.0
    mono      = 1.0 if util.get('mono', False) else 0.0
    bass_mono = 1.0 if util.get('bass_mono', False) else 0.0
    bmf       = float(util.get('bass_mono_freq', 120.0))
    mute      = 1.0 if util.get('mute', False) else 0.0
    dc_filter = 1.0 if util.get('dc_filter', False) else 0.0

    # Params in alphabetical order (matches Reaper/JUCE convention)
    xml = (
        '<?xml version="1.0" encoding="UTF-8"?> <Parameters>'
        f'<PARAM id="balance" value="{balance}"/>'
        f'<PARAM id="bassMono" value="{bass_mono}"/>'
        f'<PARAM id="bassMonoFreq" value="{bmf}"/>'
        f'<PARAM id="bassMonoSolo" value="0.0"/>'
        f'<PARAM id="channels" value="{channels}"/>'
        f'<PARAM id="dcFilter" value="{dc_filter}"/>'
        f'<PARAM id="gain" value="{gain_db}"/>'
        f'<PARAM id="mono" value="{mono}"/>'
        f'<PARAM id="mute" value="{mute}"/>'
        f'<PARAM id="phaseL" value="{phase_l}"/>'
        f'<PARAM id="phaseR" value="{phase_r}"/>'
        f'<PARAM id="width" value="{width}"/>'
        '</Parameters>'
    )
    xml_bytes = xml.encode('utf-8') + b'\x00'
    magic = struct.pack('<I', 0x21324356)
    size  = struct.pack('<I', len(xml_bytes))
    return magic + size + xml_bytes + _ABS_UTILITY_JUCE_SUFFIX


def _encode_abs_utility(util: dict, bpm: float = 120.0) -> tuple[str, dict]:
    """Encode Ableton native Utility → Absolute Utility VST3 with full state + automation."""
    juce_blob = _build_abs_utility_juce_blob(util)
    c2  = juce_blob
    c1  = bytearray.fromhex(_ABS_UTILITY_C1)
    for patch_offset, addend in [(48, 8), (60, -8)]:
        struct.pack_into('<I', c1, patch_offset, len(c2) + addend)
    state     = bytes(c1) + c2
    state_b64 = base64.b64encode(state).decode()
    rpp = _wrap_vst(_ABS_UTILITY_TAG, state_b64, util.get('enabled', True),
                    chunk_trailer='AAAQAAAA')

    # Inject automation PARMENV blocks if any
    # Ableton param name → (Absolute Utility param index, Absolute Utility param display name)
    _PARAM_MAP = {
        'gain':           (0,  'Gain'),
        'balance':        (1,  'Balance'),
        'width':          (2,  'Width'),
        'mono':           (3,  'Mono'),
        'phase_l':        (4,  'Phase L'),
        'phase_r':        (5,  'Phase R'),
        'channel_mode':   (6,  'Channels'),
        'bass_mono':      (7,  'Bass Mono'),
        'bass_mono_freq': (8,  'Bass Mono Freq'),
        'mute':           (10, 'Mute'),
        'dc_filter':      (11, 'DC Filter'),
    }
    utility_auto = util.get('utility_auto', {})
    if utility_auto:
        param_automations = {}
        for abl_param, events in utility_auto.items():
            if abl_param not in _PARAM_MAP:
                continue
            idx, name = _PARAM_MAP[abl_param]
            norm_events = [(t, _abs_utility_norm(abl_param, v)) for t, v in events]
            param_automations[idx] = {'name': name, 'events': norm_events}
        if param_automations:
            rpp = _inject_param_automations(rpp, param_automations, bpm)

    warn = {'type': 'passthrough',
            'plugin_name': 'Absolute Utility',
            'message': "Utility → Absolute Utility (full parameter mapping)."}
    return rpp, warn


# C1 header extracted from a reference RPP (Absolute delay blank example.RPP).
# Offsets 48 and 60 are patched at runtime with (len(juce_blob)+8) and (len(juce_blob)-8).
_ABS_DELAY_C1  = '59078568ee5eedfe020000000100000000000000020000000000000002000000010000000000000002000000000000007403000001000000ffff10006403000001000000'
_ABS_DELAY_TAG = 'VST "VST3: Absolute Delay (Internal)" "Absolute Delay.vst3" 0 "" 1753548633{ABCDEF019182FAEB416273554162444C} ""'
# JUCEPrivateData suffix from the reference RPP — 8 trailing zeros distinguish it from
# the Absolute Utility suffix (which is the same but 8 bytes shorter).
_ABS_DELAY_JUCE_SUFFIX = bytes.fromhex(
    '0000000000000000004a554345507269766174654461746100010142797061737300010103001d'
    '000000000000004a5543455072697661746544617461' + '0000000000000000'
)


def _build_abs_delay_juce_blob(delay: dict, bpm: float = 120.0) -> bytes:
    """Build a JUCE copyXmlToBinary blob for Absolute Delay from an Ableton Delay dict."""
    sync_l = 1.0 if delay.get('l_synced', True) else 0.0
    sync_r = 1.0 if delay.get('r_synced', True) else 0.0
    # l_sixteenths / r_sixteenths are 0-based indices into beatDivValues (direct mapping)
    beat_div_l = float(max(0, min(7, int(delay.get('l_sixteenths', 2)))))
    beat_div_r = float(max(0, min(7, int(delay.get('r_sixteenths', 2)))))
    delay_time_l = _clamp(delay.get('l_time_ms', 375.0), 1.0, 5000.0)
    delay_time_r = _clamp(delay.get('r_time_ms', 375.0), 1.0, 5000.0)
    feedback = _clamp(delay.get('feedback', 0.5) * 100.0, 0.0, 95.0)
    filter_on = 1.0 if delay.get('filter_on', False) else 0.0
    filter_freq = _clamp(delay.get('filter_freq', 1000.0), 50.0, 18000.0)
    filter_width = _clamp(delay.get('filter_bw', 8.0), 0.5, 9.0)
    dry_wet = _clamp(delay.get('dry_wet', 0.5) * 100.0, 0.0, 100.0)

    # JUCE APVTS serializes parameters in alphabetical order by parameter ID.
    xml = (
        '<?xml version="1.0" encoding="UTF-8"?> <Parameters>'
        f'<PARAM id="beatDivL" value="{beat_div_l}"/>'
        f'<PARAM id="beatDivR" value="{beat_div_r}"/>'
        f'<PARAM id="delayTimeL" value="{delay_time_l}"/>'
        f'<PARAM id="delayTimeR" value="{delay_time_r}"/>'
        f'<PARAM id="dryWet" value="{dry_wet}"/>'
        f'<PARAM id="feedback" value="{feedback}"/>'
        f'<PARAM id="filterEnabled" value="{filter_on}"/>'
        f'<PARAM id="filterFreq" value="{filter_freq}"/>'
        f'<PARAM id="filterWidth" value="{filter_width}"/>'
        '<PARAM id="infiniteFb" value="0.0"/>'
        '<PARAM id="link" value="1.0"/>'
        '<PARAM id="modFilter" value="0.0"/>'
        '<PARAM id="modRate" value="0.4999999701976776"/>'
        '<PARAM id="modTime" value="0.0"/>'
        '<PARAM id="mode" value="0.0"/>'
        '<PARAM id="offsetL" value="4.917383193969727e-7"/>'
        '<PARAM id="offsetR" value="4.917383193969727e-7"/>'
        '<PARAM id="pingPong" value="0.0"/>'
        f'<PARAM id="syncL" value="{sync_l}"/>'
        f'<PARAM id="syncR" value="{sync_r}"/>'
        '</Parameters>'
    )
    xml_bytes = xml.encode('utf-8')
    magic = struct.pack('<I', 0x21324356)
    size  = struct.pack('<I', len(xml_bytes))   # size = XML text length (no null)
    # _ABS_DELAY_JUCE_SUFFIX starts with 9 null bytes; the first one is the XML null terminator
    return magic + size + xml_bytes + _ABS_DELAY_JUCE_SUFFIX


def _abs_delay_norm(param: str, raw: float) -> float:
    """Normalize an Ableton Delay raw value to Absolute Delay's JUCE 0..1 range."""
    import math as _math
    def _skew(v, lo, hi, sk):
        proportion = _clamp((v - lo) / (hi - lo), 0.0, 1.0)
        return proportion ** sk
    if param == 'feedback':      return _clamp(raw * 100.0 / 95.0, 0.0, 1.0)
    if param == 'dry_wet':       return _clamp(raw, 0.0, 1.0)
    if param == 'filter_freq':   return _skew(raw, 50.0, 18000.0, 0.25)
    if param == 'filter_bw':     return _clamp((raw - 0.5) / 8.5, 0.0, 1.0)
    if param in ('filter_on', 'l_synced', 'r_synced'):
        return 1.0 if raw else 0.0
    if param in ('l_sixteenths', 'r_sixteenths'):
        return _clamp(round(raw) / 7.0, 0.0, 1.0)
    if param in ('l_time_ms', 'r_time_ms'):
        # Automation events store raw seconds from Ableton XML; convert to ms for the plugin range
        return _skew(raw * 1000.0, 1.0, 5000.0, 0.35)
    return _clamp(raw, 0.0, 1.0)


# Ableton Delay param name → (Absolute Delay JUCE param index, display name)
# Indices follow createParameterLayout() registration order (NOT alphabetical XML order):
# 0=syncL 1=syncR 2=beatDivL 3=beatDivR 4=delayTimeL 5=delayTimeR
# 6=offsetL 7=offsetR 8=link 9=feedback 10=infiniteFb
# 11=filterEnabled 12=filterFreq 13=filterWidth 14=modRate 15=modFilter
# 16=modTime 17=mode 18=pingPong 19=dryWet
_ABS_DELAY_PARAM_MAP = {
    'l_synced':     (0,  'Sync L'),
    'r_synced':     (1,  'Sync R'),
    'l_sixteenths': (2,  'Beat Div L'),
    'r_sixteenths': (3,  'Beat Div R'),
    'l_time_ms':    (4,  'Delay Time L'),
    'r_time_ms':    (5,  'Delay Time R'),
    'feedback':     (9,  'Feedback'),
    'filter_on':    (11, 'Filter On'),
    'filter_freq':  (12, 'Filter Freq'),
    'filter_bw':    (13, 'Filter Width'),
    'dry_wet':      (19, 'Dry / Wet'),
}


def _encode_absolute_delay(delay: dict, bpm: float = 120.0) -> str:
    """Encode Ableton native Delay → Absolute Delay VST3 with parameter + automation mapping."""
    juce_blob = _build_abs_delay_juce_blob(delay, bpm=bpm)
    c1 = bytearray.fromhex(_ABS_DELAY_C1)
    for patch_offset, addend in [(48, 8), (60, -8)]:
        struct.pack_into('<I', c1, patch_offset, len(juce_blob) + addend)
    state_b64 = base64.b64encode(bytes(c1) + juce_blob).decode()
    rpp = _wrap_vst(_ABS_DELAY_TAG, state_b64, delay.get('enabled', True),
                    chunk_trailer='AAAQAAAA')

    delay_auto = delay.get('delay_auto', {})
    if delay_auto:
        param_automations = {}
        for abl_param, events in delay_auto.items():
            if abl_param not in _ABS_DELAY_PARAM_MAP:
                continue
            idx, name = _ABS_DELAY_PARAM_MAP[abl_param]
            norm_events = [(t, _abs_delay_norm(abl_param, v)) for t, v in events]
            param_automations[idx] = {'name': name, 'events': norm_events}
        if param_automations:
            rpp = _inject_param_automations(rpp, param_automations, bpm)

    return rpp


def _utility_manual_setup_note(dev: dict) -> str:
    gain = dev.get('gain_db', 0.0)
    pan = dev.get('pan', 0.0)
    width = dev.get('width', 1.0)
    cm = dev.get('channel_mode', 0)
    phase_l = dev.get('phase_l', False)
    phase_r = dev.get('phase_r', False)
    cm_label = {0: 'Stereo', 1: 'Left mono', 2: 'Right mono', 3: 'Swap L/R'}.get(cm, 'Stereo')
    return (
        f'Utility → MUtility inserted with default state (auto-conversion unsafe, see HANDOFF.md). '
        f'Set manually: Gain={gain:+.1f}dB, Panorama={pan*100:+.0f}%, '
        f'Pano L/R=±{width*100:.0f}%, Mode={cm_label}, '
        f'InvertL={"ON" if phase_l else "off"}, InvertR={"ON" if phase_r else "off"}.'
    )

def _encode_js_chorus(ch: dict) -> str:
    return _js('Liteon/Chorus', ch.get('enabled', True), [
        _clamp(ch.get('rate_hz', 1.0) / 10.0, 0, 1),
        float(ch.get('depth', 0.5)),
        float(ch.get('feedback', 0.0)),
        float(ch.get('dry_wet', 0.5)),
    ])

# Global VST database — loaded once on first use
_vst_db: VSTDatabase | None = None

def _get_vst_db(ini_path: str = '') -> VSTDatabase:
    global _vst_db
    if _vst_db is None:
        _vst_db = VSTDatabase(ini_path if ini_path else None)
    return _vst_db


def _encode_third_party(dev: dict) -> str:
    name = dev.get('name', 'Unknown')
    ptype = dev.get('plugin_type', 'VST')
    enabled = dev.get('enabled', True)

    # Try to find the plugin in Reaper's VST database
    db = _get_vst_db()
    if db.loaded:
        info = db.find(name)
        if info:
            return info.rpp_block(enabled=enabled)

    # Fallback: disabled placeholder with plugin name visible
    pad = ' -' * 62
    return '\n'.join([
        f'      <JS utility/volume_pan "PLACEHOLDER: {name} ({ptype})"',
        '      FLOATPOS 0 0 0 0',
        '      FXID {00000000-0000-0000-0000-000000000000}',
        f'      PARM 0.500000 0.500000{pad}',
        '      >',
        '      BYPASS 1 0 0',
    ])

def _encode_generic(dev: dict) -> str:
    name = dev.get('type', 'Unknown')
    en = dev.get('enabled', True)
    pad = ' -' * 62
    return '\n'.join([
        f'      <JS utility/volume_pan "NOTE: {name}"',
        '      FLOATPOS 0 0 0 0',
        '      FXID {00000000-0000-0000-0000-000000000000}',
        f'      PARM 0.500000 0.500000{pad}',
        '      >',
        f'      BYPASS {0 if en else 1} 0 0',
    ])


# ─────────────────────────────────────────────────────────────────────────────
# Device dispatcher
# ─────────────────────────────────────────────────────────────────────────────

def _make_param_parmenv(param_idx: int, events: list, param_name: str) -> str:
    """Build a PARMENV block for a continuous plugin parameter.
    events: list of (time_seconds, norm_value) tuples, sorted by time.
    Values are normalized 0–1 as Ableton stores them (maps 1:1 to Reaper's PARMENV range)."""
    lines = [f'      <PARMENV {param_idx} 0 1 0 "{param_name}"',
             '        ACT 1 -1', '        VIS 1 1 1', '        LANEHEIGHT 0 0',
             '        ARM 1', '        DEFSHAPE 0 -1 -1']
    for t, v in events:
        lines.append(f'        PT {t:.6f} {v:.10f} 0')
    lines.append('      >')
    return '\n'.join(lines)


def _inject_param_automations(rpp: str, param_automations: dict, bpm: float) -> str:
    """Splice PARMENV blocks for each automated parameter into an FX block,
    right after FXID. Reaper accepts multiple PARMENV blocks in any order."""
    lines = rpp.split('\n')
    insert_after = None
    for i, line in enumerate(lines):
        if line.strip().startswith('FXID'):
            insert_after = i
            break
    if insert_after is None:
        return rpp
    parmenvs = []
    for param_idx in sorted(param_automations.keys()):
        info = param_automations[param_idx]
        sec_events = [(_beats_to_seconds(t, bpm), v) for t, v in info['events']]
        parmenvs.append(_make_param_parmenv(param_idx, sec_events, info['name']))
    for offset, block in enumerate(parmenvs):
        lines.insert(insert_after + 1 + offset, block)
    return '\n'.join(lines)


def _device_to_rpp(dev: dict, bpm: float = 120.0) -> tuple[str, dict | None]:
    rpp, warn = _device_to_rpp_inner(dev, bpm=bpm)
    bypass_auto = dev.get('bypass_automation')
    if bypass_auto:
        rpp = _inject_bypass_automation(rpp, bypass_auto, bpm, dev.get('type', 'FX'))
    param_automations = dev.get('param_automations')
    if param_automations:
        rpp = _inject_param_automations(rpp, param_automations, bpm)
    return rpp, warn


def _beats_to_seconds(beats: float, bpm: float) -> float:
    return beats * 60.0 / bpm


def _inject_bypass_automation(rpp: str, events: list, bpm: float, fx_name: str) -> str:
    """Splice a PARMENV bypass envelope into an already-generated FX block,
    right after its FXID line (matches Reaper's own ordering: FXID → PARMENV → WAK)."""
    seconds_events = [(_beats_to_seconds(t, bpm), enabled) for t, enabled in events]
    parmenv = _make_bypass_parmenv(seconds_events, fx_name)
    lines = rpp.split('\n')
    for i, line in enumerate(lines):
        if line.strip().startswith('FXID'):
            lines.insert(i + 1, parmenv)
            break
    return '\n'.join(lines)


def _device_to_rpp_inner(dev: dict, bpm: float = 120.0) -> tuple[str, dict | None]:
    t = dev.get('type', '')
    warn = None

    if t == 'EQ Eight':
        rpp, clamped = _encode_reaeq(dev)
        warn = {'type': 'approximation', 'message': 'EQ Eight → ReaEQ. ' + ' '.join(clamped)} if clamped else None
        return rpp, warn

    if t == 'Compressor':
        return _encode_mcompressor(dev), None

    if t == 'Glue Compressor':
        release_note = ' Release set to Auto (≈400ms).' if dev.get('release_auto') else ''
        range_db = dev.get('range_db', 70.0)
        range_note = f' Range ({range_db:.0f}dB) not mappable — MCompressor has no range param.' if abs(range_db - 70.0) > 0.5 else ''
        clip_note = ' Soft clip button not mappable — no equivalent in MCompressor.' if dev.get('peak_clip_in') else ''
        warn = {'type': 'approximation',
                'message': f'Glue Compressor → MCompressor (character differs).{release_note}{range_note}{clip_note}'}
        return _encode_mcompressor({**dev,
            'attack_ms':  dev.get('attack_ms', 1.0),
            'release_ms': dev.get('release_ms', 400.0),
            'knee_db':    0.0,
            'dry_wet':    dev.get('dry_wet', 1.0),
        }), warn

    if t == 'Gate':
        notes = []
        if dev.get('floor_db', -75.0) > -74.0:
            notes.append(f"Floor ({dev['floor_db']:.1f}dB) not mappable in ReaGate")
        if dev.get('flip', False):
            notes.append('Flip/Invert mapped to ReaGate Invert Gate')
        warn = {'type': 'approximation', 'message': 'Gate → ReaGate. ' + ' '.join(notes)} if notes else None
        return _encode_reagate(dev), warn

    if t == 'Limiter':
        return _encode_realimit(dev), None

    if t == 'Saturator':
        warn = {'type': 'approximation', 'message': 'Saturator → JS Saturation. Shape not 1:1.'}
        return _encode_js_saturator(dev), warn

    if t in ('Utility', 'Stereo Gain'):
        return _encode_abs_utility(dev, bpm=bpm)

    if t == 'Reverb':
        warn = {'type': 'approximation', 'message': 'Reverb → ReaVerb. Adjust by ear.'}
        return _encode_reaverb(dev), warn

    if t in ('Delay', 'Filter Delay', 'Ping Pong Delay'):
        if t == 'Delay':
            return _encode_absolute_delay(dev, bpm=bpm), None
        warn = {'type': 'approximation', 'message': f'{t} → MDelay. Ping-pong and multi-tap approximate.'}
        return _encode_mdelay(dev, bpm=bpm), warn

    if t in ('Chorus', 'Chorus-Ensemble'):
        warn = {'type': 'approximation', 'message': 'Chorus → JS Chorus. Approximate.'}
        return _encode_js_chorus(dev), warn

    if t == 'THIRD_PARTY':
        plugin_name = dev.get('name', 'Unknown')
        processor_state_hex = dev.get('processor_state_hex')

        # Melda VST3 passthrough: Ableton stores the exact Melda blob in ProcessorState.
        # Structure: C1 (76 bytes) + C2_prefix (512 bytes) + als_blob (512 bytes compressed)
        # C1 and C2_prefix are fixed per-plugin constants from reference RPPs.
        _MELDA_PASSTHROUGH = {
            # 3-tuple: (c1_hex, c2_prefix_hex, vst_tag)
            #   state = C1 + c2_prefix + als_blob
            'MConvolutionEZ': (
                '29256533ee5eedfe02000000010000000000000002000000000000000200000001000000000000000200000000000000100400000100000000001000000200000100000078da5d90c14a0331',
                '1086c7a347dfa0d0abb89b52a8c74dd72d141a5c5cb18bb77433dd06d3a42459911e7c055fd537d0891551739bff9b99ff9f8098b7ad289d7d766688dad9ea31608cdaf601f818d8191fff820b6d10426d64c44ca0d2c37e94b3abad911df007f4815a600ae717c0c5f266597bd77bb92f77d2f65859b9a16106fc8f5cd2aade797d449f58a57474bea112c26c965f4eaf73e014207a670c199cb6a8d42a309250922e0f01554315ba14b83643afedbd736623fd0f07f6c1857c592d6ee7c6754f5f166cc45777cdc1e848c34961a020bde2adf84726dfe4fd58b427e709b46bade24e40dbb8c177982ec3ad3604e9fb28629665af9f0999748e00000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000002000000000000',
                'VST "VST3: MConvolutionEZ (MeldaProduction)" MConvolutionEZ.vst3 0 "" 862266665{4D656C646170726F4D43657A4D43657A} ""',
            ),
            # 4-tuple: (c1_hex, vst_tag, separator_hex, trailer_hex)
            #   state = C1 + als_blob + separator + als_blob + trailer  (dual-blob / shadow-copy pattern)
            #   C1[48] patched to 2*len(als_blob)+16
            #   C1[60] patched to len(als_blob)
            #   Verified byte-by-byte against mSat.RPP reference (non-default settings).
            #   separator byte 100 = 0x02 (blob count=2); trailer ends with 300010000000.
            'MSaturator': (
                '11552641ee5eedfe020000000100000000000000020000000000000002000000010000000000000002000000000000001004000001000000000010000002000001000000',
                'VST "VST3: MSaturator (MeldaProduction)" MSaturator.vst3 0 "" 1093031185{4D656C646170726F4D4165344D416534} ""',
                '0000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000002000000000000',
                '00000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000300010000000',
            ),
        }

        if processor_state_hex and plugin_name in _MELDA_PASSTHROUGH:
            entry = _MELDA_PASSTHROUGH[plugin_name]
            if len(entry) == 3:
                c1_hex, c2_prefix_hex, vst_tag = entry
                state = bytes.fromhex(c1_hex) + bytes.fromhex(c2_prefix_hex) + bytes.fromhex(processor_state_hex)
            else:
                c1_hex, vst_tag, separator_hex, trailer_hex = entry
                als_blob = bytes.fromhex(processor_state_hex)
                c1 = bytearray.fromhex(c1_hex)
                struct.pack_into('<I', c1, 48, 2 * len(als_blob) + 16)
                struct.pack_into('<I', c1, 60, len(als_blob))
                state = bytes(c1) + als_blob + bytes.fromhex(separator_hex) + als_blob + bytes.fromhex(trailer_hex)
            state_b64 = base64.b64encode(state).decode()
            rpp = _wrap_vst(vst_tag, state_b64, dev.get('enabled', True), chunk_trailer='')
            warn = {'type': 'passthrough',
                    'plugin_name': plugin_name,
                    'message': f"'{plugin_name}' — full state passed through from Ableton (all params preserved)."}
            return rpp, warn

        # Waves WaveShell passthrough: state is stored as three separate base64 chunks in
        # the RPP (C1 / state / preset-name), unlike the single-blob approach used elsewhere.
        # c1_patches: same (offset, addend) tuples as _GENERIC_PASSTHROUGH.
        # preset_name_hex: fixed 16-byte Waves preset-name chunk appended as third b64 line.
        # c2_builder: if provided (callable), overrides the default c2 = als_blob[skip_bytes:].
        #   Called as c2_builder(als_blob) → bytes.  Used when Reaper wraps the blob in
        #   a length-prefix + zero-suffix that don't come from the blob itself.
        _WAVES_PASSTHROUGH = {
            # (c1_hex, vst_tag, skip_bytes, preset_name_hex, c1_patches[, c2_builder])
            #
            # Sibilance Mono: Reaper's state chunk = pack('<II', len(als_blob), 1)
            #   + als_blob + b'\x00'*8.  C1[40] = len(state) = len(als_blob)+16.
            #   Verified byte-by-byte against Sibilance.RPP reference (non-default settings).
            #   The 4-byte Waves internal marker at als_blob[1199:1203] (0xff000000) differs
            #   from what Reaper/Waves saves (0x0000c94d); this is safe because Waves
            #   re-parses its own XML and recalculates that field on load.
            'Sibilance Mono': (
                '8f6abf3cee5eedfe0100000001000000000000000200000003000000000000000200000000000000e60400000100000000001000',
                'VST "VST3: Sibilance Mono (Waves)" "WaveShell1-VST3 13.0.vst3" 0 "" 1019177615{5653545349424D736962696C616E6365} ""',
                0,
                '0046756c6c2052657365740010000000',  # b'\x00Full Reset\x00\x10\x00\x00\x00'
                [(40, 0)],
                lambda b: struct.pack('<II', len(b), 1) + b + b'\x00' * 8,
            ),
        }

        if processor_state_hex and plugin_name in _WAVES_PASSTHROUGH:
            entry = _WAVES_PASSTHROUGH[plugin_name]
            c1_hex, vst_tag, skip_bytes, preset_name_hex, c1_patches = entry[:5]
            c2_builder = entry[5] if len(entry) > 5 else None
            als_blob = bytes.fromhex(processor_state_hex)
            if c2_builder is not None:
                c2 = c2_builder(als_blob)
            else:
                c2 = als_blob[skip_bytes:]
            c1 = bytearray.fromhex(c1_hex)
            for patch_offset, addend in (c1_patches or []):
                value = addend(c2) if callable(addend) else len(c2) + addend
                struct.pack_into('<I', c1, patch_offset, value)
            c1_b64 = base64.b64encode(bytes(c1)).decode()
            state_b64 = base64.b64encode(c2).decode()
            preset_b64 = base64.b64encode(bytes.fromhex(preset_name_hex)).decode()
            rpp = _wrap_vst_waves(vst_tag, c1_b64, state_b64, preset_b64, dev.get('enabled', True))
            warn = {'type': 'passthrough',
                    'plugin_name': plugin_name,
                    'message': f"'{plugin_name}' — full state passed through from Ableton (all params preserved)."}
            return rpp, warn

        # Generic (non-Melda) VST2/VST3 passthrough: Ableton's ProcessorState already
        # contains the plugin's native VstW/CcnK-style chunk. Reaper's C2 is either
        # that same blob with N leading bytes skipped (a redundant header Ableton
        # keeps but Reaper's wrapper doesn't need), or that blob with a small extra
        # length-prefix Reaper adds on top. Determined empirically per plugin from a
        # reference RPP — see HANDOFF.md for the derivation. No value-patching of the
        # actual parameters; works regardless of values since we never touch the blob.
        # IMPORTANT: some plugins (confirmed: Kirchhoff-EQ) embed the total C2 length
        # *inside C1 itself* — using a stale/constant C1 silently loads default state
        # instead of crashing, so c1_size_offset must be patched per-instance when set.
        _GENERIC_PASSTHROUGH = {
            # name: (c1_hex, vst_tag, skip_bytes, length_prefix, c1_patches, chunk_trailer)
            # skip_bytes: int — leading bytes to drop from Ableton's blob before using as C2
            #             callable(als_blob) → bytes — custom C2 builder (overrides length_prefix)
            # length_prefix: if True, prepend struct.pack('<I', len(blob)-8) + b'\\x01\\x00\\x00\\x00'
            # c1_patches: list of (offset, addend) — write struct.pack('<I', len(C2)+addend) at each offset
            # chunk_trailer: base64 string appended after state (default '' = none)
            'Absolute Utility': (
                'a8425a7aee5eedfe020000000100000000000000020000000000000002000000010000000000000002000000000000005a02000001000000ffff10004a02000001000000',
                'VST "VST3: Absolute Utility (Internal)" "Absolute Utility.vst3" 0 "" 2052735656{ABCDEF019182FAEB4162735541625554} ""',
                0, False, [(48, 8), (60, -8)], 'AAAQAAAA',
            ),
            # IVGI2: Reaper's state = pack('<II', len(als_blob), 1) + als_blob + zeros*8
            # then AAAQAAAA chunk_trailer is appended by _wrap_vst.
            # C1[48] = len(als_blob)+16.  C1 is 60 bytes (not 68).
            # Verified byte-by-byte against IVGI2.RPP reference (non-default settings).
            'IVGI2': (
                'c3c53a1aee5eedfe02000000010000000000000002000000000000000200000001000000000000000200000000000000c101000001000000ffff1000',
                'VST "VST3: IVGI2 (Klanghelm)" IVGI2.vst3 0 "" 440059331{56535449564732697667693200000000} ""',
                lambda b: struct.pack('<II', len(b), 1) + b + b'\x00' * 8,
                False, [(48, 0)], 'AAAQAAAA',
            ),
            'UADx LA-2A Tube Compressor': (
                'b989e419ee5eedfe020000000100000000000000020000000000000002000000010000000000000002000000000000005504000001000000ffff10004504000001000000',
                'VST "VST3: UADx LA-2A Tube Compressor (Universal Audio (UADx))" uaudio_teletronix_la-2a_tc.vst3 0 "" 434407865{ABCDEF019182FAEB554144785533444A} ""',
                0, False, [(48, 8), (60, -8)], 'AAAQAAAA',
            ),
            'ValhallaSupermassive': (
                'c8760f23ee5eedfe02000000010000000000000002000000000000000200000001000000000000000200000000000000c602000001000000ffff1000b6020000010000005673745700000008',
                'VST "VST3: ValhallaSupermassive (Valhalla DSP, LLC)" ValhallaSupermassive.vst3 0 "" 588216008{565354734D617376616C68616C6C6173} ""',
                8, False, None,
            ),
            'Vocal Doubler': (
                'd447ce1bee5eedfe020000000100000000000000020000000000000002000000010000000000000002000000000000009c02000001000000ffff100046010000010000001cf8800000000000',
                'VST "VST3: Vocal Doubler (iZotope)" "Vocal Doubler.vst3" 0 "" 466503636{565354495A5644566F63616C20446F75} ""',
                # C1[48] = len(C2)+16; C1[60] = blob1_comp_size+12 (first 4 bytes of C2 + 12)
                8, False, [(48, 16), (60, lambda c2: struct.unpack_from('<I', c2, 0)[0] + 12)], 'AAAQAAAA',
            ),
            'MV2 Mono': (
                'c273dd44ee5eedfe0100000001000000000000000200000003000000000000000200000000000000de0300000100000000001000ce03000001000000000003ac00000003000000014d56324d',
                'VST "VST3: MV2 Mono (Waves)" "WaveShell1-VST3 14.12.vst3" 0 "" 1155363778{5653544D56324D6D7632206D6F6E6F00} ""',
                16, False, None,
            ),
            'MV2 Stereo': (  # UNVERIFIED against a real project blob — same family pattern as MV2 Mono
                '761c0841ee5eedfe02000000010000000000000002000000000000000200000001000000000000000200000000000000de0300000100000000001000ce03000001000000000003ac00000003',
                'VST "VST3: MV2 Stereo (Waves)" "WaveShell1-VST3 14.12.vst3" 0 "" 1091050614{5653544D5632536D7632207374657265} ""',
                16, False, None,
            ),
            'TBTECH Kirchhoff-EQ': (
                '9ba14234ee5eedfe04000000010000000000000002000000000000000400000000000000080000000000000002000000010000000000000002000000000000007452010001000000ffff1000',
                'VST "VST3: TBTECH Kirchhoff-EQ (Plugin Alliance)" "TBTECH Kirchhoff-EQ.vst3" 0 "" 876781979{565354356D6267746274656368206B69} ""',
                0, True, [(64, 0)],
            ),
        }

        if processor_state_hex and plugin_name in _GENERIC_PASSTHROUGH:
            entry = _GENERIC_PASSTHROUGH[plugin_name]
            c1_hex, vst_tag, skip_bytes, length_prefix, c1_patches = entry[:5]
            chunk_trailer = entry[5] if len(entry) > 5 else ''
            als_blob = bytes.fromhex(processor_state_hex)
            # skip_bytes can be a callable(als_blob) → bytes for plugins that need a
            # custom wrapper (e.g. IVGI2 prepends a length-prefix and appends zero-padding).
            if callable(skip_bytes):
                c2 = skip_bytes(als_blob)
            else:
                c2 = als_blob[skip_bytes:]
            if length_prefix:
                c2 = struct.pack('<I', len(als_blob) - 8) + b'\x01\x00\x00\x00' + als_blob
            c1 = bytearray.fromhex(c1_hex)
            for patch_offset, addend in (c1_patches or []):
                value = addend(c2) if callable(addend) else len(c2) + addend
                struct.pack_into('<I', c1, patch_offset, value)
            state = bytes(c1) + c2
            state_b64 = base64.b64encode(state).decode()
            rpp = _wrap_vst(vst_tag, state_b64, dev.get('enabled', True), chunk_trailer=chunk_trailer)
            unverified_note = ' (UNVERIFIED — please confirm it loads correctly)' if plugin_name == 'MV2 Stereo' else ''
            warn = {'type': 'passthrough',
                    'plugin_name': plugin_name,
                    'message': f"'{plugin_name}' — full state passed through from Ableton (all params preserved){unverified_note}."}
            return rpp, warn

        db = _get_vst_db()
        found_in_db = db.loaded and db.find(plugin_name) is not None
        if found_in_db:
            warn = {'type': 'third_party_found',
                    'plugin_name': plugin_name,
                    'plugin_type': dev.get('plugin_type'),
                    'message': f"'{plugin_name}' loaded from Reaper VST database."}
        else:
            warn = {'type': 'third_party',
                    'plugin_name': plugin_name,
                    'plugin_type': dev.get('plugin_type'),
                    'message': f"'{plugin_name}' not found in Reaper VST database — placeholder inserted."}
        return _encode_third_party(dev), warn

    warn = {'type': 'unsupported_native', 'message': f"'{t}' not mapped. Placeholder inserted."}
    return _encode_generic(dev), warn


# ─────────────────────────────────────────────────────────────────────────────
# FX chain block
# ─────────────────────────────────────────────────────────────────────────────

def _fx_chain(devices: list, track_name: str, warnings: list, bpm: float = 120.0) -> str:
    if not devices:
        return ''
    lines = ['    <FXCHAIN', '      SHOW 0', '      LASTSEL 0', '      DOCKED 0']
    for dev in devices:
        rpp, warn = _device_to_rpp(dev, bpm=bpm)
        if warn:
            warn['track'] = track_name
            warnings.append(warn)
        lines.append(rpp)
    lines.append('    >')
    return '\n'.join(lines)


# ─────────────────────────────────────────────────────────────────────────────
# Track order + folder structure
# ─────────────────────────────────────────────────────────────────────────────

def _build_track_tree(tracks: list) -> list:
    group_ids = {t['id'] for t in tracks if t['type'] == 'group'}
    children  = {gid: [] for gid in group_ids}
    for t in tracks:
        gid = str(t.get('group_id', -1))
        if gid in children:
            children[gid].append(t)

    result = []
    for t in tracks:
        if t['type'] == 'return':
            continue
        if t['type'] == 'group':
            result.append((t, 1, 1))   # Reaper 7.x folder start = ISBUS 1 1
        else:
            gid = str(t.get('group_id', -1))
            if gid in children:
                grp = children[gid]
                is_last = grp and grp[-1]['id'] == t['id']
                result.append((t, 2 if is_last else 0, -1 if is_last else 0))  # last child = ISBUS 2 -1
            else:
                result.append((t, 0, 0))

    for t in tracks:
        if t['type'] == 'return':
            result.append((t, 0, 0))
    return result


# ─────────────────────────────────────────────────────────────────────────────
# Single track → RPP
# ─────────────────────────────────────────────────────────────────────────────

import re as _re

def _build_stem_file_index(stem_dir: str) -> dict:
    """List all .wav/.aif/.aiff files in stem_dir and build lookup structures:
      - by_name: {filename -> Path}
      - by_short: {short_name -> Path}  (track-name portion from 'Export N' scheme)
      - by_export_num: {int -> Path}  (export number → file, for same-name track disambiguation)
    Returns (by_name, by_short, by_export_num)."""
    by_name       = {}
    by_short      = {}
    by_export_num = {}
    _export_re = _re.compile(r'.+\s*-\s*Export\s+(\d+)[-\s]+(.+)', _re.IGNORECASE)
    try:
        for f in Path(stem_dir).iterdir():
            if f.suffix.lower() in ('.wav', '.aif', '.aiff'):
                by_name[f.name] = f
                m = _export_re.match(f.stem)
                if m:
                    num, rest = m.group(1).strip(), m.group(2).strip()
                    by_export_num[int(num)] = f
                    # Store as "<N> <name>" to match Ableton track names like "11 HH"
                    by_short[f'{num} {rest}'] = f
                    # Also store the name-only form as a fallback for tracks without numbers
                    by_short.setdefault(rest, f)
    except (FileNotFoundError, NotADirectoryError):
        pass
    return by_name, by_short, by_export_num


def _find_stem_file(track_name: str, project_name: str, stem_index, export_index: int = 0) -> Path | None:
    """Find the stem file for a track by scanning actual files in the stems directory.
    stem_index is a (by_name, by_short, by_export_num) tuple from _build_stem_file_index.
    Matching strategy (applied in order, returns on first hit):
      0. Export number match: stem 'Export N' N == export_index (handles same-name tracks)
      1. Exact: '<project> <track>.wav'
      2. Exact match against Ableton's 'Export N' short name
      3. Exact suffix of full filename
      4. Case/whitespace-normalised suffix of full filename
      5. Case/whitespace-normalised match against Export short name
      6. Normalised track name contained anywhere in full filename
      7. All significant words (len>2) present in full filename
    Never constructs or guesses a filename — only matches against files that exist."""
    if not stem_index:
        return None

    by_name, by_short, by_export_num = stem_index

    def normalise(s: str) -> str:
        return ' '.join(s.lower().split())

    norm_track = normalise(track_name)

    # 0. Export number match — most reliable for same-name tracks, but only when
    # the track name also appears in the filename to avoid cross-project false positives
    if export_index and export_index in by_export_num:
        candidate = by_export_num[export_index]
        if norm_track in normalise(candidate.stem):
            return candidate

    # 1. Exact full filename
    exact = f'{project_name} {track_name}.wav'
    if exact in by_name:
        return by_name[exact]

    # 2. Exact short name (Ableton Export N scheme)
    if track_name in by_short:
        return by_short[track_name]

    # 3. Exact suffix of full filename
    for fname, fpath in by_name.items():
        if fname[:-4].endswith(track_name):
            return fpath

    # 4. Normalised suffix of full filename
    for fname, fpath in by_name.items():
        if normalise(fname[:-4]).endswith(norm_track):
            return fpath

    # 5. Normalised match against Export short name
    for short, fpath in by_short.items():
        if normalise(short) == norm_track:
            return fpath

    # 6. Normalised track name contained anywhere in full filename
    for fname, fpath in by_name.items():
        if norm_track in normalise(fname[:-4]):
            return fpath

    # 7. All significant words present (handles reordered / abbreviated names)
    words = [w for w in norm_track.split() if len(w) > 2]
    if words:
        for fname, fpath in by_name.items():
            norm_fname = normalise(fname[:-4])
            if all(w in norm_fname for w in words):
                return fpath

    return None


def _track_rpp(track: dict, isbus: int, isend: int, warnings: list, stem_dir: str, bpm: float = 120.0, project_name: str = '', stem_index: dict | None = None) -> str:
    name  = track.get('name', 'Track')
    mixer = track.get('mixer', {})
    pan   = mixer.get('pan', 0.0)
    muted = mixer.get('muted', False)
    color = _reaper_color(track.get('color_index', 0))
    fx    = _fx_chain(track.get('devices', []), name, warnings, bpm=bpm)

    # Track volume: stems must be exported from Ableton with ALL faders at 0dB
    # (group AND individual track faders) before running this tool. That keeps
    # plugin input levels matching what they actually saw in Ableton (pre-fader
    # signal). We then reproduce the real mix balance by applying each track's
    # actual Ableton fader value here, in Reaper, on top of the flat stems —
    # applies to both regular tracks and group/folder tracks.
    track_volume = mixer.get('volume_linear', 1.0)

    # Pan level correction — two complementary mechanisms:
    #
    # 1. Sine taper (VOLPAN field 3 = sqrt(2), no PANLAWFLAGS): activates "Override:
    #    -3 dB + Gain compensation + Sine taper" in Reaper's Pan Law dialog. In stereo
    #    balance mode (PANMODE 3), this provides ~0 dB to the dominant channel at
    #    intermediate pans but a full +3 dB boost at hard pan (±1.0). It also cancels
    #    the project PANLAW 1 attenuation that otherwise applies at non-centre positions.
    #
    # 2. Cosine volume correction on the fader — handles intermediate pans where the
    #    Sine taper provides insufficient boost. Ableton's constant-power pan law boosts
    #    the dominant channel by cos(45°×(1-|pan|))×√2 above the fader level; Reaper's
    #    stereo balance does not replicate this boost, so we bake it in.
    #    At hard pan (|pan|=1.0) the Sine taper already provides the full +3 dB, so the
    #    cosine formula (also +3 dB at hard pan) must NOT be applied there — it would
    #    double-correct. Confirmed: GTR tracks at hard pan in a group were 3 dB too loud
    #    with both; removing cosine at hard pan matched. 12-HH at pan=-0.765 is correct
    #    with cosine+Sine taper.
    pan_abs = abs(pan)
    if 0.0 < pan_abs < 1.0:
        track_volume *= math.cos(math.radians(45.0 * (1.0 - pan_abs))) * math.sqrt(2)

    lines = [
        '  <TRACK',
        f'    NAME {json.dumps(name, ensure_ascii=False)}',
        f'    PEAKCOL {color}',
        '    BEAT -1',
        '    AUTOMODE 0',
        f'    VOLPAN {track_volume:.6f} {pan:.6f} 1.41421356237309 -1 1',
        f'    MUTESOLO {1 if muted else 0} 0 0',
        '    IPHASE 0',
        '    PLAYOFFS 0 1',
        f'    ISBUS {isbus} {isend}',
        '    BUSCOMP 0 0 0 0 0',
        '    SHOWINMIX 1 0.6667 0.5 1 0.5 0 0 0',
        '    FIXEDLANES 9 0 0 0 0',
        '    SEL 0',
        '    REC 0 0 1 0 0 0 0 0',
        '    VU 2',
        '    TRACKHEIGHT 0 0 0 0 0 0 0',
        '    INQ 0 0 0 0.5 100 0 0 100',
        '    NCHAN 2',
        '    FX 1',
        '    TRACKID {00000000-0000-0000-0000-000000000000}',
        '    PERF 0',
        '    MIDIOUT -1',
        '    MAINSEND 1 0',
    ]
    if fx:
        lines.append(fx)
    # Skip stem import for folder/group tracks. Ableton's "Export all individual
    # tracks" also exports a summed stem for each group, but in Reaper, audio
    # placed directly on a folder track plays IN ADDITION to its child tracks
    # (unlike Ableton, where the group's own audio doesn't separately exist) —
    # importing it here would double the volume of every track inside that group.
    if stem_dir and isbus != 1:
        wav_path = _find_stem_file(name, project_name, stem_index or ({}, {}, {}), export_index=track.get('export_index', 0))
        if wav_path is None:
            warnings.append({
                'type': 'missing_stem',
                'track': name,
                'message': f"No stem file found for track '{name}' — track left empty. Link manually in Reaper if a stem exists.",
            })
        else:
            length = _get_wav_duration(wav_path)
            lines += [
                '    <ITEM',
                f'      NAME {json.dumps(name + " stem", ensure_ascii=False)}',
                '      POSITION 0',
                f'      LENGTH {length:.6f}',
                '      LOOP 0',
                '      <SOURCE WAVE',
                f'        FILE {json.dumps(str(wav_path), ensure_ascii=False)}',
                '      >',
                '    >',
            ]
    elif stem_dir and isbus == 1:
        vol_note = ''
        if abs(track_volume - 1.0) > 0.001:
            vol_db = 20 * math.log10(max(track_volume, 1e-6))
            vol_note = f" Group fader set to {vol_db:+.1f}dB to match Ableton."
        warnings.append({
            'type': 'group_stem_skipped',
            'track': name,
            'message': f"'{name}' is a group/folder track — its summed stem export was NOT imported (would double the volume of its child tracks in Reaper). Child tracks' individual stems were imported normally.{vol_note}",
        })
    lines.append('  >')
    return '\n'.join(lines)


# ─────────────────────────────────────────────────────────────────────────────
# Main entry point
# ─────────────────────────────────────────────────────────────────────────────

def generate_rpp(project: dict, output_path, stem_dir: str = '') -> dict:
    output_path = Path(output_path)
    warnings    = []
    tempo       = project.get('tempo', 120.0)
    ts_num, ts_den = project.get('time_signature', '4/4').split('/')
    tracks      = project.get('tracks', [])
    master      = project.get('master')

    tree = _build_track_tree(tracks)
    project_name = Path(project.get('source_file', '')).stem
    stem_index = _build_stem_file_index(stem_dir) if stem_dir else ({}, {})

    lines = [
        '<REAPER_PROJECT 0.1 "6.0" 0',
        '  RIPPLE 0', '  GROUPOVERRIDE 0 0 0', '  AUTOXFADE 129',
        '  ENVATTACH 3', '  POOLEDENVATTACH 0', '  MIXERUIFLAGS 11 48',
        '  PEAKGAIN 1', '  FEEDBACK 0', '  PANLAW 1',
        '  PROJOFFS 0 0 0', '  MAXPROJLEN -1',
        '  GRID 3199 8 1 8 1 0 0 0', '  TIMEMODE 1 5 -1 30 0 0 -1',
        '  VIDEO_CONFIG 0 0 256', '  PANMODE 3', '  CURSOR 0',
        '  ZOOM 100 0 0', '  VZOOMEX 6 0', '  USE_REC_CFG 0', '  RECMODE 1',
        '  SMPTESYNC 0 30 100 40 1000 300 0 0 1 0 0',
        '  LOOP 0', '  LOOPGRAN 0', '  RECORD_PATH "" ""',
        '  <RECORD_CFG\n  >', '  <APPLYFX_CFG\n  >',
        '  RENDER_FILE ""', '  RENDER_PATTERN ""', '  RENDER_FMT 0 2 0',
        '  RENDER_1X 0', '  RENDER_RANGE 1 0 0 18 1000',
        '  RENDER_RESAMPLE 3 0 1', '  RENDER_ADDTOPROJ 0',
        '  RENDER_STEMS 0', '  RENDER_DITHER 0',
        '  TIMELOCKMODE 1', '  TEMPOENVLOCKMODE 1', '  ITEMMIX 1',
        '  DEFPITCHMODE 589824 0', '  TAKELANE 1', '  SAMPLERATE 44100 0 0',
        '  <RENDER_CFG\n  >', '  LOCK 0',
        '  <METRONOME 6 2',
        '    VOL 0.25 0.125', '    FREQ 800 1600 1', '    BEATLEN 4',
        '    SAMPLES "" ""', '    PATTERN 2863311530 2863311529',
        '  >',
        '  GLOBAL_AUTO -1',
        f'  TEMPO {tempo:.4f} {ts_num} {ts_den}',
        '  SELECTION 0 0', '  SELECTION2 0 0',
        '  MASTERAUTOMODE 0', '  MASTERTRACKHEIGHT 0 0',
        '  MASTERPEAKCOL 16576', '  MASTERMUTESOLO 0',
        '  MASTERTRACKVIEW 1 0.6667 0.5 0.5 0 0 0 0 0 0 0 0 0 0',
        '  MASTERHWOUT 12 0 1 0 0 0 0 -1',
        '  MASTERHWOUT 0 0 1 0 0 0 0 -1',
        '  MASTER_NCH 2 2',
        '  MASTER_VOLUME 1 0 -1 -1 1',
        '  MASTER_PANMODE 3',
        '  MASTER_PANLAWFLAGS 3',
        '  MASTER_FX 1',
        '  MASTER_SEL 0',
    ]

    # Master FX — uses MASTERFXLIST (flat, no MASTERTRACK wrapper), sits right after
    # the MASTER_* properties. Confirmed structure from reference RPP.
    if master and master.get('devices'):
        mfx_inner = _fx_chain(master['devices'], 'Master', warnings, bpm=tempo)
        # _fx_chain wraps in <FXCHAIN ...> — strip that outer tag (and its closing '>'),
        # keep everything else (SHOW/LASTSEL/DOCKED/BYPASS/... are already in there).
        mfx_lines = mfx_inner.split('\n')
        inner_content = mfx_lines[1:-1]
        lines += ['  <MASTERFXLIST'] + \
                  [l.replace('      ', '    ', 1) if l.startswith('      ') else l for l in inner_content] + \
                  ['  >']

    for (track, isbus, isend) in tree:
        lines.append(_track_rpp(track, isbus, isend, warnings, stem_dir, bpm=tempo, project_name=project_name, stem_index=stem_index))

    lines.append('>')

    output_path.write_text('\n'.join(lines), encoding='utf-8')

    return {
        'source_file':           project.get('source_file', ''),
        'output_file':           str(output_path),
        'track_count':           len(tracks),
        'warnings':              warnings,
        'third_party_plugins':   [w for w in warnings if w.get('type') == 'third_party'],
        'third_party_found':     [w for w in warnings if w.get('type') == 'third_party_found'],
        'passthrough':           [w for w in warnings if w.get('type') == 'passthrough'],
        'approximations':        [w for w in warnings if w.get('type') == 'approximation'],
        'unsupported':           [w for w in warnings if w.get('type') == 'unsupported_native'],
        'missing_stems':         [w for w in warnings if w.get('type') == 'missing_stem'],
    }
