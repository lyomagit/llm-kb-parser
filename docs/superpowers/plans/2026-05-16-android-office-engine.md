# Android Office Engine Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the Android app ready to use a real Collabora/LibreOffice-based companion engine for DOC, DOCX, PDF, and legacy Office conversion without bundling Collabora inside the main kbparser APK.

**Architecture:** Keep `com.lyomagit.kbparser` as the user-facing Chaquopy app and call a separate signed companion app through an explicit Android intent contract. The companion is expected to be built from a fork of `CollaboraOnline/online` and expose a narrow conversion API around LibreOfficeKit `saveAs`.

**Tech Stack:** Kotlin/Compose, Android Storage Access Framework, Chaquopy Python 3.13, JSON DTOs, Activity Result API, future Collabora/LibreOfficeKit companion package.

---

### File Structure

- Modify: `android/app/src/main/java/com/lyomagit/kbparser/PythonBridge.kt`
  - Keep the Python JSON bridge as the only Python entrypoint from Kotlin.
- Modify: `android/app/src/main/java/com/lyomagit/kbparser/MainActivity.kt`
  - Add office-engine status, all-document picker, and a conversion-first path for unsupported desktop formats.
- Create: `android/app/src/main/java/com/lyomagit/kbparser/OfficeEngineContract.kt`
  - Define package name, action names, extras, MIME policy, and helper methods for the companion engine.
- Modify: `android/app/src/main/AndroidManifest.xml`
  - Add `<queries>` so Android 11+ package visibility can detect the companion package/action.
- Modify: `src/kbparser/mobile/facade.py`
  - Advertise the external office-engine pathway and allow parsed converted files to keep their original source metadata.
- Modify: `tests/test_android_scaffold.py`
  - Assert the Kotlin contract, manifest package visibility, and no hard dependency on Collabora in the main APK.
- Modify: `tests/test_mobile_facade.py`
  - Assert capabilities now mark DOC/DOCX/PDF as companion-convertible instead of permanently disabled.

### Task 1: Companion Contract

**Files:**
- Create: `android/app/src/main/java/com/lyomagit/kbparser/OfficeEngineContract.kt`
- Modify: `android/app/src/main/AndroidManifest.xml`
- Test: `tests/test_android_scaffold.py`

- [ ] **Step 1: Write failing scaffold tests**

```python
def test_android_declares_office_engine_companion_contract():
    contract = ROOT / "android" / "app" / "src" / "main" / "java" / "com" / "lyomagit" / "kbparser" / "OfficeEngineContract.kt"
    text = contract.read_text(encoding="utf-8")

    assert 'COMPANION_PACKAGE = "com.lyomagit.kbparser.officeengine"' in text
    assert 'ACTION_CONVERT = "com.lyomagit.kbparser.officeengine.CONVERT"' in text
    assert 'EXTRA_SOURCE_URI = "source_uri"' in text
    assert 'EXTRA_TARGET_FORMAT = "target_format"' in text
    assert 'EXTRA_RESULT_JSON = "result_json"' in text
    assert "supportedInputMimeTypes" in text
```

- [ ] **Step 2: Verify RED**

Run: `/tmp/kbparser-build-311/bin/python -m pytest tests/test_android_scaffold.py::test_android_declares_office_engine_companion_contract -q`

Expected: FAIL because `OfficeEngineContract.kt` does not exist.

- [ ] **Step 3: Add minimal contract**

```kotlin
package com.lyomagit.kbparser

import android.content.Context
import android.content.Intent
import android.net.Uri

object OfficeEngineContract {
    const val COMPANION_PACKAGE = "com.lyomagit.kbparser.officeengine"
    const val ACTION_CONVERT = "com.lyomagit.kbparser.officeengine.CONVERT"
    const val EXTRA_SOURCE_URI = "source_uri"
    const val EXTRA_SOURCE_NAME = "source_name"
    const val EXTRA_TARGET_FORMAT = "target_format"
    const val EXTRA_RESULT_JSON = "result_json"

    val supportedInputMimeTypes = arrayOf(
        "application/msword",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/pdf",
        "application/rtf",
        "text/rtf",
    )

    fun buildConvertIntent(sourceUri: Uri, sourceName: String, targetFormat: String): Intent =
        Intent(ACTION_CONVERT).apply {
            setPackage(COMPANION_PACKAGE)
            data = sourceUri
            putExtra(EXTRA_SOURCE_URI, sourceUri.toString())
            putExtra(EXTRA_SOURCE_NAME, sourceName)
            putExtra(EXTRA_TARGET_FORMAT, targetFormat)
            addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
        }

    fun isAvailable(context: Context): Boolean =
        buildConvertIntent(Uri.EMPTY, "", "docx")
            .resolveActivity(context.packageManager) != null
}
```

- [ ] **Step 4: Add package visibility**

```xml
<queries>
    <package android:name="com.lyomagit.kbparser.officeengine" />
    <intent>
        <action android:name="com.lyomagit.kbparser.officeengine.CONVERT" />
    </intent>
</queries>
```

- [ ] **Step 5: Verify GREEN**

Run: `/tmp/kbparser-build-311/bin/python -m pytest tests/test_android_scaffold.py -q`

Expected: PASS.

### Task 2: Python Capability Contract

**Files:**
- Modify: `src/kbparser/mobile/facade.py`
- Test: `tests/test_mobile_facade.py`

- [ ] **Step 1: Write failing capability test**

```python
def test_android_capabilities_advertise_external_office_engine():
    payload = json.loads(android_capabilities_json())

    assert payload["external_engines"]["office"]["package"] == "com.lyomagit.kbparser.officeengine"
    assert payload["external_engines"]["office"]["source"] == "CollaboraOnline/online fork"
    assert payload["disabled_formats"]["doc"]["replacement"] == "Android office companion conversion"
    assert payload["disabled_formats"]["docx"]["replacement"] == "Android office companion conversion"
    assert payload["disabled_formats"]["pdf"]["replacement"] == "Android office companion conversion"
```

- [ ] **Step 2: Verify RED**

Run: `/tmp/kbparser-build-311/bin/python -m pytest tests/test_mobile_facade.py::test_android_capabilities_advertise_external_office_engine -q`

Expected: FAIL because `external_engines` is missing.

- [ ] **Step 3: Update capability JSON**

Add `external_engines.office` and update DOC/DOCX/PDF replacement text to `Android office companion conversion`.

- [ ] **Step 4: Verify GREEN**

Run: `/tmp/kbparser-build-311/bin/python -m pytest tests/test_mobile_facade.py -q`

Expected: PASS.

### Task 3: Android UI Integration

**Files:**
- Modify: `android/app/src/main/java/com/lyomagit/kbparser/MainActivity.kt`
- Modify: `android/app/src/main/java/com/lyomagit/kbparser/PythonBridge.kt`
- Test: `tests/test_android_scaffold.py`

- [ ] **Step 1: Write failing UI tests**

Assert that `MainActivity.kt` uses `OfficeEngineContract`, launches all supported office MIME types, and shows companion status without requiring Collabora classes in the app module.

- [ ] **Step 2: Verify RED**

Run: `/tmp/kbparser-build-311/bin/python -m pytest tests/test_android_scaffold.py -q`

Expected: FAIL until UI references the contract.

- [ ] **Step 3: Add companion-aware UI**

Keep XLS/XLSX direct Python parsing. For DOC/DOCX/PDF/RTF, launch the companion convert intent if available; otherwise show a JSON error explaining that the companion is missing.

- [ ] **Step 4: Verify GREEN**

Run: `/tmp/kbparser-build-311/bin/python -m pytest tests/test_android_scaffold.py -q`

Expected: PASS.

### Task 4: Build Verification

**Files:**
- Android Gradle project
- Python source and tests

- [ ] **Step 1: Run Python tests**

Run: `/tmp/kbparser-build-311/bin/python -m pytest tests/test_android_scaffold.py tests/test_mobile_facade.py`

Expected: PASS.

- [ ] **Step 2: Compile Python files**

Run: `/tmp/kbparser-build-311/bin/python -m compileall -q src tests scripts packaging`

Expected: exit 0.

- [ ] **Step 3: Build Android debug APK**

Run: `cd android && ./gradlew :app:assembleDebug`

Expected: exit 0 and APK under `android/app/build/outputs/apk/debug/`.

- [ ] **Step 4: Check whitespace**

Run: `git diff --check`

Expected: exit 0.

### Task 5: Collabora Fork Follow-Up

**Files:**
- Create later in the Collabora fork, not in this repo: `android/app/src/main/java/com/lyomagit/kbparser/officeengine/ConvertActivity.kt`

- [ ] **Step 1: Fork target**

Use `CollaboraOnline/online` branch `main` as source; mobile release branches are downstream release lines.

- [ ] **Step 2: Add companion package**

Set package/applicationId to `com.lyomagit.kbparser.officeengine`.

- [ ] **Step 3: Implement convert API**

Receive `ACTION_CONVERT`, copy input URI to cache, load through existing LibreOfficeKit flow, call native `saveAs(fileUri, format, options)`, return `EXTRA_RESULT_JSON`.

- [ ] **Step 4: Verify with real DOC**

Install companion APK next to kbparser, choose a `.doc`, verify kbparser receives converted output and parses it.
