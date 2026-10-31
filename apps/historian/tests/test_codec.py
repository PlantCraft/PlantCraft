import numpy as np
import pytest

from histcraft.archive import codec


def test_numbers_round_trip_with_gaps():
    times = np.array([0, 1000, 2500, 10_000], dtype=np.int64)
    values = np.array([1.5, np.nan, -3.25, 1e300])
    got_times, got_values = codec.decode(codec.encode(times, values, "number"))
    assert got_times.tolist() == times.tolist()
    np.testing.assert_array_equal(got_values, values)


def test_text_round_trip_with_gaps_and_unicode():
    times = np.array([5, 6, 7], dtype=np.int64)
    labels = ["AUTO", None, "MAN ção"]
    assert codec.decode(codec.encode(times, labels, "text"))[1] == labels


def test_a_flat_hour_at_one_second_is_small():
    times = np.arange(0, 3_600_000, 1000, dtype=np.int64)
    blob = codec.encode(times, np.full(len(times), 42.0), "number")
    assert len(blob) < 200


@pytest.mark.parametrize("blob", [b"", b"\x00abc", b"\x10notzlib", bytes([0x11]) + b"x" * 10])
def test_damaged_chunks_raise_codec_error(blob):
    with pytest.raises(codec.CodecError):
        codec.decode(blob)


def test_empty_chunks_are_refused():
    with pytest.raises(codec.CodecError):
        codec.encode(np.array([], dtype=np.int64), np.array([]), "number")


def _zlib_numbers(times, values) -> bytes:
    """A chunk as Historian 0.4 and earlier wrote it (``0x10``, zlib)."""

    import struct
    import zlib

    times = np.asarray(times, dtype="<i8")
    body = struct.pack("<Iq", len(times), int(times[0])) + np.diff(times).tobytes()
    return bytes([0x10]) + zlib.compress(body + np.asarray(values, dtype="<f8").tobytes(), 6)


def test_chunks_written_before_still_read():
    times = np.array([0, 1000, 5000], dtype=np.int64)
    values = np.array([1.0, np.nan, 2.5])
    got_times, got_values = codec.decode(_zlib_numbers(times, values))
    assert got_times.tolist() == times.tolist()
    np.testing.assert_array_equal(got_values, values)


def test_float32_values_are_kept_in_four_bytes_and_others_exactly():
    times = np.arange(0, 600_000, 1000, dtype=np.int64)
    plc = np.float32(np.linspace(10, 90, len(times))).astype(np.float64)  # a PLC's REAL
    exact = np.linspace(10, 90, len(times)) + 1e-9  # not a float32: stays float64
    for values in (plc, exact):
        _, got = codec.decode(codec.encode(times, values, "number"))
        assert got.tolist() == values.tolist()
    assert len(codec.encode(times, plc, "number")) < len(codec.encode(times, exact, "number"))


def test_times_far_apart_and_negative_round_trip():
    times = np.array([-(10**12), 0, 3 * 10**12], dtype=np.int64)  # differences past int32
    got_times, _ = codec.decode(codec.encode(times, np.array([1.0, 2.0, 3.0]), "number"))
    assert got_times.tolist() == times.tolist()


def test_noisy_signals_take_less_than_the_zlib_layout():
    rng = np.random.default_rng(1)
    times = np.cumsum(rng.integers(1000, 9000, 10_000)).astype(np.int64)
    values = np.float32(50 + np.cumsum(rng.normal(0, 0.05, 10_000))).astype(np.float64)
    assert len(codec.encode(times, values, "number")) < 0.9 * len(_zlib_numbers(times, values))


def test_a_batch_of_many_points_round_trips():
    batch = {
        3: ("number", [(1000, 1.5), (2000, float("nan")), (3000, None)]),
        1: ("integer", [(500, 7.0)]),
        9: ("text", [(1000, "AUTO"), (2000, None)]),
        4: ("number", []),
    }
    got = codec.decode_batch(codec.encode_batch(batch))
    assert set(got) == {1, 3, 9}
    assert got[3][1].tolist() == [1000, 2000, 3000]
    assert got[3][2][0] == 1.5 and np.isnan(got[3][2][1:]).all()
    assert got[1][2].tolist() == [7.0]
    assert got[9][0] == "text" and got[9][2] == ["AUTO", None]


@pytest.mark.parametrize("blob", [b"", b"\x30garbage", bytes([0x20]) + b"x" * 10])
def test_damaged_batches_raise_codec_error(blob):
    with pytest.raises(codec.CodecError):
        codec.decode_batch(blob)


def test_decoded_chunks_decode_once_and_follow_a_rewritten_chunk():
    cache = codec.DecodedChunks(budget=1 << 20)
    times = np.array([1000, 2000, 3000], dtype=np.int64)
    blob = codec.encode_numbers(times, np.array([1.0, 2.0, 3.0]))
    first = cache.decode(blob)
    again = cache.decode(bytes(blob))
    assert cache.misses == 1 and cache.hits == 1
    assert again[0] is first[0]
    assert not again[0].flags.writeable and not again[1].flags.writeable
    rewritten = codec.encode_numbers(times, np.array([1.0, 2.0, 4.0]))
    assert cache.decode(rewritten)[1].tolist() == [1.0, 2.0, 4.0]


def test_decoded_chunks_stay_within_their_budget():
    blobs = [
        codec.encode_numbers(np.arange(100, dtype=np.int64) * 1000, np.full(100, float(i)))
        for i in range(20)
    ]
    cache = codec.DecodedChunks(budget=5_000)
    for blob in blobs:
        cache.decode(blob)
    assert 0 < cache.size <= 5_000
    assert cache.decode(blobs[0])[1][0] == 0.0  # evicted, decoded again
    off = codec.DecodedChunks(budget=0)
    off.decode(blobs[0])
    assert off.size == 0 and not off._items
