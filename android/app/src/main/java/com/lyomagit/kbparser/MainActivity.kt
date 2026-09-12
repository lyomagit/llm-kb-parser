package com.lyomagit.kbparser

import android.content.Intent
import android.net.Uri
import android.os.Bundle
import android.provider.OpenableColumns
import androidx.activity.ComponentActivity
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.compose.setContent
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import java.io.File

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContent {
            MaterialTheme {
                Surface(modifier = Modifier.fillMaxSize()) {
                    KBParserScreen(
                        copyUriToCache = ::copyUriToCache,
                        displayNameForUri = ::displayNameForUri,
                        mimeTypeForUri = { uri -> contentResolver.getType(uri) },
                        officeEngineAvailable = { OfficeEngineContract.isAvailable(this) },
                    )
                }
            }
        }
    }

    private fun copyUriToCache(uri: Uri): File {
        val name = displayNameForUri(uri)
        val safeName = name.replace(Regex("""[^\w.\- ]"""), "_")
        val out = File(cacheDir, safeName)
        contentResolver.openInputStream(uri).use { input ->
            requireNotNull(input) { "Could not open selected document" }
            out.outputStream().use { output -> input.copyTo(output) }
        }
        return out
    }

    private fun displayNameForUri(uri: Uri): String =
        contentResolver.query(uri, null, null, null, null)?.use { cursor ->
            val index = cursor.getColumnIndex(OpenableColumns.DISPLAY_NAME)
            if (index >= 0 && cursor.moveToFirst()) cursor.getString(index) else null
        } ?: "selected-document"
}

@Composable
private fun KBParserScreen(
    copyUriToCache: (Uri) -> File,
    displayNameForUri: (Uri) -> String,
    mimeTypeForUri: (Uri) -> String?,
    officeEngineAvailable: () -> Boolean,
) {
    var output by remember {
        mutableStateOf(
            "Ready. XLS/XLSX become Markdown locally; DOC, DOCX, PDF, and RTF use com.lyomagit.kbparser.officeengine when installed."
        )
    }
    var busy by remember { mutableStateOf(false) }
    var pendingOfficeSourceName by remember { mutableStateOf<String?>(null) }
    var pendingOfficeSourceFormat by remember { mutableStateOf<String?>(null) }
    val scope = rememberCoroutineScope()
    val officeEngineLauncher = rememberLauncherForActivityResult(ActivityResultContracts.StartActivityForResult()) { result ->
        handleOfficeEngineResult(
            resultData = result.data,
            sourceName = pendingOfficeSourceName ?: "selected-document",
            sourceFormat = pendingOfficeSourceFormat ?: "",
            copyUriToCache = copyUriToCache,
            scope = scope,
            onOutput = { output = it },
            onBusy = { busy = it },
        )
    }
    val launcher = rememberLauncherForActivityResult(ActivityResultContracts.OpenDocument()) { uri ->
        if (uri == null) return@rememberLauncherForActivityResult
        val displayName = displayNameForUri(uri)
        val mimeType = mimeTypeForUri(uri)
        busy = true
        output = "Processing selected file..."
        if (OfficeEngineContract.isCompanionFormat(mimeType, displayName)) {
            pendingOfficeSourceName = displayName
            pendingOfficeSourceFormat = OfficeEngineContract.sourceFormatFor(displayName, mimeType)
            launchOfficeConversion(
                uri = uri,
                displayName = displayName,
                officeEngineAvailable = officeEngineAvailable,
                launch = { officeEngineLauncher.launch(it) },
                onOutput = { output = it },
                onBusy = { busy = it },
            )
        } else {
            scope.launch {
                output = withContext(Dispatchers.IO) {
                    runCatching {
                        val file = copyUriToCache(uri)
                        PythonBridge.parseFileMarkdown(file)
                    }.getOrElse { error ->
                        officeEngineFailureJson(error.message ?: error::class.java.simpleName)
                    }
                }
                busy = false
            }
        }
    }

    Column(
        modifier = Modifier
            .fillMaxSize()
            .padding(20.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        Text("KBParser Android", style = MaterialTheme.typography.headlineSmall)
        Text("Local Python turns spreadsheets into Markdown. A Collabora-based companion engine handles legacy Office and PDF conversion when installed.")
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            Button(
                enabled = !busy,
                onClick = {
                    launcher.launch(ALL_INPUT_MIME_TYPES)
                },
            ) {
                Text(if (busy) "Working" else "Choose document")
            }
            OutlinedButton(
                enabled = !busy,
                onClick = {
                    output = runCatching { PythonBridge.capabilitiesJson() }
                        .getOrElse { """{"status":"failed","message":"${it.message}"}""" }
                },
            ) {
                Text("Capabilities")
            }
        }
        Spacer(modifier = Modifier.height(8.dp))
        Text(
            output,
            modifier = Modifier
                .fillMaxWidth()
                .weight(1f)
                .verticalScroll(rememberScrollState()),
            style = MaterialTheme.typography.bodySmall,
        )
    }
}

private val DIRECT_PYTHON_MIME_TYPES = arrayOf(
    "application/vnd.ms-excel",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
)

private val ALL_INPUT_MIME_TYPES = DIRECT_PYTHON_MIME_TYPES + OfficeEngineContract.supportedInputMimeTypes

private fun launchOfficeConversion(
    uri: Uri,
    displayName: String,
    officeEngineAvailable: () -> Boolean,
    launch: (android.content.Intent) -> Unit,
    onOutput: (String) -> Unit,
    onBusy: (Boolean) -> Unit,
) {
    if (!officeEngineAvailable()) {
        onOutput(
            """{"status":"needs_office_engine","engine":"${OfficeEngineContract.COMPANION_PACKAGE}","message":"Install kbparser office engine to convert ${jsonEscape(displayName)}"}"""
        )
        onBusy(false)
        return
    }

    val targetFormat = OfficeEngineContract.targetFormatFor(displayName)
    val intent = OfficeEngineContract.buildConvertIntent(uri, displayName, targetFormat)
    runCatching {
        launch(intent)
        onOutput("""{"status":"converting","engine":"${OfficeEngineContract.COMPANION_PACKAGE}","target_format":"$targetFormat"}""")
    }.getOrElse { error ->
        onOutput(officeEngineFailureJson(error.message ?: error::class.java.simpleName))
        onBusy(false)
    }
}

private fun handleOfficeEngineResult(
    resultData: Intent?,
    sourceName: String,
    sourceFormat: String,
    copyUriToCache: (Uri) -> File,
    scope: CoroutineScope,
    onOutput: (String) -> Unit,
    onBusy: (Boolean) -> Unit,
) {
    val resultUri = resultData?.getStringExtra(OfficeEngineContract.EXTRA_RESULT_URI)
    if (resultUri.isNullOrBlank()) {
        onOutput(
            resultData?.getStringExtra(OfficeEngineContract.EXTRA_RESULT_JSON)
                ?: officeEngineFailureJson("Office engine returned no converted document")
        )
        onBusy(false)
        return
    }

    onOutput("Parsing converted file...")
    scope.launch {
        outputConvertedMarkdown(
            resultUri = resultUri,
            sourceName = sourceName,
            sourceFormat = sourceFormat,
            copyUriToCache = copyUriToCache,
            onOutput = onOutput,
            onBusy = onBusy,
        )
    }
}

private suspend fun outputConvertedMarkdown(
    resultUri: String,
    sourceName: String,
    sourceFormat: String,
    copyUriToCache: (Uri) -> File,
    onOutput: (String) -> Unit,
    onBusy: (Boolean) -> Unit,
) {
    val markdown = withContext(Dispatchers.IO) {
        runCatching {
            val convertedFile = copyUriToCache(Uri.parse(resultUri))
            PythonBridge.parseConvertedFileMarkdown(convertedFile, sourceName, sourceFormat)
        }.getOrElse { error ->
            officeEngineFailureJson(error.message ?: error::class.java.simpleName)
        }
    }
    onOutput(markdown)
    onBusy(false)
}

private fun officeEngineFailureJson(message: String): String =
    """{"status":"failed","message":"${jsonEscape(message)}"}"""

private fun jsonEscape(value: String): String =
    value
        .replace("\\", "\\\\")
        .replace("\"", "\\\"")
        .replace("\n", "\\n")
        .replace("\r", "\\r")
