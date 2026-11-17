"""The candidate seal refuses an artifact carrying an export-excluded file or a home-directory path.

The breakage it prevents: the sealed 3.0.3 candidate's gpuwm wheel carried 45
files RELEASE-EXCLUDE.txt keeps out of the public tree, 44 of them records
whose paths named the author's home directory, and the seal read only the
source tree's case-token scan, which cannot see inside a wheel.  The check
lives in the private cut tooling beside the owner-identity scan, which the
public snapshot does not carry, so a published tree skips this module.

Every path below is assembled from fragments: this file ships in the sdist,
where the packet gates read it.
"""

from __future__ import annotations

import importlib.util
import io
from pathlib import Path
import tarfile
import zipfile

import pytest

REPO = Path(__file__).resolve().parents[1]
CHECK = REPO / "tools" / "release" / "cut" / "drivers" / "seal_check.py"

pytestmark = pytest.mark.skipif(
    not (CHECK.is_file() and (REPO / "RELEASE-EXCLUDE.txt").is_file()),
    reason="the release cut tooling is not in this tree (published snapshot)")

BS = chr(92)
HOME = "/" + "ho" + "me/"
MAC = "/" + "Us" + "ers/"
WIN = "C:" + BS + "Us" + "ers" + BS


def _check():
    spec = importlib.util.spec_from_file_location("seal_check_under_test", CHECK)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _excluded_member() -> str:
    """A literal tree path RELEASE-EXCLUDE.txt drops, under the gpuwm project."""

    from tools.release_exclusions import read_exclusions

    for rule in read_exclusions(REPO):
        if rule.startswith("configs/") and not rule.endswith("/**"):
            return rule
    pytest.skip("RELEASE-EXCLUDE.txt drops no literal configs path to build a fixture from")


def _wheel(path: Path, members: dict[str, bytes]) -> Path:
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, data in members.items():
            archive.writestr(name, data)
    return path


def _sdist(path: Path, root: str, members: dict[str, bytes]) -> Path:
    with tarfile.open(path, "w:gz") as archive:
        for name, data in members.items():
            info = tarfile.TarInfo(f"{root}/{name}")
            info.size = len(data)
            archive.addfile(info, io.BytesIO(data))
    return path


CLEAN = {
    "gpuwm/__init__.py": b'"""Engine."""\n',
    "configs/demo.toml": b"[run]\nhours = 1\n",
    # Placeholders are not account names, a URL path is not a home, and the
    # macOS and Linux roots are read in their own case.
    "gpuwm/receipt.py": ("# prepared on Linux records " + HOME + "<user>/prep/case.toml\n"
                         "# or $" + "HOME, " + HOME + "$USER/x, " + WIN + "%USERNAME%" + BS + "x, "
                         + WIN + "{user}" + BS + "x\n"
                         "URL = 'https://example.invalid/wrf/users/download/'\n"
                         "NOTE = 'see /Home/endgame-tablebases'\n").encode(),
    "gpuwm-3.0.3.dist-info/METADATA": b"Name: gpuwm\n",
}


def test_a_clean_wheel_and_sdist_pass(tmp_path: Path) -> None:
    check = _check()
    wheel = _wheel(tmp_path / "gpuwm-9.9.9-py3-none-any.whl", CLEAN)
    sdist = _sdist(tmp_path / "gpuwm-9.9.9.tar.gz", "gpuwm-9.9.9", CLEAN)
    assert check.check([wheel, sdist], REPO) == []
    assert check.main(["--repo-root", str(REPO), str(wheel), str(sdist)]) == 0


@pytest.mark.parametrize("kind", ["wheel", "sdist"])
def test_an_export_excluded_file_is_refused_in_a_wheel_and_an_sdist(tmp_path: Path, kind: str) -> None:
    check = _check()
    member = _excluded_member()
    members = dict(CLEAN, **{member: b"{}\n"})
    path = (_wheel(tmp_path / "gpuwm-9.9.9-py3-none-any.whl", members) if kind == "wheel"
            else _sdist(tmp_path / "gpuwm-9.9.9.tar.gz", "gpuwm-9.9.9", members))
    rows = check.check([path], REPO)
    assert [(row["kind"], row["token"]) for row in rows] == [("a file the export drops", member)]
    assert check.main(["--repo-root", str(REPO), str(path)]) == 1


def test_a_companion_member_is_read_under_its_project_directory(tmp_path: Path) -> None:
    check = _check()
    assert check.tree_path("gpuwm_data/data/x.json", "wheel", "gpuwm_data") == "gpuwm-data/gpuwm_data/data/x.json"
    assert check.tree_path("gpuwm_data-9.9.9/gpuwm_data/x", "sdist", "gpuwm_data") == "gpuwm-data/gpuwm_data/x"
    assert check.tree_path("gpuwm_data-9.9.9.dist-info/RECORD", "wheel", "gpuwm_data") is None
    assert check.distribution(Path("gpuwm_kernels_startup-3.0.3-py3-none-any.whl")) == "gpuwm_kernels_startup"
    assert check.distribution(Path("gpuwm-data-3.0.3.tar.gz")) == "gpuwm_data"


@pytest.mark.parametrize("token", [
    HOME + "someone/scratch/plan.json",
    MAC + "someone/Library/x",
    "/mnt/c/" + "Us" + "ers/someone/x",
    WIN + "someone" + BS + "x",
    "C:" + BS * 2 + "Us" + "ers" + BS * 2 + "someone" + BS * 2 + "x",  # as JSON writes it
    "D:/" + "us" + "ers/someone/x",
])
def test_any_home_directory_path_is_refused(tmp_path: Path, token: str) -> None:
    check = _check()
    members = dict(CLEAN, **{"configs/plan.json": ('{"path": "' + token + '"}\n').encode()})
    wheel = _wheel(tmp_path / "gpuwm-9.9.9-py3-none-any.whl", members)
    rows = check.check([wheel], REPO)
    assert [(row["kind"], row["member"]) for row in rows] == [("a home-directory path", "configs/plan.json")], rows
    assert rows[0]["token"].endswith("someone")


def test_a_home_path_in_a_nested_archive_is_found_and_a_package_folder_is_not_a_home(tmp_path: Path) -> None:
    check = _check()
    inner = io.BytesIO()
    with zipfile.ZipFile(inner, "w") as archive:
        archive.writestr("notes.txt", HOME + "someone/x\n")
    members = dict(CLEAN, **{"gpuwm/data/kit.zip": inner.getvalue(),
                             "gpuwm/data/" + "ho" + "me/someone/x.txt": b"ok\n"})
    rows = check.check([_wheel(tmp_path / "gpuwm-9.9.9-py3-none-any.whl", members)], REPO)
    assert {row["member"] for row in rows if row["kind"] == "a home-directory path"} == {
        "gpuwm/data/kit.zip!notes.txt"}
    # A directory named for a home root inside the package is not a home root.
    assert all("x.txt" not in row["member"] for row in rows)


def test_the_owner_identity_markers_apply_too(tmp_path: Path) -> None:
    check = _check()
    mail = "fahrenheit" + "agi" + "@example.invalid"
    members = dict(CLEAN, **{"gpuwm/contact.txt": ("write to " + mail + "\n").encode()})
    rows = check.check([_wheel(tmp_path / "gpuwm-9.9.9-py3-none-any.whl", members)], REPO)
    assert [row["kind"] for row in rows] == ["owner's e-mail"]


def test_usage_without_an_artifact_is_exit_2() -> None:
    assert _check().main([]) == 2
