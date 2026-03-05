import pytest
from commuter.pathmap import translate, encode_project_path


MAPS = [
    ("/home/ljubomir/projects", "/Users/ljubomir/projects"),
    ("/home/ljubomir/Dropbox", "/Users/ljubomir/Dropbox"),
]


def test_translate_forward():
    result = translate("/home/ljubomir/projects/myapp", MAPS)
    assert result == "/Users/ljubomir/projects/myapp"


def test_translate_reverse():
    result = translate("/Users/ljubomir/projects/myapp", MAPS)
    assert result == "/home/ljubomir/projects/myapp"


def test_translate_exact_match():
    result = translate("/home/ljubomir/projects", MAPS)
    assert result == "/Users/ljubomir/projects"


def test_translate_no_match():
    result = translate("/tmp/something", MAPS)
    assert result == "/tmp/something"


def test_translate_longer_prefix_wins():
    maps = [
        ("/home/ljubomir", "/Users/ljubomir"),
        ("/home/ljubomir/projects", "/Users/ljubomir/work"),
    ]
    result = translate("/home/ljubomir/projects/myapp", maps)
    assert result == "/Users/ljubomir/work/myapp"


def test_translate_dropbox():
    result = translate("/home/ljubomir/Dropbox/file.json", MAPS)
    assert result == "/Users/ljubomir/Dropbox/file.json"


def test_translate_empty_maps():
    result = translate("/home/ljubomir/projects/foo", [])
    assert result == "/home/ljubomir/projects/foo"


def test_encode_project_path():
    assert encode_project_path("/home/ljubomir/github/commuter") == "-home-ljubomir-github-commuter"


def test_encode_project_path_trailing_slash():
    # resolve() strips trailing slash
    import os
    p = encode_project_path("/home/ljubomir/projects/foo")
    assert p == "-home-ljubomir-projects-foo"
