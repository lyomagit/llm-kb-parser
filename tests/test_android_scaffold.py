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


def test_android_declares_office_engine_companion_contract():
    contract = ROOT / "android" / "app" / "src" / "main" / "java" / "com" / "lyomagit" / "kbparser" / "OfficeEngineContract.kt"
    text = contract.read_text(encoding="utf-8")

    assert 'COMPANION_PACKAGE = "com.lyomagit.kbparser.officeengine"' in text
    assert 'ACTION_CONVERT = "com.lyomagit.kbparser.officeengine.CONVERT"' in text
    assert 'EXTRA_SOURCE_URI = "source_uri"' in text
    assert 'EXTRA_SOURCE_NAME = "source_name"' in text
    assert 'EXTRA_TARGET_FORMAT = "target_format"' in text
    assert 'EXTRA_RESULT_JSON = "result_json"' in text
    assert "supportedInputMimeTypes" in text
    assert "buildConvertIntent" in text
    assert "isAvailable" in text


def test_android_manifest_can_discover_office_engine_without_bundling_it():
    manifest = (ROOT / "android" / "app" / "src" / "main" / "AndroidManifest.xml").read_text(encoding="utf-8")
    build_file = (ROOT / "android" / "app" / "build.gradle.kts").read_text(encoding="utf-8")

    assert '<package android:name="com.lyomagit.kbparser.officeengine" />' in manifest
    assert '<action android:name="com.lyomagit.kbparser.officeengine.CONVERT" />' in manifest
    assert "com.collabora.libreoffice" not in manifest
    assert "CollaboraOnline" not in build_file


def test_android_ui_routes_desktop_formats_through_companion_engine():
    activity = (ROOT / "android" / "app" / "src" / "main" / "java" / "com" / "lyomagit" / "kbparser" / "MainActivity.kt").read_text(encoding="utf-8")

    assert "OfficeEngineContract.supportedInputMimeTypes" in activity
    assert "OfficeEngineContract.isAvailable" in activity
    assert "officeEngineLauncher" in activity
    assert "launchOfficeConversion" in activity
    assert "kbparser.officeengine" in activity


def test_android_direct_python_path_uses_markdown_output():
    bridge = (ROOT / "android" / "app" / "src" / "main" / "java" / "com" / "lyomagit" / "kbparser" / "PythonBridge.kt").read_text(encoding="utf-8")
    activity = (ROOT / "android" / "app" / "src" / "main" / "java" / "com" / "lyomagit" / "kbparser" / "MainActivity.kt").read_text(encoding="utf-8")

    assert "parse_path_markdown" in bridge
    assert "parseFileMarkdown" in bridge
    assert "PythonBridge.parseFileMarkdown" in activity


def test_android_bridge_can_parse_converted_file_with_original_metadata():
    bridge = (ROOT / "android" / "app" / "src" / "main" / "java" / "com" / "lyomagit" / "kbparser" / "PythonBridge.kt").read_text(encoding="utf-8")

    assert "parseConvertedFileMarkdown" in bridge
    assert "sourceName: String" in bridge
    assert "sourceFormat: String" in bridge
    assert "original_source_name" in bridge
    assert "original_source_format" in bridge


def test_android_office_engine_result_uri_is_parsed_after_conversion():
    contract = (ROOT / "android" / "app" / "src" / "main" / "java" / "com" / "lyomagit" / "kbparser" / "OfficeEngineContract.kt").read_text(encoding="utf-8")
    activity = (ROOT / "android" / "app" / "src" / "main" / "java" / "com" / "lyomagit" / "kbparser" / "MainActivity.kt").read_text(encoding="utf-8")

    assert 'EXTRA_RESULT_URI = "result_uri"' in contract
    assert 'EXTRA_RESULT_FORMAT = "result_format"' in contract
    assert "sourceFormatFor" in contract
    assert "handleOfficeEngineResult" in activity
    assert "EXTRA_RESULT_URI" in activity
    assert "pendingOfficeSourceName" in activity
    assert "PythonBridge.parseConvertedFileMarkdown" in activity
