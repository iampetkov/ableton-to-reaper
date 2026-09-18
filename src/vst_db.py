"""
vst_db.py
Parses Reaper's reaper-vstplugins_arm64.ini (or _x64.ini) and provides
name-based lookup to get the exact VST3 tag needed to reference a plugin in an RPP file.

Default search paths on macOS:
  ~/Library/Application Support/REAPER/reaper-vstplugins_arm64.ini
  ~/Library/Application Support/REAPER/reaper-vstplugins64.ini

Usage:
    db = VSTDatabase()               # auto-find
    db = VSTDatabase('/path/to.ini') # explicit path
    info = db.find('MConvolutionEZ') # search by plugin name
    if info:
        rpp_block = info.rpp_block(enabled=True)
"""

import os
import re
from pathlib import Path
from dataclasses import dataclass


# ---------------------------------------------------------------------------
# Default search locations
# ---------------------------------------------------------------------------

DEFAULT_SEARCH_PATHS = [
    Path.home() / 'Library' / 'Application Support' / 'REAPER' / 'reaper-vstplugins_arm64.ini',
    Path.home() / 'Library' / 'Application Support' / 'REAPER' / 'reaper-vstplugins64.ini',
    Path.home() / 'Library' / 'Application Support' / 'REAPER' / 'reaper-vstplugins.ini',
    Path('/Library') / 'Application Support' / 'REAPER' / 'reaper-vstplugins_arm64.ini',
    # Windows fallbacks
    Path(os.environ.get('APPDATA', '')) / 'REAPER' / 'reaper-vstplugins64.ini',
]


# ---------------------------------------------------------------------------
# Data class
# ---------------------------------------------------------------------------

@dataclass
class VSTPluginInfo:
    display_name: str      # e.g. "MConvolutionEZ (MeldaProduction)"
    filename: str          # e.g. "MConvolutionEZ.vst3"
    uid: str               # e.g. "862266665"
    guid: str              # e.g. "4D656C646170726F4D43657A4D43657A"
    is_vst3: bool

    def rpp_block(self, enabled: bool = True) -> str:
        """Generate the RPP FX block for this plugin (default/empty state)."""
        bypass = 0 if enabled else 1
        if self.is_vst3:
            tag = f'VST "VST3: {self.display_name}" {self.filename} 0 "" {self.uid}<{self.guid}> ""'
        else:
            tag = f'VST "{self.display_name}" {self.filename} 0 "" {self.uid} ""'

        return '\n'.join([
            f'      <{tag}',
            f'      BYPASS {bypass} 0 0',
            '      FLOATPOS 0 0 0 0',
            '      FXID {00000000-0000-0000-0000-000000000000}',
            '      >',
        ])


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------

def _parse_line(line: str) -> VSTPluginInfo | None:
    """
    Parse one line from the INI file.
    Formats:
      name.vst3=TIMESTAMP,UID{GUID,Display Name (Mfr)
      name.vst3<UID=TIMESTAMP,UID{GUID,Display Name (Mfr)    ← shell plugins
      name.vst=TIMESTAMP,UID,Display Name (Mfr)
    """
    line = line.strip()
    if not line or line.startswith('[') or line.startswith(';'):
        return None

    try:
        eq = line.index('=')
    except ValueError:
        return None

    filename_key = line[:eq]
    value = line[eq + 1:]

    # Actual filename: strip <ID suffix used by shell plugins
    filename = filename_key.split('<')[0].strip()
    is_vst3 = filename.lower().endswith('.vst3')

    if is_vst3:
        # Format: TIMESTAMP,UID{GUID,Display Name
        m = re.match(r'^[^,]+,(\d+)\{([0-9A-Fa-f]+),(.+)$', value)
        if not m:
            return None
        uid, guid, display_name = m.group(1), m.group(2), m.group(3).strip()
    else:
        # Format: TIMESTAMP,UID,Display Name
        parts = value.split(',', 2)
        if len(parts) < 3:
            return None
        uid, display_name = parts[1].strip(), parts[2].strip()
        guid = ''

    # Skip instruments (VSTi) and broken entries
    if '!!!' in display_name:
        display_name = display_name.split('!!!')[0].strip()

    return VSTPluginInfo(
        display_name=display_name,
        filename=filename,
        uid=uid,
        guid=guid,
        is_vst3=is_vst3,
    )


# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------

class VSTDatabase:
    def __init__(self, ini_path: str | Path | None = None):
        self._by_name: dict[str, VSTPluginInfo] = {}   # normalized name → info
        self._path: Path | None = None

        if ini_path:
            self._load(Path(ini_path))
        else:
            for candidate in DEFAULT_SEARCH_PATHS:
                if candidate.exists():
                    self._load(candidate)
                    break

    def _load(self, path: Path):
        self._path = path
        with open(path, encoding='utf-8', errors='replace') as f:
            for line in f:
                info = _parse_line(line)
                if info:
                    # Index by normalized display name (lowercase, no special chars)
                    key = _normalize(info.display_name)
                    # Prefer VST3 over VST2 when both exist
                    if key not in self._by_name or info.is_vst3:
                        self._by_name[key] = info

    @property
    def loaded(self) -> bool:
        return bool(self._by_name)

    @property
    def path(self) -> Path | None:
        return self._path

    def find(self, plugin_name: str) -> VSTPluginInfo | None:
        """
        Search for a plugin by name.
        Tries exact match first, then fuzzy (name is contained in display name).
        Returns VST3 entry preferentially over VST2.
        """
        needle = _normalize(plugin_name)

        # 1. Exact match
        if needle in self._by_name:
            return self._by_name[needle]

        # 2. Partial match: needle contained in display name key
        matches = [info for key, info in self._by_name.items() if needle in key]
        if len(matches) == 1:
            return matches[0]

        # 3. Partial match: display name key contained in needle (shorter name)
        matches = [info for key, info in self._by_name.items() if key in needle and len(key) > 4]
        if len(matches) == 1:
            return matches[0]

        # 4. Word-by-word: all words of needle appear in the key
        words = needle.split()
        if len(words) > 1:
            matches = [info for key, info in self._by_name.items()
                       if all(w in key for w in words)]
            if matches:
                # Prefer VST3, then longest name match
                vst3 = [m for m in matches if m.is_vst3]
                return vst3[0] if vst3 else matches[0]

        return None

    def all_names(self) -> list[str]:
        return sorted(self._by_name.keys())


def _normalize(name: str) -> str:
    """Lowercase, remove punctuation except spaces, collapse spaces."""
    name = name.lower()
    name = re.sub(r'[^\w\s]', ' ', name)   # punctuation → space
    name = re.sub(r'\s+', ' ', name).strip()
    return name


# ---------------------------------------------------------------------------
# CLI: test lookup
# ---------------------------------------------------------------------------

if __name__ == '__main__':
    import sys
    db = VSTDatabase()
    if not db.loaded:
        print('No Reaper VST database found.')
        sys.exit(1)

    print(f'Loaded: {db.path}  ({len(db._by_name)} plugins)')
    print()

    queries = sys.argv[1:] if len(sys.argv) > 1 else [
        'MConvolutionEZ', 'IVGI2', 'ValhallaSupermassive',
        'MV2 Mono', 'Vocal Doubler', 'TBTECH Kirchhoff-EQ',
        'TR5 Classic Clipper', 'Silk Vocal Mono',
    ]

    for q in queries:
        info = db.find(q)
        if info:
            print(f'✓ "{q}"')
            print(f'  → {info.display_name}  [{info.filename}  uid={info.uid}]')
            print(f'  RPP tag: <VST "VST3: {info.display_name}" {info.filename} 0 "" {info.uid}<{info.guid}> ""')
        else:
            print(f'✗ "{q}" — not found in database')
        print()
