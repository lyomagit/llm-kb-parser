package com.lyomagit.kbparser

import com.chaquo.python.Python
import java.io.File

object PythonBridge {
    fun capabilitiesJson(): String {
        val module = Python.getInstance().getModule("kbparser.mobile.facade")
        return module.callAttr("android_capabilities_json").toString()
    }

    fun parseFile(file: File): String {
        val module = Python.getInstance().getModule("kbparser.mobile.facade")
        return module.callAttr("parse_path_json", file.absolutePath, "balanced").toString()
    }

    fun parseFileMarkdown(file: File): String {
        val module = Python.getInstance().getModule("kbparser.mobile.facade")
        return module.callAttr("parse_path_markdown", file.absolutePath, "balanced").toString()
    }

    fun parseConvertedFileMarkdown(file: File, sourceName: String, sourceFormat: String): String {
        val module = Python.getInstance().getModule("kbparser.mobile.facade")
        // The last two positional args map to original_source_name and original_source_format.
        return module.callAttr(
            "parse_path_markdown",
            file.absolutePath,
            "balanced",
            sourceName,
            sourceFormat,
        ).toString()
    }
}
