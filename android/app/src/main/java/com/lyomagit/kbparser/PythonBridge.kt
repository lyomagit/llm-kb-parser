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
}
