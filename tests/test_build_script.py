from pathlib import Path
import re


BUILD_SCRIPT = Path(__file__).resolve().parents[1] / "build_paddleocr_pdf_to_md_EXE.bat"


def test_windows_version_metadata_has_no_leading_zero_components():
    """Nuitka/Windows version metadata must contain four plain integers."""
    script = BUILD_SCRIPT.read_text(encoding="utf-8")
    versions = re.findall(r"--(?:file|product)-version=([^\s^]+)", script)

    assert versions == ["26.8.13.3", "26.8.13.3"]
    for version in versions:
        components = version.split(".")
        assert len(components) == 4
        assert all(component.isdecimal() for component in components)
        assert all(component == "0" or not component.startswith("0") for component in components)


def test_release_filename_keeps_display_version():
    """The public filename may retain the zero-padded release label."""
    script = BUILD_SCRIPT.read_text(encoding="utf-8")
    assert 'set "EXE_NAME=PaddleOCR_PDF_to_MD_26.8.13.03.exe"' in script
