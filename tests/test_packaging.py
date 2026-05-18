from __future__ import annotations

from importlib import resources


def test_textual_stylesheet_is_packaged_with_module_resources():
    assert resources.files("sonos_now").joinpath("sonos_now.tcss").is_file()
