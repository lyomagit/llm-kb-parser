package com.lyomagit.kbparser

import android.net.Uri
import android.os.Bundle
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
                    Phase0Screen(
                        copyUriToCache = ::copyUriToCache,
                    )
                }
            }
        }
    }

    private fun copyUriToCache(uri: Uri): File {
        val name = contentResolver.query(uri, null, null, null, null)?.use { cursor ->
            val index = cursor.getColumnIndex("_display_name")
            if (index >= 0 && cursor.moveToFirst()) cursor.getString(index) else null
        } ?: "selected-document"
        val safeName = name.replace(Regex("""[^\w.\- ]"""), "_")
        val out = File(cacheDir, safeName)
        contentResolver.openInputStream(uri).use { input ->
            requireNotNull(input) { "Could not open selected document" }
            out.outputStream().use { output -> input.copyTo(output) }
        }
        return out
    }
}

@Composable
private fun Phase0Screen(copyUriToCache: (Uri) -> File) {
    var output by remember { mutableStateOf("Ready. Phase 0 supports XLS and XLSX only.") }
    var busy by remember { mutableStateOf(false) }
    val scope = rememberCoroutineScope()
    val launcher = rememberLauncherForActivityResult(ActivityResultContracts.OpenDocument()) { uri ->
        if (uri == null) return@rememberLauncherForActivityResult
        busy = true
        output = "Parsing selected file..."
        scope.launch {
            output = withContext(Dispatchers.IO) {
                runCatching {
                    val file = copyUriToCache(uri)
                    PythonBridge.parseFile(file)
                }.getOrElse { error ->
                    """{"status":"failed","message":"${error.message ?: error::class.java.simpleName}"}"""
                }
            }
            busy = false
        }
    }

    Column(
        modifier = Modifier
            .fillMaxSize()
            .padding(20.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        Text("KBParser Android Spike", style = MaterialTheme.typography.headlineSmall)
        Text("Phase 0 embeds the Python core with Chaquopy. DOC, DOCX, PDF, and OCR are disabled until their Android backends are proven.")
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            Button(
                enabled = !busy,
                onClick = {
                    launcher.launch(
                        arrayOf(
                            "application/vnd.ms-excel",
                            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        )
                    )
                },
            ) {
                Text(if (busy) "Working" else "Choose XLS/XLSX")
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
