from pathlib import Path
import ast
import re


BUILD_SCRIPT = Path(__file__).resolve().parents[1] / "build_paddleocr_pdf_to_md_EXE.bat"


def test_windows_version_metadata_has_no_leading_zero_components():
    """Nuitka/Windows version metadata must contain four plain integers."""
    script = BUILD_SCRIPT.read_text(encoding="utf-8")
    versions = re.findall(r"--(?:file|product)-version=([^\s^]+)", script)

    assert versions == ["26.10.19.2", "26.10.19.2"]
    for version in versions:
        components = version.split(".")
        assert len(components) == 4
        assert all(component.isdecimal() for component in components)
        assert all(component == "0" or not component.startswith("0") for component in components)


def test_release_filename_keeps_display_version():
    """The public filename must identify the current release."""
    script = BUILD_SCRIPT.read_text(encoding="utf-8")
    assert 'set "EXE_NAME=PaddleOCR_PDF_to_MD_26.10.19.02.exe"' in script


def test_application_and_build_versions_match():
    """Prevent the GUI title and Windows product metadata from diverging."""
    import paddleocr_pdf_to_md_gui as application

    script = BUILD_SCRIPT.read_text(encoding="utf-8")
    assert application.APP_VERSION == "26.10.19.02"
    metadata_version = ".".join(str(int(part)) for part in application.APP_VERSION.split("."))
    assert f"--file-version={metadata_version}" in script
    assert f"--product-version={metadata_version}" in script
    assert f"PDFToMarkdown/{application.APP_VERSION}" in script
    launcher = BUILD_SCRIPT.with_name("start_paddleocr_pdf_to_md_SAFE.bat").read_text(encoding="utf-8")
    assert f"启动器 {application.APP_VERSION}" in launcher


def test_windows_version_reference_has_matching_fixed_and_display_versions():
    """The reference resource used to retain an outdated fixed version tuple."""
    resource = BUILD_SCRIPT.with_name("version_info_26.10.19.02.txt")
    tree = ast.parse(resource.read_text(encoding="utf-8"))
    fixed_versions = {}
    display_versions = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.keyword) and node.arg in {"filevers", "prodvers"}:
            fixed_versions[node.arg] = ast.literal_eval(node.value)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "StringStruct":
            name, value = (ast.literal_eval(arg) for arg in node.args)
            display_versions[name] = value
    assert fixed_versions == {"filevers": (26, 10, 19, 2), "prodvers": (26, 10, 19, 2)}
    assert display_versions["FileVersion"] == display_versions["ProductVersion"] == "26.10.19.02"
    assert display_versions["OriginalFilename"] == "PaddleOCR_PDF_to_MD_26.10.19.02.exe"


def test_source_launchers_check_all_required_workspace_modules():
    """A partial source download should fail clearly before opening the application."""
    for name in ("start_paddleocr_pdf_to_md_SAFE.bat", "build_paddleocr_pdf_to_md_EXE.bat"):
        script = BUILD_SCRIPT.with_name(name).read_text(encoding="utf-8")
        assert "(paddleocr_pdf_to_md_gui.py literature_processing.py literature_ui.py workspace_ui.py ui_i18n.py ui_translations.py responsive_ui.py github_ui.py model_budget.py app_launcher.py app_updater.py source_bootstrap.py update_ui.py make_update_package.py update_helper.ps1)" in script


def test_frozen_launcher_and_update_resources_are_bundled():
    import app_launcher
    import paddleocr_pdf_to_md_gui as application
    script = BUILD_SCRIPT.read_text(encoding="utf-8")
    assert app_launcher.APP_VERSION == application.APP_VERSION
    assert 'SCRIPT=%ROOT%app_launcher.py' in script
    assert '--include-data-files="%ROOT%requirements.txt=requirements.txt"' in script
    assert '--include-data-files="%ROOT%update_helper.ps1=update_helper.ps1"' in script
    assert '"%ROOT%make_update_package.py" "%EXE_PATH%"' in script
