#!/usr/bin/env python3
"""
test_pipeline.py
Creates a synthetic .als file that mirrors a real Ableton project structure,
then runs the full parse → generate pipeline and validates output.
"""

import gzip
import json
import sys
import os
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from als_parser import parse_als
from rpp_generator import generate_rpp
from report_generator import generate_report

# ---------------------------------------------------------------------------
# Synthetic .als XML
# ---------------------------------------------------------------------------

SYNTHETIC_ALS_XML = '''<?xml version="1.0" encoding="UTF-8"?>
<Ableton MajorVersion="5" MinorVersion="12.0.2" SchemaChangeCount="3" Creator="Ableton Live 12.3.2" Revision="">
  <LiveSet>
    <Tracks>

      <!-- KICK DRUM - Audio Track with EQ Eight + Glue Compressor -->
      <AudioTrack Id="1">
        <Name>
          <EffectiveName Value="Kick Drum"/>
          <UserName Value=""/>
        </Name>
        <ColorIndex Value="5"/>
        <TrackGroupId Value="-1"/>
        <MuteState><Manual Value="false"/></MuteState>
        <DeviceChain>
          <Mixer>
            <Volume><Manual Value="0.794328"/></Volume>
            <Pan><Manual Value="0.0"/></Pan>
            <Sends>
              <TrackSendHolder>
                <Send>
                  <Manual Value="0.5"/>
                  <Active><Manual Value="true"/></Active>
                </Send>
              </TrackSendHolder>
            </Sends>
          </Mixer>
          <Devices>
            <Eq8 Id="1">
              <On><Manual Value="true"/></On>
              <Bands.0>
                <IsOn><Manual Value="true"/></IsOn>
                <Mode><Manual Value="0"/></Mode>
                <Freq><Manual Value="60.0"/></Freq>
                <Gain><Manual Value="0.0"/></Gain>
                <Q><Manual Value="0.7"/></Q>
                <Slope><Manual Value="1"/></Slope>
              </Bands.0>
              <Bands.1>
                <IsOn><Manual Value="true"/></IsOn>
                <Mode><Manual Value="2"/></Mode>
                <Freq><Manual Value="100.0"/></Freq>
                <Gain><Manual Value="3.5"/></Gain>
                <Q><Manual Value="1.2"/></Q>
                <Slope><Manual Value="0"/></Slope>
              </Bands.1>
              <Bands.2>
                <IsOn><Manual Value="false"/></IsOn>
                <Mode><Manual Value="2"/></Mode>
                <Freq><Manual Value="500.0"/></Freq>
                <Gain><Manual Value="0.0"/></Gain>
                <Q><Manual Value="0.7"/></Q>
                <Slope><Manual Value="0"/></Slope>
              </Bands.2>
              <Bands.3>
                <IsOn><Manual Value="true"/></IsOn>
                <Mode><Manual Value="5"/></Mode>
                <Freq><Manual Value="8000.0"/></Freq>
                <Gain><Manual Value="0.0"/></Gain>
                <Q><Manual Value="0.7"/></Q>
                <Slope><Manual Value="0"/></Slope>
              </Bands.3>
            </Eq8>
            <GlueCompressor Id="2">
              <On><Manual Value="true"/></On>
              <Threshold><Manual Value="-18.0"/></Threshold>
              <Ratio><Manual Value="4.0"/></Ratio>
              <Attack><Manual Value="0.03"/></Attack>
              <Release><Manual Value="0.2"/></Release>
              <MakeupGain><Manual Value="3.0"/></MakeupGain>
            </GlueCompressor>
          </Devices>
        </DeviceChain>
      </AudioTrack>

      <!-- SNARE - Audio Track with EQ Eight + Compressor + Saturator -->
      <AudioTrack Id="2">
        <Name>
          <EffectiveName Value="Snare"/>
        </Name>
        <ColorIndex Value="7"/>
        <TrackGroupId Value="10"/>
        <MuteState><Manual Value="false"/></MuteState>
        <DeviceChain>
          <Mixer>
            <Volume><Manual Value="0.891251"/></Volume>
            <Pan><Manual Value="0.0"/></Pan>
          </Mixer>
          <Devices>
            <Eq8 Id="3">
              <On><Manual Value="true"/></On>
              <Bands.0>
                <IsOn><Manual Value="true"/></IsOn>
                <Mode><Manual Value="0"/></Mode>
                <Freq><Manual Value="100.0"/></Freq>
                <Gain><Manual Value="0.0"/></Gain>
                <Q><Manual Value="0.7"/></Q>
                <Slope><Manual Value="0"/></Slope>
              </Bands.0>
              <Bands.1>
                <IsOn><Manual Value="true"/></IsOn>
                <Mode><Manual Value="2"/></Mode>
                <Freq><Manual Value="200.0"/></Freq>
                <Gain><Manual Value="-4.0"/></Gain>
                <Q><Manual Value="2.0"/></Q>
                <Slope><Manual Value="0"/></Slope>
              </Bands.1>
              <Bands.2>
                <IsOn><Manual Value="true"/></IsOn>
                <Mode><Manual Value="4"/></Mode>
                <Freq><Manual Value="6000.0"/></Freq>
                <Gain><Manual Value="2.5"/></Gain>
                <Q><Manual Value="0.7"/></Q>
                <Slope><Manual Value="0"/></Slope>
              </Bands.2>
            </Eq8>
            <Compressor2 Id="4">
              <On><Manual Value="true"/></On>
              <Threshold><Manual Value="-22.0"/></Threshold>
              <Ratio><Manual Value="6.0"/></Ratio>
              <Attack><Manual Value="5.0"/></Attack>
              <Release><Manual Value="80.0"/></Release>
              <GainOutput><Manual Value="4.0"/></GainOutput>
              <Knee><Manual Value="3.0"/></Knee>
            </Compressor2>
            <Saturator Id="5">
              <On><Manual Value="true"/></On>
              <Drive><Manual Value="8.0"/></Drive>
              <Output><Manual Value="-2.0"/></Output>
              <DryWet><Manual Value="0.4"/></DryWet>
              <WaveShaper><Manual Value="1"/></WaveShaper>
            </Saturator>
          </Devices>
        </DeviceChain>
      </AudioTrack>

      <!-- BASS - Audio Track with EQ Eight + Utility + third party plugin -->
      <AudioTrack Id="3">
        <Name>
          <EffectiveName Value="Bass"/>
        </Name>
        <ColorIndex Value="12"/>
        <TrackGroupId Value="-1"/>
        <MuteState><Manual Value="false"/></MuteState>
        <DeviceChain>
          <Mixer>
            <Volume><Manual Value="0.707946"/></Volume>
            <Pan><Manual Value="-0.1"/></Pan>
          </Mixer>
          <Devices>
            <Eq8 Id="6">
              <On><Manual Value="true"/></On>
              <Bands.0>
                <IsOn><Manual Value="true"/></IsOn>
                <Mode><Manual Value="0"/></Mode>
                <Freq><Manual Value="40.0"/></Freq>
                <Gain><Manual Value="0.0"/></Gain>
                <Q><Manual Value="0.7"/></Q>
                <Slope><Manual Value="1"/></Slope>
              </Bands.0>
              <Bands.1>
                <IsOn><Manual Value="true"/></IsOn>
                <Mode><Manual Value="2"/></Mode>
                <Freq><Manual Value="80.0"/></Freq>
                <Gain><Manual Value="2.0"/></Gain>
                <Q><Manual Value="1.5"/></Q>
                <Slope><Manual Value="0"/></Slope>
              </Bands.1>
              <Bands.2>
                <IsOn><Manual Value="true"/></IsOn>
                <Mode><Manual Value="2"/></Mode>
                <Freq><Manual Value="2000.0"/></Freq>
                <Gain><Manual Value="-3.0"/></Gain>
                <Q><Manual Value="0.8"/></Q>
                <Slope><Manual Value="0"/></Slope>
              </Bands.2>
              <Bands.3>
                <IsOn><Manual Value="true"/></IsOn>
                <Mode><Manual Value="5"/></Mode>
                <Freq><Manual Value="12000.0"/></Freq>
                <Gain><Manual Value="0.0"/></Gain>
                <Q><Manual Value="0.7"/></Q>
                <Slope><Manual Value="0"/></Slope>
              </Bands.3>
            </Eq8>
            <Utility Id="7">
              <On><Manual Value="true"/></On>
              <Gain><Manual Value="2.0"/></Gain>
              <Pan><Manual Value="0.0"/></Pan>
              <MonoLeft><Manual Value="false"/></MonoLeft>
              <MonoRight><Manual Value="false"/></MonoRight>
              <StereoWidth><Manual Value="1.0"/></StereoWidth>
              <Mute><Manual Value="false"/></Mute>
              <PhaseInvertLeft><Manual Value="false"/></PhaseInvertLeft>
              <PhaseInvertRight><Manual Value="false"/></PhaseInvertRight>
              <BassMonoFrequency><Manual Value="150.0"/></BassMonoFrequency>
            </Utility>
            <!-- Third-party VST plugin -->
            <PluginDevice Id="8">
              <On><Manual Value="true"/></On>
              <PluginDesc>
                <VstPluginInfo>
                  <PlugName Value="Decapitator"/>
                  <Manufacturer Value="Soundtoys"/>
                </VstPluginInfo>
              </PluginDesc>
            </PluginDevice>
          </Devices>
        </DeviceChain>
      </AudioTrack>

      <!-- GUITARS Group Track -->
      <GroupTrack Id="10">
        <Name>
          <EffectiveName Value="Drums Bus"/>
        </Name>
        <ColorIndex Value="3"/>
        <TrackGroupId Value="-1"/>
        <MuteState><Manual Value="false"/></MuteState>
        <DeviceChain>
          <Mixer>
            <Volume><Manual Value="0.841395"/></Volume>
            <Pan><Manual Value="0.0"/></Pan>
          </Mixer>
          <Devices>
            <GlueCompressor Id="9">
              <On><Manual Value="true"/></On>
              <Threshold><Manual Value="-12.0"/></Threshold>
              <Ratio><Manual Value="2.0"/></Ratio>
              <Attack><Manual Value="0.3"/></Attack>
              <Release><Manual Value="0.5"/></Release>
              <MakeupGain><Manual Value="1.5"/></MakeupGain>
            </GlueCompressor>
          </Devices>
        </DeviceChain>
      </GroupTrack>

      <!-- VOCALS - Audio Track with Reverb + Delay + Chorus -->
      <AudioTrack Id="4">
        <Name>
          <EffectiveName Value="Lead Vocal"/>
        </Name>
        <ColorIndex Value="18"/>
        <TrackGroupId Value="-1"/>
        <MuteState><Manual Value="false"/></MuteState>
        <DeviceChain>
          <Mixer>
            <Volume><Manual Value="1.0"/></Volume>
            <Pan><Manual Value="0.0"/></Pan>
          </Mixer>
          <Devices>
            <Eq8 Id="11">
              <On><Manual Value="true"/></On>
              <Bands.0>
                <IsOn><Manual Value="true"/></IsOn>
                <Mode><Manual Value="0"/></Mode>
                <Freq><Manual Value="120.0"/></Freq>
                <Gain><Manual Value="0.0"/></Gain>
                <Q><Manual Value="0.7"/></Q>
                <Slope><Manual Value="1"/></Slope>
              </Bands.0>
              <Bands.1>
                <IsOn><Manual Value="true"/></IsOn>
                <Mode><Manual Value="2"/></Mode>
                <Freq><Manual Value="3000.0"/></Freq>
                <Gain><Manual Value="1.5"/></Gain>
                <Q><Manual Value="1.0"/></Q>
                <Slope><Manual Value="0"/></Slope>
              </Bands.1>
            </Eq8>
            <Gate Id="12">
              <On><Manual Value="true"/></On>
              <Threshold><Manual Value="-45.0"/></Threshold>
              <Return><Manual Value="-42.0"/></Return>
              <Floor><Manual Value="-80.0"/></Floor>
              <Attack><Manual Value="0.5"/></Attack>
              <Hold><Manual Value="50.0"/></Hold>
              <Release><Manual Value="100.0"/></Release>
            </Gate>
          </Devices>
        </DeviceChain>
      </AudioTrack>

      <!-- RETURN A - Reverb -->
      <ReturnTrack Id="5">
        <Name>
          <EffectiveName Value="Reverb Return"/>
        </Name>
        <ColorIndex Value="20"/>
        <TrackGroupId Value="-1"/>
        <DeviceChain>
          <Mixer>
            <Volume><Manual Value="0.7"/></Volume>
            <Pan><Manual Value="0.0"/></Pan>
          </Mixer>
          <Devices>
            <Reverb Id="13">
              <On><Manual Value="true"/></On>
              <DecayTime><Manual Value="2.5"/></DecayTime>
              <PreDelay><Manual Value="15.0"/></PreDelay>
              <RoomSize><Manual Value="0.7"/></RoomSize>
              <DryWet><Manual Value="1.0"/></DryWet>
              <InDiffuseSize><Manual Value="0.6"/></InDiffuseSize>
            </Reverb>
          </Devices>
        </DeviceChain>
      </ReturnTrack>

      <!-- RETURN B - Delay -->
      <ReturnTrack Id="6">
        <Name>
          <EffectiveName Value="Delay Return"/>
        </Name>
        <ColorIndex Value="15"/>
        <TrackGroupId Value="-1"/>
        <DeviceChain>
          <Mixer>
            <Volume><Manual Value="0.6"/></Volume>
            <Pan><Manual Value="0.0"/></Pan>
          </Mixer>
          <Devices>
            <Delay Id="14">
              <On><Manual Value="true"/></On>
              <LDelay>
                <Time><Manual Value="250.0"/></Time>
                <Sync><Manual Value="false"/></Sync>
                <Beat><Manual Value="1/4"/></Beat>
              </LDelay>
              <RDelay>
                <Time><Manual Value="375.0"/></Time>
                <Sync><Manual Value="false"/></Sync>
                <Beat><Manual Value="3/8"/></Beat>
              </RDelay>
              <Feedback><Manual Value="0.45"/></Feedback>
              <DryWet><Manual Value="1.0"/></DryWet>
            </Delay>
          </Devices>
        </DeviceChain>
      </ReturnTrack>

    </Tracks>

    <MasterTrack>
      <Name>
        <EffectiveName Value="Master"/>
      </Name>
      <DeviceChain>
        <Mixer>
          <Volume><Manual Value="1.0"/></Volume>
          <Pan><Manual Value="0.0"/></Pan>
        </Mixer>
        <Devices>
          <Limiter Id="15">
            <On><Manual Value="true"/></On>
            <Ceiling><Manual Value="-0.3"/></Ceiling>
            <Lookahead><Manual Value="1.5"/></Lookahead>
            <Release><Manual Value="100.0"/></Release>
            <StereoLink><Manual Value="true"/></StereoLink>
          </Limiter>
        </Devices>
      </DeviceChain>
    </MasterTrack>

    <Transport>
      <Tempo>
        <LomId Value="0"/>
        <Manual Value="124.0"/>
        <MidiControllerRange>
          <Min Value="60"/>
          <Max Value="200"/>
        </MidiControllerRange>
      </Tempo>
      <TimeSignature>
        <TimeSignatures>
          <RemoteableTimeSignature Id="0">
            <Numerator Value="4"/>
            <Denominator Value="4"/>
          </RemoteableTimeSignature>
        </TimeSignatures>
      </TimeSignature>
    </Transport>

  </LiveSet>
</Ableton>
'''


def create_synthetic_als(path: Path):
    """Write synthetic XML compressed as .als (gzip)."""
    with gzip.open(path, "wb") as f:
        f.write(SYNTHETIC_ALS_XML.encode("utf-8"))
    print(f"  Created synthetic .als: {path}")


def run_tests():
    test_dir = Path("/tmp/als_test")
    test_dir.mkdir(exist_ok=True)
    out_dir = test_dir / "output"

    print("\n" + "="*55)
    print("  ABLETON → REAPER PIPELINE TEST")
    print("="*55)

    # Create synthetic .als
    als_path = test_dir / "test_project.als"
    create_synthetic_als(als_path)

    # Step 1: Parse
    print("\n[1] Parsing .als...")
    project = parse_als(als_path)
    print(f"    ✓ Parsed {len(project['tracks'])} tracks")
    print(f"    ✓ Tempo: {project['tempo']} BPM")
    print(f"    ✓ Time sig: {project['time_signature']}")

    for t in project["tracks"]:
        dev_names = [d.get("type", "?") for d in t["devices"]]
        print(f"    Track '{t['name']}' ({t['type']}): [{', '.join(dev_names)}]")

    assert len(project["tracks"]) > 0, "No tracks parsed"
    assert project["tempo"] == 124.0, f"Wrong tempo: {project['tempo']}"

    # Check EQ bands parsed
    kick = next(t for t in project["tracks"] if t["name"] == "Kick Drum")
    eq = next(d for d in kick["devices"] if d["type"] == "EQ Eight")
    assert len(eq["bands"]) > 0, "No EQ bands parsed"
    print(f"\n    EQ Eight bands on Kick Drum:")
    for b in eq["bands"]:
        status = "ON " if b["enabled"] else "OFF"
        print(f"      [{status}] Band {b['index']}: {b['mode']:12} {b['freq']:8.1f}Hz  {b['gain_db']:+.1f}dB  Q={b['q']:.2f}")

    # Check third-party detection
    bass = next(t for t in project["tracks"] if t["name"] == "Bass")
    tp_plugins = [d for d in bass["devices"] if d.get("type") == "THIRD_PARTY"]
    assert len(tp_plugins) == 1, f"Expected 1 third-party plugin, got {len(tp_plugins)}"
    print(f"\n    Third-party plugin detected: {tp_plugins[0]['name']} ({tp_plugins[0]['plugin_type']})")

    # Step 2: Generate RPP
    print("\n[2] Generating Reaper project...")
    out_dir.mkdir(exist_ok=True)
    rpp_path = out_dir / "test_project.RPP"
    report = generate_rpp(project, rpp_path, stem_dir="./Stems")
    print(f"    ✓ Generated: {rpp_path}")
    print(f"    Warnings: {len(report['warnings'])}")
    print(f"    Third-party: {len(report['third_party_plugins'])}")
    print(f"    Approximations: {len(report['approximations'])}")

    # Validate RPP file exists and has content
    assert rpp_path.exists(), "RPP file not created"
    rpp_content = rpp_path.read_text()
    assert "REAPER_PROJECT" in rpp_content, "Missing REAPER_PROJECT header"
    assert "Kick Drum" in rpp_content, "Missing track name"
    assert "ReaEQ" in rpp_content or "reaEQ" in rpp_content, "Missing ReaEQ reference"
    assert "ReaComp" in rpp_content or "reaComp" in rpp_content, "Missing ReaComp"
    print(f"    ✓ RPP content validated ({len(rpp_content)} chars)")

    # Step 3: Generate report
    print("\n[3] Generating migration report...")
    report_path = out_dir / "test_project_migration_report.txt"
    report_text = generate_report(report, report_path)
    assert report_path.exists()
    print(f"    ✓ Report generated")
    print("\n" + "─"*55)
    print("  MIGRATION REPORT PREVIEW:")
    print("─"*55)
    # Print first 50 lines of report
    for line in report_text.split("\n")[:60]:
        print("  " + line)

    print("\n" + "="*55)
    print("  ALL TESTS PASSED ✓")
    print(f"  Output files in: {out_dir}")
    print("="*55 + "\n")

    return True


if __name__ == "__main__":
    success = run_tests()
    sys.exit(0 if success else 1)
