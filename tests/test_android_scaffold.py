from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_android_scaffold_pins_chaquopy_phase0_contract():
    build_file = ROOT / "android" / "app" / "build.gradle.kts"
    text = build_file.read_text(encoding="utf-8")

    assert 'id("com.chaquo.python")' in text
    assert 'version = "3.13"' in text
    assert '"arm64-v8a"' in text
    assert '"x86_64"' in text
    assert "requirements-android.txt" in text


def test_android_workflow_builds_debug_apk_only_for_spike():
    workflow = ROOT / ".github" / "workflows" / "android.yml"
    text = workflow.read_text(encoding="utf-8")

    assert ":app:assembleDebug" in text
    assert ":app:bundleRelease" not in text
    assert "python-version: '3.13'" in text
    assert "cd android" in text
    assert "./gradlew :app:assembleDebug" in text


def test_android_gradle_wrapper_is_checked_in():
    assert (ROOT / "android" / "gradlew").is_file()
    assert (ROOT / "android" / "gradlew.bat").is_file()
    assert (ROOT / "android" / "gradle" / "wrapper" / "gradle-wrapper.jar").is_file()
    properties = (ROOT / "android" / "gradle" / "wrapper" / "gradle-wrapper.properties").read_text(encoding="utf-8")
    assert "gradle-8.13-bin.zip" in properties
