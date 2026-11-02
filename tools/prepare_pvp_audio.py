#!/usr/bin/env python3
"""Build the PvP weapon audio bank from the user's retail ISO (no shipped assets)."""
import argparse
import hashlib
import io
import json
import math
import array
import sys
import struct
import tempfile
import wave
from pathlib import Path
from extract_mp_map import XboxIso

WEAPONS = ((1, 'pst', '00'), (4, 'smg', '00'), (6, 'ak1', '00'),
           (5, 'asr', '03'), (3, 'snr', '03'), (10, 'p90', '03'),
           (16, 'mp1', '04'), (9, 'sm3', '06'), (13, 'm16', '07'),
           (12, 'mgn', '08'))

# Tactical FPS gunshot ballistic profiles:
# (min_dist, max_dist, crossover, vol_scale, distant_sample_name)
WEAPON_AUDIO_PROFILES = {
    1:  (10.0, 250.0, 250.0, 0.60, 'PstlDst0'),  # DC3 Elite Handgun
    3:  (25.0, 360.0, 360.0, 1.50, 'MgnDst0'),   # Walther 2000 Sniper Rifle
    4:  (12.0, 270.0, 270.0, 1.00, 'MgnDst0'),   # Uzi SMG
    5:  (20.0, 320.0, 320.0, 0.80, 'MgnDst0'),   # G36C Assault Rifle
    6:  (22.0, 320.0, 320.0, 1.30, 'MgnDst0'),   # AK47 Assault Rifle
    9:  (12.0, 270.0, 270.0, 1.00, 'MgnDst0'),   # MAC10 Elite SMG
    10: (14.0, 270.0, 270.0, 0.70, 'MgnDst0'),   # P90 SMG
    12: (18.0, 290.0, 290.0, 1.10, 'MgnDst0'),   # Magnum .44 Heavy Revolver
    13: (20.0, 320.0, 320.0, 0.80, 'MgnDst0'),   # M16 A2 Assault Rifle
    15: (10.0, 250.0, 250.0, 0.60, 'PstlDst0'),  # Glock Handgun
    16: (14.0, 270.0, 270.0, 0.90, 'MgnDst0'),   # MP5 SMG
}

# Authentic full-body signature gunshot waveforms across the arsenal.
# Looping bursts with 88ms mid-slice samples (_M0..3) fail in discrete multiplayer
# and silence weapons because native sub_0013FC20 leaves 0x79=0 when has_tail != 0.
# Assigning each weapon its authentic full shot waveform (_E0 or FP master) in single-shot mode (has_tail=0)
# gives all 11 weapons full punch, spatial reach, and realistic reverb.
PRIMARY_SHOT_SAMPLES = {
    1:  'Pstl0',         # DC3 Elite Handgun
    3:  'CarrieSnpr',    # Walther 2000 Sniper Rifle
    4:  'E_Uzi_E0',      # Uzi SMG
    5:  'E_KarlDH_E0',   # G36C Assault Rifle
    6:  'E_BlackHd_E0',  # AK47 Assault Rifle
    9:  'E_Mac10_E0',    # MAC10 Elite SMG
    10: 'E_AliasE0',     # P90 SMG
    12: 'PvpMagnum0',    # Magnum .44 Heavy Revolver (authentic heavy cylinder boom)
    13: 'E_Navy_E0',     # M16 A2 Assault Rifle
    15: 'PvpGlock0',     # Glock Handgun
    16: 'E_Rock_E0',     # MP5 SMG
}

def u32(data, at):
    return struct.unpack_from('<I', data, at)[0]

def key_of(name):
    value = 0
    for c in name.upper():
        digit = {'-': 1, '/': 2, '_': 39}.get(c)
        if digit is None:
            digit = ord(c)-45 if '0' <= c <= '9' else ord(c)-52 if 'A' <= c <= 'Z' else 0
        value = (value*40+digit) & ((1 << 64)-1)
    for _ in range(max(0, 12-len(name))):
        value = value*40 & ((1 << 64)-1)
    return struct.pack('<Q', value)

def read(iso, parts):
    entry = iso.find(parts)
    if not entry or entry.is_dir:
        raise ValueError('ISO resource absent: '+'/'.join(parts))
    iso.file.seek(entry.offset)
    data = iso.file.read(entry.size)
    if len(data) != entry.size:
        raise ValueError('Truncated resource: '+entry.name)
    return data

def samples_of(data):
    if u32(data, 0) != 0x809:
        raise ValueError('Unexpected AWD version')
    payload = u32(data, 8)
    head = u32(data, 12)+12
    node = u32(data, head+4)
    samples = {}
    seen = set()
    while node != head:
        if node in seen or len(seen) >= 128 or node+16 > payload:
            raise ValueError('Invalid AWD sample list')
        seen.add(node)
        descriptor = u32(data, node+8)
        if descriptor+0x5C > payload:
            raise ValueError('Invalid AWD descriptor')
        desc = bytearray(data[descriptor:descriptor+0x5C])
        name_at = u32(desc, 4)
        end = data.find(b'\0', name_at, payload)
        if end < 0:
            raise ValueError('Invalid sample name')
        name = data[name_at:end].decode('ascii')
        size, offset = u32(desc, 0x18), u32(desc, 0x4C)
        if u32(desc, 0x14) != 1 or not 8000 <= u32(desc, 0x10) <= 48000 or not size or size % 2:
            raise ValueError('Unsupported AI sample format: '+name)
        pcm = data[payload+offset:payload+offset+size]
        if len(pcm) != size:
            raise ValueError('Truncated PCM sample: '+name)
        samples[key_of(name)] = (name, desc, pcm)
        node = u32(data, node+4)
    return samples

def variant_of(stage, prefix):
    table, count = struct.unpack_from('<II', stage, 4)
    for i in range(count):
        entry = table+40*i
        name = stage[entry:entry+16].split(b'\0')[0].decode('ascii')
        if name.endswith('bg1_'+prefix):
            offset = struct.unpack_from('<i', stage, entry+0x18)[0]
            if not u32(stage, entry+0x20):
                offset = struct.unpack_from('<i', stage, entry+0x1C)[0]
                if not u32(stage, entry+0x24):
                    raise ValueError('No audio variant: '+name)
            at = entry+offset
            variant = stage[at:at+0xB0]
            if len(variant) != 0xB0:
                raise ValueError('Truncated variant')
            return stage[entry+16:entry+24], variant
    raise ValueError('Weapon definition absent: '+prefix)

def required_keys(variant):
    count = u32(variant, 0x90)
    if not 1 <= count <= 10:
        raise ValueError('Invalid variant sample count')
    offsets = [0x18+8*i for i in range(count)]+[0x78, 0x80]
    if variant[0xAC]:
        offsets += [0x68, 0x70]
    return {variant[o:o+8] for o in offsets if any(variant[o:o+8])}

def compact_sample(sample):
    """Low-pass 48 kHz mono PCM to 24 kHz; retain native timing and gun identity."""
    name, original, pcm = sample
    if u32(original, 0x10) != 48000:
        return sample
    source = array.array('h')
    source.frombytes(pcm)
    if sys.byteorder != 'little':
        source.byteswap()
    taps = []
    for n in range(-15, 16):
        sinc = 0.5 if n == 0 else math.sin(math.pi*0.5*n)/(math.pi*n)
        taps.append(sinc*(0.54+0.46*math.cos(math.pi*n/15)))
    gain = sum(taps)
    taps = [t/gain for t in taps]
    output = array.array('h')
    for at in range(0, len(source), 2):
        value = sum(t*source[min(len(source)-1, max(0, at+n-15))] for n,t in enumerate(taps))
        output.append(max(-32768, min(32767, round(value))))
    if sys.byteorder != 'little':
        output.byteswap()
    result = output.tobytes()
    desc = bytearray(original)
    for offset in (0x10, 0x2C): struct.pack_into('<I', desc, offset, 24000)
    for offset in (0x18, 0x34): struct.pack_into('<I', desc, offset, len(result))
    return name, desc, result

def build_bank(template, samples):
    data = bytearray(template[:0x5C])
    payload = bytearray()
    nodes = []
    for _, (name, original, pcm) in sorted(samples.items()):
        data.extend(b'\0'*(-len(data) % 4))
        descriptor = len(data)
        desc = bytearray(original)
        node = descriptor+0x5C
        name_at = node+16
        desc[0:12] = struct.pack('<III', 0, name_at, 0)
        for offset in (0x20, 0x3C, 0x48, 0x50):
            struct.pack_into('<I', desc, offset, 0)
        payload.extend(b'\0'*(-len(payload) % 256))
        struct.pack_into('<I', desc, 0x4C, len(payload))
        payload.extend(pcm)
        data.extend(desc)
        data.extend(struct.pack('<4I', 0, 0, descriptor, 0))
        data.extend(name.encode('ascii')+b'\0')
        nodes.append(node)
    head = 0x38
    for i, node in enumerate(nodes):
        struct.pack_into('<II', data, node, nodes[i-1] if i else head,
                         nodes[i+1] if i+1 < len(nodes) else head)
    struct.pack_into('<II', data, head, nodes[-1], nodes[0])
    data.extend(b'\0'*(-len(data) % 2048))
    struct.pack_into('<I', data, 8, len(data))
    struct.pack_into('<I', data, 20, len(payload))
    data.extend(payload)
    data.extend(b'\0'*(-len(data) % 2048))
    if len(samples) > 120:
        raise ValueError('Native bank capacity exceeded')
    # Parse the generated artifact, then compare actual names and PCM bytes.
    reparsed = samples_of(data)
    if reparsed.keys() != samples.keys() or any(reparsed[k][2] != samples[k][2] for k in samples):
        raise ValueError('Generated AWD round-trip mismatch')
    return bytes(data)

def write_atomic(path, data):
    if path.exists() and path.read_bytes() == data:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as output:
        temporary = Path(output.name)
        output.write(data)
    try:
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)

def prepare(iso_path, output):
    iso = XboxIso(str(iso_path))
    try:
        template = read(iso, ['levels', 'level_00', 'stg_0001', 'AIWpns.awd'])
        samples = samples_of(template)  # prefer resident waveforms when keys are shared
        # Pre-collect waveforms from all weapon stages
        for _, _, level in WEAPONS:
            for k, s in samples_of(read(iso, ['levels', 'level_'+level, 'stg_0001', 'AIWpns.awd'])).items():
                samples.setdefault(k, s)

        # Glock has no EnemyWeapon entry. Its own unsuppressed first-person
        # waveform is embedded as RIFF at +38 in its DB, not a pistol fallback.
        glock = read(iso, ['levels', 'level_04', 'fpguns', 'bg1_gk1.db'])
        at = u32(glock, 0x38)
        with wave.open(io.BytesIO(glock[at:]), 'rb') as wav:
            if wav.getnchannels() != 1 or wav.getsampwidth() != 2:
                raise ValueError('Unexpected Glock waveform format')
            rate = wav.getframerate()
            pcm = wav.readframes(wav.getnframes())
        name = 'PvpGlock0'
        desc = bytearray(next(iter(samples.values()))[1])
        desc[4:8] = struct.pack('<I', 0)
        for offset in (0x10, 0x2C): struct.pack_into('<I', desc, offset, rate)
        for offset in (0x18, 0x34): struct.pack_into('<I', desc, offset, len(pcm))
        samples[key_of(name)] = (name, desc, pcm)

        # Magnum .44 authentic unsuppressed heavy revolver shot from level 08
        mgn = read(iso, ['levels', 'level_08', 'fpguns', 'bg1_mgn.db'])
        riff_m = 713728
        data_tag = mgn.find(b'data', riff_m)
        data_size = struct.unpack_from('<I', mgn, data_tag+4)[0]
        pcm_m = mgn[data_tag+8:data_tag+8+data_size]
        desc_m = bytearray(next(iter(samples.values()))[1])
        desc_m[4:8] = struct.pack('<I', 0)
        for offset in (0x10, 0x2C): struct.pack_into('<I', desc_m, offset, 48000)
        for offset in (0x18, 0x34): struct.pack_into('<I', desc_m, offset, len(pcm_m))
        samples[key_of('PvpMagnum0')] = ('PvpMagnum0', desc_m, pcm_m)

        variants = []
        provenance = []
        for wire, prefix, level in WEAPONS:
            stage = read(iso, ['levels', 'level_'+level, 'stg_0001', 'StLevel.bin'])
            key, var_bytes = variant_of(stage, prefix)
            var = bytearray(var_bytes)

            min_d, max_d, cross, vol, dist_sample = WEAPON_AUDIO_PROFILES.get(
                wire, (15.0, 300.0, 300.0, 0.80, 'MgnDst0')
            )

            # Apply weapon-specific min distance (punch), max distance, crossover and volume scale
            struct.pack_into('<f', var, 0x9C, min_d)
            struct.pack_into('<f', var, 0xA0, max_d)
            struct.pack_into('<f', var, 0xA4, cross)
            struct.pack_into('<f', var, 0xA8, vol)

            # Force single-shot mode (has_tail = 0) so discrete multiplayer network shots
            # reliably trigger sub_0014AE60 and immediately play the signature gunshot sound.
            var[0xAC] = 0

            # Assign authentic full-body signature gunshot sample to primary slot 0
            primary_name = PRIMARY_SHOT_SAMPLES[wire]
            var[0x18:0x20] = key_of(primary_name)
            var[0x20:0x68] = b'\0' * (0x68 - 0x20)
            struct.pack_into('<I', var, 0x90, 1)

            # Distant sample key setup: caliber-appropriate distant echo
            var[0x78:0x80] = key_of(dist_sample)
            var[0x80:0x88] = key_of(dist_sample)

            variant = bytes(var)
            for sample_key in required_keys(variant):
                if sample_key not in samples:
                    raise ValueError(f'Unresolved sample {sample_key.hex()} for {prefix}')
            variants.append((wire, key, variant))
            provenance.append({'weapon': wire, 'prefix': prefix, 'level': level, 'samples': len(required_keys(variant))})

        # Add Glock variant
        var_g = bytearray(variants[0][2])
        min_d, max_d, cross, vol, dist_sample = WEAPON_AUDIO_PROFILES[15]
        struct.pack_into('<f', var_g, 0x9C, min_d)
        struct.pack_into('<f', var_g, 0xA0, max_d)
        struct.pack_into('<f', var_g, 0xA4, cross)
        struct.pack_into('<f', var_g, 0xA8, vol)
        var_g[0xAC] = 0
        var_g[0x18:0x20] = key_of('PvpGlock0')
        var_g[0x20:0x68] = b'\0' * (0x68 - 0x20)
        struct.pack_into('<I', var_g, 0x90, 1)
        var_g[0x78:0x80] = key_of(dist_sample)
        var_g[0x80:0x88] = key_of(dist_sample)
        key_g = glock[0x10:0x18]
        variants.append((15, key_g, bytes(var_g)))
        provenance.append({'weapon': 15, 'prefix': 'gk1', 'source': 'level_04/fpguns/bg1_gk1.db RIFF+38', 'samples': 1})
        needed = set().union(*(required_keys(v) for _,_,v in variants))
        samples = {key: compact_sample(samples[key]) for key in needed}
        bank = build_bank(template, samples)
        # The existing arena reserves 634880 PCM bytes. Keep that layout intact.
        aligned_payload = (u32(bank, 20)+2047) & ~2047
        if aligned_payload > 634880:
            raise ValueError('PvP audio exceeds the native arena reservation')
        metadata = bytearray(struct.pack('<4sIII', b'PVA1', 1, len(variants), 0xBC))
        for wire, key, variant in sorted(variants):
            metadata.extend(struct.pack('<I', wire)+key+variant)
        write_atomic(output/'arsenal.awd', bank)
        write_atomic(output/'arsenal.bin', bytes(metadata))
        manifest = {'version': 1, 'weapons': provenance, 'samples': len(samples),
                    'header_bytes': u32(bank, 8), 'payload_bytes': u32(bank, 20),
                    'sha256': hashlib.sha256(bank).hexdigest(),
                    'normalization': '48 kHz samples low-pass filtered to 24 kHz; other rates unchanged'}
        write_atomic(output/'manifest.json', (json.dumps(manifest, indent=2)+'\n').encode())
        print(f'PvP audio ready: {len(variants)} weapons, {len(samples)} samples, {len(bank)} bytes')
    finally:
        iso.close()

if __name__ == '__main__':
    root = Path(__file__).resolve().parent.parent
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--iso', type=Path, default=root/'assets/Black.iso')
    parser.add_argument('--output', type=Path, default=root/'assets/pvp_audio')
    args = parser.parse_args()
    prepare(args.iso, args.output)
