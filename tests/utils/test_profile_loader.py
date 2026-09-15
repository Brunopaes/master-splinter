"""Tests for reading dive profiles out of dive computer exports."""

import json

import pytest

from master_splinter.utils.profile_loader import (
    ProfileFormatError,
    load_profile,
)

CSV = "time,depth\n0,0\n1,20\n2,30\n20,30\n22,0\n"
SAMPLES = [
    {"time": 0, "depth": 0},
    {"time": 1, "depth": 20},
    {"time": 2, "depth": 30},
]


def write(tmp_path, name, content):
    path = tmp_path / name
    path.write_text(content)
    return path


def test_csv_becomes_depth_duration_elapsed(tmp_path):
    profile = load_profile(write(tmp_path, "dive.csv", CSV))

    assert [depth for depth, _, _ in profile] == [0, 20, 30, 30, 0]
    assert [elapsed for _, _, elapsed in profile] == [0, 1, 2, 20, 22]
    # Durations are the gap to the next sample.
    assert [duration for _, duration, _ in profile] == [1, 1, 18, 2, 2]


def test_last_sample_inherits_the_previous_duration(tmp_path):
    """The final sample has no successor to measure against."""
    profile = load_profile(write(tmp_path, "dive.csv", CSV))
    assert profile[-1][1] == profile[-2][1]


def test_csv_columns_are_case_and_space_insensitive(tmp_path):
    content = " Time , Depth \n0,0\n1,10\n"
    profile = load_profile(write(tmp_path, "dive.csv", content))
    assert len(profile) == 2


def test_samples_are_sorted_by_time(tmp_path):
    content = "time,depth\n2,30\n0,0\n1,20\n"
    profile = load_profile(write(tmp_path, "dive.csv", content))
    assert [elapsed for _, _, elapsed in profile] == [0, 1, 2]


def test_json_list_of_samples(tmp_path):
    path = write(tmp_path, "dive.json", json.dumps(SAMPLES))
    assert len(load_profile(path)) == 3


def test_json_samples_wrapper(tmp_path):
    path = write(tmp_path, "dive.json", json.dumps({"samples": SAMPLES}))
    assert len(load_profile(path)) == 3


def test_loaded_profile_is_analysable(tmp_path):
    """The loader's output must be interchangeable with the generator's."""
    from master_splinter.processors.dive_analysis import analyse_profile

    profile = load_profile(write(tmp_path, "dive.csv", CSV))
    report = analyse_profile(profile)
    assert report.samples
    assert report.max_depth == 30


def test_missing_file_raises(tmp_path):
    with pytest.raises(OSError):
        load_profile(tmp_path / "absent.csv")


@pytest.mark.parametrize(
    "content,message",
    [
        ("time,depth\n0,0\n", "at least 2 samples"),
        ("", "empty CSV"),
        ("foo,bar\n1,2\n3,4\n", "'time' and 'depth' columns"),
        ("time,depth\n0,0\nx,10\n", "non-numeric"),
        ("time,depth\n0,0\n0,10\n", "non-increasing"),
    ],
)
def test_bad_csv_is_rejected_with_a_useful_message(tmp_path, content, message):
    with pytest.raises(ProfileFormatError, match=message):
        load_profile(write(tmp_path, "dive.csv", content))


@pytest.mark.parametrize(
    "content,message",
    [
        ("{not json", "invalid JSON"),
        (json.dumps({"nope": []}), "at least 2 samples"),
        (json.dumps("a string"), "expected a list"),
        (json.dumps([{"time": 0}, {"time": 1}]), "numeric"),
    ],
)
def test_bad_json_is_rejected_with_a_useful_message(
    tmp_path, content, message
):
    with pytest.raises(ProfileFormatError, match=message):
        load_profile(write(tmp_path, "dive.json", content))


@pytest.mark.parametrize(
    "depth,reason",
    [
        (200, "a feet-for-meters mix-up, or a sensor spike"),
        (-30, "a depth above the surface"),
    ],
)
def test_implausible_depths_are_refused(tmp_path, depth, reason):
    """The loader is the trust boundary; past it a depth is believed.

    Without this the value reaches the model, loads the tissues past anything
    the stop grid covers, and surfaces as a RuntimeError from inside the
    ascent walk rather than as a complaint about the file.
    """
    path = tmp_path / "bad.csv"
    path.write_text(f"time,depth\n0,0\n5,{depth}\n20,{depth}\n25,0\n")

    with pytest.raises(ProfileFormatError, match="check the units"):
        load_profile(path)


def test_the_deepest_allowed_depth_is_accepted(tmp_path):
    """The bound is inclusive; 120 m is a real if unusual dive."""
    path = tmp_path / "deep.csv"
    path.write_text("time,depth\n0,0\n5,120\n20,120\n25,0\n")

    profile = load_profile(path)
    assert max(depth for depth, _, _ in profile) == 120.0
