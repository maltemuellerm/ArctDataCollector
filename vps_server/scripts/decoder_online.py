"""
OpenMetBuoy hex-payload decoder — VPS / online edition.

Adapted from OpenMetBuoy-v2021a/legacy_firmware/decoder/decoder.py.
CLI, plotting, and icecream dependencies removed so this file can run in a
plain Flask venv (pip install flask numpy scipy).

Public API
----------
    kind, metadata, packets = decode_message(hex_string)

where `packets` is a list of dataclass instances (GNSS_Packet, Waves_Packet,
Thermistors_Packet, ThermistorsMLX_Packet) — see individual classes below.
"""

import binascii
import struct
import datetime
import time
import os
import math
from dataclasses import dataclass

import numpy as np
import scipy.signal as signal

# ---------------------------------------------------------------------------
# make sure we are all UTC
os.environ["TZ"] = "UTC"
time.tzset()

# ---------------------------------------------------------------------------
# module constants

_BD_VERSION_NBR = "2.1"

# GNSS packets: 1 byte start + posix(4) + lat(4) + lon(4) + 1 byte end = 14
_BD_GNSS_PACKET_LENGTH = 14

# Wave spectra packets (2048-point FFT)
_BD_YWAVE_PACKET_MIN_BIN = 9
_BD_YWAVE_PACKET_MAX_BIN = 64
_BD_YWAVE_PACKET_SCALER = 65000
_BD_YWAVE_PACKET_SAMPLING_FREQ_HZ = 10.0
_BD_YWAVE_PACKET_NBR_SAMPLES_PER_SEGMENT = 2**11

_BD_YWAVE_NBR_BINS = _BD_YWAVE_PACKET_MAX_BIN - _BD_YWAVE_PACKET_MIN_BIN
_BD_YWAVE_PACKET_FRQ_RES = _BD_YWAVE_PACKET_SAMPLING_FREQ_HZ / _BD_YWAVE_PACKET_NBR_SAMPLES_PER_SEGMENT

_BD_YWAVE_PACKET_LENGTH = (
    1 + 4 + 4 + 4 * 4 + _BD_YWAVE_NBR_BINS * 2 + 2 + 1
)
assert _BD_YWAVE_PACKET_LENGTH == 138

# Thermistors packets (4 sensors)
_BD_THERM_MSG_FIXED_LENGTH = 3
_BD_THERM_MSG_NBR_THERMISTORS = 4
_BD_THERM_PACKET_NBR_BYTES_PER_THERMISTOR = 3
_BD_THERM_PACKET_LENGTH = (
    1 + 1 * 4 + _BD_THERM_PACKET_NBR_BYTES_PER_THERMISTOR * _BD_THERM_MSG_NBR_THERMISTORS
)
_BD_THERM_12BITS_TO_FLOAT_TEMPERATURE_FACTOR = 1.0 / 16.0

# Thermistors16 packets (16 sensors)
_BD_THERM16_MSG_FIXED_LENGTH = 3
_BD_THERM16_MSG_NBR_THERMISTORS = 16
_BD_THERM16_PACKET_NBR_BYTES_PER_THERMISTOR = 3
_BD_THERM16_PACKET_LENGTH = (
    1 + 1 * 4 + _BD_THERM16_PACKET_NBR_BYTES_PER_THERMISTOR * _BD_THERM16_MSG_NBR_THERMISTORS
)

# ThermistorsMLX packets (3 sensors + IR)
_BD_THERMMLX_MSG_FIXED_LENGTH = 3
_BD_THERMMLX_MSG_NBR_THERMISTORS = 3
_BD_THERMMLX_PACKET_NBR_BYTES_PER_THERMISTOR = 3
_BD_THERMMLX_PACKET_LENGTH = (
    1 + 4 + 5 + _BD_THERMMLX_PACKET_NBR_BYTES_PER_THERMISTOR * _BD_THERMMLX_MSG_NBR_THERMISTORS + 2
)

# 27 thermistors + 1 MLX packets
_BD_27THERM1MLX_MSG_FIXED_LENGTH = 3
_BD_27THERM1MLX_MSG_NBR_THERMISTORS = 27
_BD_27THERM1MLX_PACKET_NBR_BYTES_PER_THERMISTOR = 3
_BD_27THERM1MLX_PACKET_LENGTH = (
    1 + 4 + 5 + _BD_27THERM1MLX_PACKET_NBR_BYTES_PER_THERMISTOR * _BD_27THERM1MLX_MSG_NBR_THERMISTORS + 2
)

# ---------------------------------------------------------------------------
# binary helpers


def _byte_to_char(b):
    return chr(b)


def _one_byte_to_int(b):
    return struct.unpack('B', bytes(b))[0]


def _one_byte_to_signed_int(b):
    return struct.unpack('b', bytes(b))[0]


def _two_bytes_to_int(b):
    return struct.unpack('h', bytes(b))[0]


def _four_bytes_to_long(b):
    return struct.unpack('<l', bytes(b))[0]


def _four_bytes_to_int(b):
    return struct.unpack('<i', bytes(b))[0]


def _four_bytes_to_float(b):
    return struct.unpack('<f', bytes(b))[0]


# ---------------------------------------------------------------------------
# data classes


@dataclass
class Spectral_Moments:
    m0: float
    m2: float
    m4: float


@dataclass
class GNSS_Packet:
    datetime_fix: datetime.datetime
    latitude: float
    longitude: float
    is_valid: bool


@dataclass
class GNSS_Metadata:
    nbr_gnss_fixes: int


@dataclass
class Waves_Packet:
    datetime_fix: datetime.datetime
    spectrum_number: int
    Hs: float
    Tz: float
    Tc: float
    _array_max_value: float
    _array_uint16: object
    list_frequencies: list
    list_acceleration_energies: list
    frequency_resolution: float
    list_elevation_energies: list
    wave_spectral_moments: Spectral_Moments
    is_valid: bool
    processed_list_frequencies: list
    processed_list_elevation_energies: list
    processed_wave_spectral_moments: Spectral_Moments
    processed_Hs: float
    processed_Tz: float
    processed_Tc: float
    low_frequency_index_cutoff: int


@dataclass
class Waves_Metadata:
    pass


@dataclass
class Thermistors_Reading:
    mean_temperature: float
    range_temperature: float
    probe_id: int


@dataclass
class Thermistors_Packet:
    datetime_packet: datetime.datetime
    thermistors_readings: list


@dataclass
class ThermistorsMLX_Packet:
    datetime_packet: datetime.datetime
    thermistors_readings: list
    ir_target_temp: float
    ir_sensor_temp: float
    ir_target_temp_range: float


@dataclass
class Thermistors_Metadata:
    nbr_thermistors_measurements: int


# ---------------------------------------------------------------------------
# spectral processing helper


def _find_low_frequency_cutoff(list_frequencies, list_elevation_energies):
    normalized = -np.array(list_elevation_energies) / np.max(list_elevation_energies)
    peaks_output = signal.find_peaks(normalized, distance=3, prominence=0.05)
    peaks = list(peaks_output[0])
    if not peaks:
        peaks = [0]

    first_peak = peaks[0]
    if list_frequencies[first_peak] > 0.10:
        first_peak = 0
    if list_elevation_energies[first_peak] > (
        (list_elevation_energies[0] + list_elevation_energies[1]) / 2.0
    ):
        first_peak = 0

    return int(first_peak)  # ensure plain Python int, not numpy int64


# ---------------------------------------------------------------------------
# packet / message decoders


def _message_kind(bin_msg):
    first_char = _byte_to_char(bin_msg[0])
    valid = ["G", "Y", "T", "U", "V", "W"]
    if first_char not in valid:
        raise ValueError("Unknown message kind: {!r} (valid: {})".format(first_char, valid))
    return first_char


def _decode_gnss_packet(bin_packet):
    assert len(bin_packet) == _BD_GNSS_PACKET_LENGTH
    assert _byte_to_char(bin_packet[0]) == 'F'

    posix = _four_bytes_to_long(bin_packet[1:5])
    lat = _four_bytes_to_long(bin_packet[5:9]) / 1.0e7
    lon = _four_bytes_to_long(bin_packet[9:13]) / 1.0e7

    trailing = _byte_to_char(bin_packet[13])
    assert trailing in ['E', 'F']

    return GNSS_Packet(
        datetime_fix=datetime.datetime.utcfromtimestamp(posix),
        latitude=lat,
        longitude=lon,
        is_valid=True,
    )


def _decode_gnss_message(bin_msg):
    assert _message_kind(bin_msg) == 'G'
    nbr_fixes = _one_byte_to_int(bin_msg[1:2])
    metadata = GNSS_Metadata(nbr_gnss_fixes=nbr_fixes)

    packets = []
    start = 2
    while True:
        assert _byte_to_char(bin_msg[start]) == 'F'
        pkt = _decode_gnss_packet(bin_msg[start: start + _BD_GNSS_PACKET_LENGTH])
        packets.append(pkt)
        trailing = _byte_to_char(bin_msg[start + _BD_GNSS_PACKET_LENGTH - 1])
        if trailing == 'E':
            break
        start += _BD_GNSS_PACKET_LENGTH - 1

    return metadata, packets


def _decode_ywave_packet(bin_packet):
    assert len(bin_packet) == _BD_YWAVE_PACKET_LENGTH
    assert _byte_to_char(bin_packet[0]) == 'Y'
    assert _byte_to_char(bin_packet[-1]) == 'E'

    i = 1
    posix = _four_bytes_to_long(bin_packet[i:i+4]); i += 4
    spectrum_number = _four_bytes_to_int(bin_packet[i:i+4]); i += 4
    Hs = _four_bytes_to_float(bin_packet[i:i+4]); i += 4
    Tz = 1.0 / _four_bytes_to_float(bin_packet[i:i+4]); i += 4
    Tc = 1.0 / _four_bytes_to_float(bin_packet[i:i+4]); i += 4
    max_val = _four_bytes_to_float(bin_packet[i:i+4]); i += 4

    n_bytes = _BD_YWAVE_NBR_BINS * 2
    arr_uint16 = struct.unpack('<' + _BD_YWAVE_NBR_BINS * 'H', bin_packet[i:i+n_bytes])
    is_valid = Hs > 1e-5

    freqs, accel_e = [], []
    for idx, v in enumerate(arr_uint16):
        freqs.append((_BD_YWAVE_PACKET_MIN_BIN + idx) * _BD_YWAVE_PACKET_FRQ_RES)
        accel_e.append(v * max_val / _BD_YWAVE_PACKET_SCALER)

    omega = [2.0 * math.pi * f for f in freqs]
    omega4 = [math.pow(w, 4) for w in omega]
    elev_e = [a / w4 for a, w4 in zip(accel_e, omega4)]

    def moment(fl, el, order):
        return float(np.trapz([math.pow(f, order) * e for f, e in zip(fl, el)], fl))

    m0 = moment(freqs, elev_e, 0)
    m2 = moment(freqs, elev_e, 2)
    m4 = moment(freqs, elev_e, 4)
    moments = Spectral_Moments(m0, m2, m4)

    cutoff = _find_low_frequency_cutoff(freqs, elev_e)
    proc_freqs = freqs[cutoff:]
    proc_elev = elev_e[cutoff:]
    pm0 = moment(proc_freqs, proc_elev, 0)
    pm2 = moment(proc_freqs, proc_elev, 2)
    pm4 = moment(proc_freqs, proc_elev, 4)
    proc_moments = Spectral_Moments(pm0, pm2, pm4)
    proc_Hs = 4 * math.sqrt(pm0)
    proc_Tz = 1.0 / math.sqrt(pm2 / pm0)
    proc_Tc = 1.0 / math.sqrt(pm4 / pm2)
    proc_elev_full = cutoff * [math.nan] + proc_elev

    return Waves_Packet(
        datetime_fix=datetime.datetime.utcfromtimestamp(posix),
        spectrum_number=spectrum_number,
        Hs=Hs, Tz=Tz, Tc=Tc,
        _array_max_value=max_val,
        _array_uint16=list(arr_uint16),
        list_frequencies=freqs,
        list_acceleration_energies=accel_e,
        frequency_resolution=_BD_YWAVE_PACKET_FRQ_RES,
        list_elevation_energies=elev_e,
        wave_spectral_moments=moments,
        is_valid=is_valid,
        processed_list_frequencies=freqs,
        processed_list_elevation_energies=proc_elev_full,
        processed_wave_spectral_moments=proc_moments,
        processed_Hs=proc_Hs,
        processed_Tz=proc_Tz,
        processed_Tc=proc_Tc,
        low_frequency_index_cutoff=cutoff,
    )


def _decode_ywave_message(bin_msg):
    assert _message_kind(bin_msg) == 'Y'
    return Waves_Metadata(), [_decode_ywave_packet(bin_msg)]


def _decode_thermistor_reading(b3):
    id_6 = _one_byte_to_int(b3[0:1]) // 4
    r2hi = _one_byte_to_int(b3[0:1]) % 4
    r2hi_lo = r2hi % 2
    r2hi_hi = (r2hi - r2hi_lo) // 2
    r8mid = _one_byte_to_int(b3[1:2])
    r2lo = _one_byte_to_int(b3[2:3]) // 64
    reading_bin = r2lo + (2**2) * r8mid + (2**10) * r2hi_lo
    if r2hi_hi:
        reading_bin = reading_bin - 2**11 - 1
    range_6 = _one_byte_to_int(b3[2:3]) % 64

    return Thermistors_Reading(
        mean_temperature=reading_bin * _BD_THERM_12BITS_TO_FLOAT_TEMPERATURE_FACTOR,
        range_temperature=range_6 * _BD_THERM_12BITS_TO_FLOAT_TEMPERATURE_FACTOR,
        probe_id=id_6,
    )


def _decode_thermistors_packet(bin_packet, nbr):
    assert _byte_to_char(bin_packet[0]) == 'P'
    i = 1
    posix = _four_bytes_to_long(bin_packet[i:i+4]); i += 4
    readings = []
    for _ in range(nbr):
        readings.append(_decode_thermistor_reading(bin_packet[i:i+3]))
        i += 3
    return Thermistors_Packet(
        datetime_packet=datetime.datetime.utcfromtimestamp(posix),
        thermistors_readings=readings,
    )


def _decode_thermistorsmlx_packet(bin_packet, nbr):
    assert _byte_to_char(bin_packet[0]) == 'P'
    i = 1
    posix = _four_bytes_to_long(bin_packet[i:i+4]); i += 4
    ir_target = _two_bytes_to_int(bin_packet[i:i+2]) / 100.0; i += 2
    ir_sensor = _two_bytes_to_int(bin_packet[i:i+2]) / 100.0; i += 2
    ir_range = _one_byte_to_int(bin_packet[i:i+1]) / 20.0; i += 1
    readings = []
    for _ in range(nbr):
        readings.append(_decode_thermistor_reading(bin_packet[i:i+3]))
        i += 3
    return ThermistorsMLX_Packet(
        datetime_packet=datetime.datetime.utcfromtimestamp(posix),
        thermistors_readings=readings,
        ir_target_temp=ir_target,
        ir_sensor_temp=ir_sensor,
        ir_target_temp_range=ir_range,
    )


def _decode_generic_thermistors_message(bin_msg, kind, packet_len, fixed_len, nbr_sensors,
                                        packet_decoder):
    assert _message_kind(bin_msg) == kind
    assert _byte_to_char(bin_msg[-1]) == 'E'
    n = _one_byte_to_int(bin_msg[1:2])
    metadata = Thermistors_Metadata(nbr_thermistors_measurements=n)
    start = 2
    packets = []
    while True:
        assert _byte_to_char(bin_msg[start]) == 'P'
        pkt = packet_decoder(bin_msg[start: start + packet_len], nbr_sensors)
        packets.append(pkt)
        trailing = _byte_to_char(bin_msg[start + packet_len])
        if trailing == 'E':
            break
        start += packet_len
    return metadata, packets


# ---------------------------------------------------------------------------
# public API


def decode_message(hex_string_message, print_decoded=False, print_debug_information=False):
    """
    Decode a hex-encoded RockBLOCK payload.

    Returns
    -------
    (kind, metadata, list_of_packets)
        kind      : str  — 'G' GNSS | 'Y' waves | 'T'/'U'/'V'/'W' thermistors
        metadata  : dataclass
        packets   : list of dataclass instances
    """
    bin_msg = binascii.unhexlify(hex_string_message)
    kind = _message_kind(bin_msg)

    if kind == 'G':
        metadata, packets = _decode_gnss_message(bin_msg)
    elif kind == 'Y':
        metadata, packets = _decode_ywave_message(bin_msg)
    elif kind == 'T':
        metadata, packets = _decode_generic_thermistors_message(
            bin_msg, 'T', _BD_THERM_PACKET_LENGTH, _BD_THERM_MSG_FIXED_LENGTH,
            _BD_THERM_MSG_NBR_THERMISTORS,
            lambda b, n: _decode_thermistors_packet(b, n),
        )
    elif kind == 'U':
        metadata, packets = _decode_generic_thermistors_message(
            bin_msg, 'U', _BD_THERMMLX_PACKET_LENGTH, _BD_THERMMLX_MSG_FIXED_LENGTH,
            _BD_THERMMLX_MSG_NBR_THERMISTORS,
            lambda b, n: _decode_thermistorsmlx_packet(b, n),
        )
    elif kind == 'V':
        metadata, packets = _decode_generic_thermistors_message(
            bin_msg, 'V', _BD_THERM16_PACKET_LENGTH, _BD_THERM16_MSG_FIXED_LENGTH,
            _BD_THERM16_MSG_NBR_THERMISTORS,
            lambda b, n: _decode_thermistors_packet(b, n),
        )
    elif kind == 'W':
        metadata, packets = _decode_generic_thermistors_message(
            bin_msg, 'W', _BD_27THERM1MLX_PACKET_LENGTH, _BD_27THERM1MLX_MSG_FIXED_LENGTH,
            _BD_27THERM1MLX_MSG_NBR_THERMISTORS,
            lambda b, n: _decode_thermistorsmlx_packet(b, n),
        )
    else:
        raise RuntimeError("Unknown message kind: {}".format(kind))

    return kind, metadata, packets
